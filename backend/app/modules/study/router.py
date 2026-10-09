"""API обезличенной статистики прохождения (/api/study/*).

Для вошедшего пользователя: состояние (`me`), включение после показа уведомления (`enroll`), отказ (`decline`), события
экранов и ошибок, необязательная анкета. Открытая публичная сводка для /validation — пустая при N < 3 завершённых путей.
Для администратора — служебная сводка. Автотесты, служебные и демо-учётки в статистику не входят (exclude.py).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import err
from app.core.ratelimit import SlidingWindow, hit
from app.modules.auth.models import User
from app.modules.study import report, service, texts

router = APIRouter(prefix="/api/study", tags=["study"])
TAGS = [{"name": "study", "description": "Обезличенная статистика прохождения у жюри и посетителей стенда: уведомление и отказ, "
                                         "путь, необязательная анкета SUS и оценки топ-5, сводка для /validation (при N ≥ 3)"}]
admin = require_role(UserRole.admin)

_ev_user = SlidingWindow(240, 60)
_sub_user = SlidingWindow(20, 60)
_enroll_user = SlidingWindow(30, 60)


class EnrollIn(BaseModel):
    automation: bool = Field(False, description="Браузер сообщил navigator.webdriver: автотест в статистику не входит")
    again: bool = Field(False, description="Отказавший сам просит включить статистику снова")


class EventIn(BaseModel):
    kind: Literal["view", "error"]
    key: str = Field(..., min_length=1, max_length=300, description="Путь экрана или API (идентификаторы заменяются на :id)")
    status: int | None = Field(None, ge=0, le=599)
    code: str | None = Field(None, max_length=64)


class RatingIn(BaseModel):
    ref: str = Field(..., max_length=32)
    rating: int = Field(..., ge=1, le=5)


class SurveyIn(BaseModel):
    sus: list[int] | None = Field(None, max_length=10, description="10 ответов шкалы SUS, 1–5, в порядке пунктов, или не передавать")
    ratings: list[RatingIn] | None = Field(None, description="Оценки всех показанных кандидатов подборки (работодатель)")
    belief: int | None = Field(None, ge=1, le=5, description="«Верю грейду», 1–5")
    grade_fit: Literal["lower", "fit", "higher"] | None = Field(None, description="Кандидат: грейд занижен / соответствует / завышен")
    tags: list[str] | None = Field(None, max_length=10)
    comment: str | None = Field(None, max_length=2000)
    need_id: str | None = Field(None, max_length=40, description="Потребность, подборку которой оценивали (из адреса экрана)")
    version: int | None = Field(None, ge=1, le=10_000)


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")


@router.get("/me", summary="Состояние статистики для пользователя: new | on (шаги пути) | declined | excluded")
def me(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.me(db, user, ua=_ua(request))


@router.post("/enroll", summary="Включить сбор после показа уведомления (автотесты и служебные учётки не включаются)")
def enroll(data: EnrollIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    hit(_enroll_user, str(user.id), "study_rate_limited", "Слишком много запросов")
    return service.enroll(db, user, ua=_ua(request), automation=data.automation, again=data.again)


@router.post("/decline", summary="«Не участвовать»: собранное по записи удаляется, сбор больше не ведётся")
def decline(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    hit(_enroll_user, str(user.id), "study_rate_limited", "Слишком много запросов")
    return service.decline(db, user)


@router.post("/events", status_code=204, summary="Событие экрана или ошибка интерфейса (обезличенно; без включённой статистики — без последствий)")
def events(data: EventIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    hit(_ev_user, str(user.id), "study_rate_limited", "Слишком много событий")
    service.record_event(db, user, data.kind, data.key, data.status, data.code, ua=_ua(request))
    return Response(status_code=204)


@router.get("/survey", summary="Анкета после пути: SUS, оценки топ-5 (работодатель), доверие к грейду, «что мешало»",
            responses={404: err("Статистика прохождения у пользователя не ведётся")})
def survey(need_id: str | None = None, version: int | None = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)) -> dict:
    return service.form(db, user, need_id, version)


@router.post("/survey", summary="Сдать анкету (необязательна; любая часть; повторная отправка заменяет ответы)",
             responses={404: err("Статистика прохождения у пользователя не ведётся"), 422: err("Неполные или неверные ответы")})
def submit(data: SurveyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    hit(_sub_user, str(user.id), "study_rate_limited", "Слишком много отправок")
    return service.submit(db, user, sus=data.sus, ratings=[r.model_dump() for r in data.ratings or []], belief=data.belief,
                          grade_fit=data.grade_fit, tags=data.tags, comment=data.comment, need_id=data.need_id,
                          version=data.version)


@router.post("/survey/shown", summary="Отметить, что анкета показана: повторно её не предлагают")
def survey_shown(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.mark_prompted(db, user)


@router.get("/summary", summary="Сводка «Живые пользователи» для /validation (shown=false при N < 3 завершённых путей)")
def summary(db: Session = Depends(get_db)) -> dict:
    return report.public_summary(db)


@router.get("/admin/report", summary="Служебная сводка по участникам (шаги, время, ошибки; без имён и почт)")
def admin_report(texts: bool = False, user: User = Depends(admin), db: Session = Depends(get_db)) -> dict:
    return report.admin_report(db, with_texts=texts)
