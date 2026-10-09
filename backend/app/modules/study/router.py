"""API проверки с живыми пользователями (/api/study/*).

Открытые: страница приглашения по коду, публичная сводка (пустая при N < 3). Для вошедших: привязка к приглашению, состояние
пути, события экранов и ошибок, анкета, отзыв участия. Для администратора: выпуск ссылок и служебная сводка.
Не участник на `me` и `events` получает нейтральный ответ без ошибок: интерфейс спрашивает об этом при каждом входе.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.modules.auth.models import User
from app.modules.study import report, service

router = APIRouter(prefix="/api/study", tags=["study"])
TAGS = [{"name": "study", "description": "Проверка с живыми пользователями: ссылка-приглашение, согласие, путь, анкета SUS, "
                                         "оценки топ-5, сводка для /validation (при N ≥ 3)"}]
admin = require_role(UserRole.admin)

_ip = SlidingWindow(40, 60)  # просмотры и старт по коду: перебор кода — 2^60, лимит — на всякий случай
_ev_user = SlidingWindow(240, 60)
_sub_user = SlidingWindow(20, 60)


class StartIn(BaseModel):
    consent: bool = Field(..., description="Согласие на участие и обезличенную статистику")


class JoinIn(BaseModel):
    code: str = Field(..., min_length=8, max_length=40)


class EventIn(BaseModel):
    kind: Literal["view", "error"]
    key: str = Field(..., min_length=1, max_length=300, description="Путь экрана или API (идентификаторы заменяются на :id)")
    status: int | None = Field(None, ge=0, le=599)
    code: str | None = Field(None, max_length=64)


class RatingIn(BaseModel):
    ref: str = Field(..., max_length=32)
    rating: int = Field(..., ge=1, le=5)


class SurveyIn(BaseModel):
    sus: list[int] = Field(..., min_length=10, max_length=10, description="10 ответов шкалы SUS, 1–5, в порядке пунктов")
    ratings: list[RatingIn] | None = Field(None, description="Оценки показанных кандидатов подборки (работодатель)")
    belief: int | None = Field(None, ge=1, le=5, description="«Верю грейду», 1–5")
    grade_fit: Literal["lower", "fit", "higher"] | None = Field(None, description="Кандидат: грейд занижен / соответствует / завышен")
    tags: list[str] | None = Field(None, max_length=10)
    comment: str | None = Field(None, max_length=2000)


START_PAGE = {"candidate": "/candidate/assessment", "employer": "/employer/needs"}  # куда вести после входа по ссылке


class InvitesIn(BaseModel):
    role: Literal["candidate", "employer"]
    n: int = Field(1, ge=1, le=100)
    batch: str = Field("", max_length=64)
    mode: Literal["register", "quick"] = "quick"
    source: Literal["freelance_paid", "team"] = "freelance_paid"
    is_test: bool = False


@router.get("/invites/{code}", summary="Страница приглашения: роль, шаги, текст согласия (без входа)",
            responses={404: err("Ссылка недействительна")})
def invite(code: str, request: Request, db: Session = Depends(get_db)) -> dict:
    hit(_ip, client_ip(request), "study_rate_limited", "Слишком много обращений к приглашению")
    return service.invite_view(db, service.find(db, code))


@router.post("/invites/{code}/start", summary="Дать согласие и начать путь; в режиме quick — войти без регистрации",
             responses={404: err("Ссылка недействительна"), 410: err("Участие отозвано или приглашение закрыто"),
                        422: err("Нет согласия")})
def start(code: str, data: StartIn, request: Request, db: Session = Depends(get_db)) -> dict:
    hit(_ip, client_ip(request), "study_rate_limited", "Слишком много обращений к приглашению")
    p, user = service.start(db, service.find(db, code), data.consent)
    out: dict[str, Any] = {"role": p.role, "mode": p.mode, "state": "started",
                           "next": f"/register?role={p.role}" if p.mode == "register" else START_PAGE[p.role]}
    if user is not None:
        from app.modules.auth.service import issue_token

        out["token"] = issue_token(user).model_dump(mode="json")
    return out


@router.post("/join", summary="Привязать вошедшего пользователя к приглашению (после регистрации или входа)",
             responses={404: err("Ссылка недействительна"), 409: err("Роль не совпадает или ссылка уже занята"),
                        410: err("Участие отозвано или приглашение закрыто")})
def join(data: JoinIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service.join(db, user, data.code)
    return service.me(db, user)


@router.get("/me", summary="Участвует ли пользователь в проверке и как идёт путь (шаги, время, что дальше)")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.me(db, user)


@router.post("/events", status_code=204, summary="Событие экрана или ошибка интерфейса (обезличенно; не участнику — без последствий)")
def events(data: EventIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    hit(_ev_user, str(user.id), "study_rate_limited", "Слишком много событий")
    service.record_event(db, user, data.kind, data.key, data.status, data.code)
    return Response(status_code=204)


@router.get("/survey", summary="Анкета после пути: SUS, оценки топ-5 (работодатель), доверие к грейду, «что мешало»",
            responses={404: err("Пользователь не участвует в проверке")})
def survey(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.form(db, user)


@router.post("/survey", summary="Сдать анкету (повторная отправка заменяет ответы)",
             responses={404: err("Пользователь не участвует в проверке"), 422: err("Неполные или неверные ответы")})
def submit(data: SurveyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    hit(_sub_user, str(user.id), "study_rate_limited", "Слишком много отправок")
    return service.submit(db, user, sus=data.sus, ratings=[r.model_dump() for r in data.ratings or []], belief=data.belief,
                          grade_fit=data.grade_fit, tags=data.tags, comment=data.comment)


@router.post("/withdraw", summary="Отозвать участие: события пути и анкета удаляются, в цифры участник не входит",
             responses={404: err("Пользователь не участвует в проверке")})
def withdraw(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.withdraw(db, user)


@router.get("/summary", summary="Сводка «Живые пользователи» для /validation (shown=false при N < 3)")
def summary(db: Session = Depends(get_db)) -> dict:
    return report.public_summary(db)


@router.post("/admin/invites", summary="Выпустить ссылки-приглашения (администратор; код показывается один раз)")
def admin_invites(data: InvitesIn, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)) -> dict:
    base = f"{(request.headers.get('x-forwarded-proto') or request.url.scheme).split(',')[0].strip()}://" \
           f"{(request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()}"
    return {"invites": service.create_invites(db, data.role, data.n, batch=data.batch, mode=data.mode, is_test=data.is_test,
                                              source=data.source, base_url=base if "//" in base and not base.endswith("//") else None)}


@router.get("/admin/report", summary="Служебная сводка по участникам (метки, шаги, время, ошибки; без имён и почт)")
def admin_report(texts: bool = False, user: User = Depends(admin), db: Session = Depends(get_db)) -> dict:
    return report.admin_report(db, with_texts=texts)
