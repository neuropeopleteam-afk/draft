"""API подписок и уведомлений.

* /api/employer/needs/{id}/subscription — подписка на потребность (включить, частота, новые подходящие);
* /api/notifications — лента уведомлений кабинета и настройки каналов (для любой роли);
* /api/jury/subs/simulate — «смоделировать нового кандидата» (только песочница жюри).
"""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, get_db, utcnow
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.matching.router import _make_version, _own_need, my_company
from app.modules.subs import delivery, demo, runner, service
from app.modules.subs.models import NeedSubscription, UserNotification

employer_router = APIRouter(prefix="/api/employer", tags=["subscriptions"])
notify_router = APIRouter(prefix="/api/notifications", tags=["subscriptions"])
jury_router = APIRouter(prefix="/api/jury/subs", tags=["jury"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 404: err("Потребность не найдена")}
employer = require_role(UserRole.employer)
TAGS = [{"name": "subscriptions", "description": "Подписка на потребность («новые подходящие»), уведомления кабинета, напоминания"}]


class SubscriptionIn(BaseModel):
    enabled: bool = Field(description="Следить ли за потребностью")
    frequency: Literal["instant", "daily", "weekly"] | None = Field(
        None, description="instant — push сразу и письмо-дайджест раз в день; daily — только дайджест раз в день; "
                          "weekly — только дайджест раз в неделю")


class SeenIn(BaseModel):
    refs: list[str] | None = Field(None, max_length=50, description="Ссылки К-…; пусто — все новые")


def _own(db: Session, user: User, need_id: uuid.UUID) -> EmployerNeed:
    return _own_need(db, my_company(db, user), need_id)


@employer_router.get("/subscriptions", summary="Мои подписки на потребности: включена ли и сколько новых подходящих",
                     responses=AUTH)
def my_subscriptions(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    my_company(db, user)
    counts = service.new_counts(db, user.id)
    subs = db.scalars(select(NeedSubscription).where(NeedSubscription.employer_user_id == user.id)).all()
    return {"items": [{"need_id": str(s.need_id), "enabled": s.enabled, "frequency": s.frequency,
                       "new_count": counts.get(s.need_id, 0),
                       "computed_at": as_aware(s.computed_at).isoformat() if s.computed_at else None} for s in subs],
            "new_total": sum(counts.values())}


@employer_router.get("/needs/{need_id}/subscription", summary="Подписка на потребность: настройки и новые подходящие",
                     description="Новые подходящие — кандидаты, вошедшие в топ-10 подборки после подписки (после теста, "
                                 "смены грейда, нового навыка) и ещё не просмотренные. Строки обезличены, как в подборке.",
                     responses=AUTH)
def get_subscription(need_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    n = _own(db, user, need_id)
    return service.sub_out(db, n, service.get_sub(db, n.id))


@employer_router.put("/needs/{need_id}/subscription", summary="Включить, выключить подписку или изменить частоту",
                     description="Первое включение запоминает, кто в топ-10 сейчас: они не считаются новыми.",
                     responses=AUTH)
def put_subscription(need_id: uuid.UUID, data: SubscriptionIn, user: User = Depends(employer),
                     db: Session = Depends(get_db)) -> dict:
    n = _own(db, user, need_id)
    if data.enabled and not service.active_need(n):
        raise api_error(409, "need_not_active", "Следить можно за активной потребностью: эта закрыта или в черновике")
    service.subscribe(db, n, user, enabled=data.enabled, frequency=data.frequency)
    return service.sub_out(db, n, service.get_sub(db, n.id))


@employer_router.post("/needs/{need_id}/subscription/seen", summary="Отметить новых подходящих просмотренными",
                      responses=AUTH)
def seen(need_id: uuid.UUID, data: SeenIn | None = None, user: User = Depends(employer),
         db: Session = Depends(get_db)) -> dict:
    n = _own(db, user, need_id)
    sub = service.get_sub(db, n.id)
    if sub is not None:
        service.mark_seen(db, sub, data.refs if data else None)
    return service.sub_out(db, n, sub)


@employer_router.post("/needs/{need_id}/subscription/check", summary="Проверить подписку сейчас (не чаще раза в 30 секунд)",
                      description="Обычно фоновый обход делает это сам; кнопка — для тех, кто не хочет ждать.",
                      responses={**AUTH, 409: err("Подписка выключена или проверена только что")})
def check_now(need_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    n = _own(db, user, need_id)
    sub = service.get_sub(db, n.id)
    if sub is None or not sub.enabled:
        raise api_error(409, "subscription_off", "Подписка выключена")
    if sub.computed_at and (utcnow() - as_aware(sub.computed_at)).total_seconds() < 30:
        return service.sub_out(db, n, sub)  # только что считали
    runner.tick(db, only_employer=user.id, force=True)
    db.expire_all()
    return service.sub_out(db, n, service.get_sub(db, n.id))


@employer_router.post("/needs/{need_id}/subscription/new-version", status_code=201,
                      summary="Обновить подборку: новая версия с теми же условиями, что у слежения",
                      description="Версии подборки — снимки: кандидат, вошедший в топ-10 позже, виден в новой версии "
                                  "с отметкой «новый». Прежние версии сохраняются.", responses=AUTH)
def new_version(need_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    n = _own(db, user, need_id)
    req, filters = service.definition_of(db, n)
    last = db.scalar(select(func.max(SelectionVersion.version)).where(SelectionVersion.need_id == n.id))
    v = _make_version(db, n, user, dict(filters), last, req)
    return {"version": v.version, "parent_version": v.parent_version}


# ------------------------------------------------------------------ уведомления кабинета
class PrefsIn(BaseModel):
    push_enabled: bool | None = None
    email_enabled: bool | None = None
    reminders_enabled: bool | None = None


def _prefs_out(p) -> dict:
    return {"push_enabled": p.push_enabled, "email_enabled": p.email_enabled, "reminders_enabled": p.reminders_enabled}


def _note_out(n: UserNotification) -> dict:
    return {"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "url": n.url,
            "created_at": as_aware(n.created_at).isoformat(), "read": n.read_at is not None,
            "push_state": n.push_state, "email_state": n.email_state, "digest": n.digest, "channels": n.channels,
            "waiting": n.delivery == "pending"}


@notify_router.get("", summary="Лента уведомлений кабинета: что пришло в push и письмах", responses={401: err("Не выполнен вход")})
def feed(unread_only: bool = False, limit: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user),
         db: Session = Depends(get_db)) -> dict:
    q = select(UserNotification).where(UserNotification.user_id == user.id)
    if unread_only:
        q = q.where(UserNotification.read_at.is_(None))
    rows = db.scalars(q.order_by(UserNotification.created_at.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(UserNotification)
                       .where(UserNotification.user_id == user.id, UserNotification.read_at.is_(None))) or 0
    return {"items": [_note_out(n) for n in rows], "unread": unread, "prefs": _prefs_out(delivery.prefs_of(db, user.id)),
            "quiet": {"from": get_settings().subs_quiet_from, "to": get_settings().subs_quiet_to}}


class ReadIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(None, max_length=200, description="Пусто — все")


@notify_router.post("/read", summary="Отметить уведомления прочитанными", responses={401: err("Не выполнен вход")})
def read(data: ReadIn | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    q = update(UserNotification).where(UserNotification.user_id == user.id, UserNotification.read_at.is_(None))
    if data and data.ids:
        q = q.where(UserNotification.id.in_(data.ids))
    r = db.execute(q.values(read_at=utcnow()))
    db.commit()
    return {"read": r.rowcount}


@notify_router.get("/prefs", summary="Настройки уведомлений: push, письма, напоминания", responses={401: err("Не выполнен вход")})
def get_prefs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    p = delivery.prefs_of(db, user.id)
    db.commit()
    return _prefs_out(p)


@notify_router.put("/prefs", summary="Изменить настройки уведомлений", responses={401: err("Не выполнен вход")})
def put_prefs(data: PrefsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    p = delivery.prefs_of(db, user.id)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return _prefs_out(p)


# ------------------------------------------------------------------ песочница жюри
class SimulateIn(BaseModel):
    need_id: uuid.UUID | None = None


@jury_router.post("/simulate", summary="Смоделировать нового кандидата: тест → топ-10 → уведомление (только песочница жюри)",
                  description="Создаёт в вашей песочнице кандидата, который проходит настоящий тест банка, и запускает "
                              "обход подписок для вашего работодателя. Не создаёт и не меняет ничего вне песочницы.",
                  responses={**AUTH, 409: err("Лимит смоделированных кандидатов или нет потребности"),
                             429: err("Слишком часто")})
def simulate(data: SimulateIn | None = None, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return demo.simulate(db, user, data.need_id if data else None)


class FastForwardIn(BaseModel):
    days: Literal[5, 29] = Field(5, description="5 — приглашение без ответа 3 дня и отклик без решения 5 дней; 29 — до конца срока ответа сутки")


@jury_router.post("/fast-forward", summary="Перемотать время: показать напоминания Н6 в песочнице жюри",
                  description="Считает напоминания так, будто прошло 5 или 29 дней: кандидату — приглашение без ответа и "
                              "за сутки до конца срока, работодателю — отклик без решения (в дайджесте). Только песочница.",
                  responses={**AUTH, 422: err("Недопустимое число дней"), 429: err("Слишком часто")})
def fast_forward(data: FastForwardIn | None = None, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return demo.fast_forward(db, user, data.days if data else 5)
