"""API камеры во время теста по согласию (И16): согласие, режим камеры в сессии, события без кадров, итог.

Кандидат: согласие (дать, отозвать, текст), режим камеры в своей активной сессии, пачки событий из браузера,
свой итог и события. Аналитик ФСП и администратор: обезличенный агрегат. Работодателю отдельного API нет —
он видит только итог в карточке кандидата (profiles/facts.py → integrity.camera).
"""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.proctor import service

router = APIRouter(prefix="/api/proctor", tags=["proctor"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
candidate = require_role(UserRole.candidate)
analyst = require_role(UserRole.fsp_analyst, UserRole.admin)

Mode = Literal["camera", "declined", "unsupported", "denied"]
Kind = Literal["no_face", "multi_face", "blocked", "camera_off", "printscreen"]  # printscreen — снимок экрана (D3)


class StartIn(BaseModel):
    mode: Mode = Field(description="camera — с камерой (нужно действующее согласие); declined — кандидат выбрал "
                                   "«без камеры»; unsupported — браузер не поддерживает анализ видео; denied — нет "
                                   "доступа к камере")
    reason: str | None = Field(None, max_length=120, description="Коротко, почему без камеры (текст ошибки браузера)")
    client: dict[str, str | int | float] | None = Field(
        None, description="Справочно: model, fps, backend, build — без данных о человеке")


class EventIn(BaseModel):
    item_id: str = Field(max_length=64, description="Токен задания сессии (item_id из /api/assessment)")
    kind: Kind
    duration_ms: int = Field(ge=0, le=3_600_000)
    faces: int | None = Field(None, ge=0, le=20, description="Сколько лиц было в кадре (multi_face)")
    at_ms: int | None = Field(None, ge=0, description="Начало интервала по часам браузера, мс Unix — справочно")


class ObservedIn(BaseModel):
    item_id: str = Field(max_length=64)
    ms: int = Field(ge=0, le=7_200_000, description="Сколько миллисекунд камера наблюдала задание")
    frames: int = Field(0, ge=0, le=100_000, description="Проанализировано кадров")
    face: int = Field(0, ge=0, le=100_000, description="Кадров с ровно одним лицом")


class EventsIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list, max_length=100)
    observed: list[ObservedIn] = Field(default_factory=list, max_length=50)


class StopIn(BaseModel):
    reason: Literal["user", "error"] = Field("user", description="user — кандидат выключил камеру; error — сбой камеры "
                                                                 "или модели (дальше тест идёт без камеры)")


def _enabled() -> bool:
    return bool(get_settings().proctor_camera_enabled)


def _require_enabled() -> None:
    if not _enabled():
        raise api_error(409, "camera_disabled", "Камера во время теста на этом стенде выключена (PROCTOR_CAMERA_ENABLED)")


@router.get("/consent", summary="Согласие на анализ видео с камеры: состояние и текст",
            description="Текст согласия — что делается, что хранится, сколько и кто видит; enabled — включена ли камера "
                        "на стенде (PROCTOR_CAMERA_ENABLED, по умолчанию да). Без камеры тест доступен полностью.",
            responses=AUTH)
def get_consent(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return {**service.consent_state(db, user), "enabled": _enabled()}


@router.post("/consent", summary="Дать согласие на анализ видео с камеры (текущая редакция)", status_code=201,
             responses={**AUTH, 409: err("camera_disabled — камера на стенде выключена")})
def grant_consent(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    _require_enabled()
    c = service.grant(db, user)
    db.commit()
    return {"kind": "proctoring", "granted": True, "version": c.document_version}


@router.delete("/consent", summary="Отозвать согласие: камера в текущем тесте выключается, дальше — без камеры",
               responses=AUTH)
def revoke_consent(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    stopped = service.revoke(db, user)
    db.commit()
    return {"kind": "proctoring", "granted": False, "stopped_sessions": stopped}


@router.post("/sessions/{session_id}/start", summary="Режим камеры в активной сессии теста",
             description="camera — нужно действующее согласие (иначе 409 consent_required); повторный вызов после "
                         "перезагрузки страницы включает камеру снова; без камеры → camera — наблюдение с текущего "
                         "задания. declined/unsupported/denied — тест идёт без камеры, работодатель видит нейтральную "
                         "пометку «тест без камеры».",
             responses={**AUTH, 404: err("Сессия не найдена или чужая"),
                        409: err("session_closed; consent_required; camera_disabled"), 422: err("Неизвестный режим")})
def start(session_id: uuid.UUID, data: StartIn, user: User = Depends(candidate),
          db: Session = Depends(get_db)) -> dict:
    if data.mode == "camera":
        _require_enabled()
    ts = service.own_session(db, user, session_id, active=True)
    return service.start(db, user, ts, data.mode, data.reason, data.client)


@router.post("/sessions/{session_id}/events", summary="Пачка событий камеры из браузера (без кадров)",
             description="Интервалы «нет лица», «несколько лиц», «камера закрыта», «камера не передаёт изображение» по "
                         "заданиям и сколько камера наблюдала каждое задание. Принимаются только в открытом окне "
                         "наблюдения; значения ограничиваются сервером; не больше 2000 событий на сессию.",
             responses={**AUTH, 404: err("Сессия не найдена"),
                        409: err("session_closed; camera_not_enabled; camera_stopped; consent_revoked")})
def events(session_id: uuid.UUID, data: EventsIn, user: User = Depends(candidate),
           db: Session = Depends(get_db)) -> dict:
    ts = service.own_session(db, user, session_id, active=True)
    return service.record(db, user, ts, [e.model_dump() for e in data.events],
                          [o.model_dump() for o in data.observed])


@router.post("/sessions/{session_id}/stop", summary="Выключить камеру: дальше тест идёт без камеры",
             responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Сессия закрыта")})
def stop(session_id: uuid.UUID, data: StopIn, user: User = Depends(candidate),
         db: Session = Depends(get_db)) -> dict:
    ts = service.own_session(db, user, session_id, active=True)
    return service.stop(db, user, ts, data.reason)


@router.get("/sessions/{session_id}", summary="Камера в моей сессии: режим, окна наблюдения, итог и свои события",
            responses={**AUTH, 404: err("Сессия не найдена или чужая")})
def get_session(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    ts = service.own_session(db, user, session_id)
    return service.session_view(db, ts, events=True)


@router.get("/me/sessions", summary="Мои тесты: режим камеры и итог по каждому", responses=AUTH)
def my_sessions(user: User = Depends(candidate), db: Session = Depends(get_db)) -> list[dict]:
    return service.my_sessions(db, user)


@router.get("/stats", summary="Кабинет ФСП: обезличенный агрегат по камере (группы меньше 5 скрыты)",
            responses={401: err("Не выполнен вход"), 403: err("Только аналитик ФСП или администратор")})
def stats(days: int | None = None, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    return {**service.stats(db, days if days and 0 < days <= 3650 else None), "enabled": _enabled()}
