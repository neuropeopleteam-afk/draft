"""API Web Push: публичный ключ VAPID, подписка устройства, тестовое уведомление."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import api_error, err
from app.integrations.push import service
from app.integrations.push.models import PushSubscription
from app.integrations.settings import get_isettings
from app.modules.auth.models import User

router = APIRouter(prefix="/api/push", tags=["push"])
AUTH = {401: err("Не выполнен вход")}


@router.get("/config", summary="Публичный ключ VAPID (applicationServerKey) и состояние Web Push")
def config() -> dict:
    s = get_isettings()
    return {"enabled": s.push_enabled, "vapid_public_key": s.vapid_public_key if s.push_enabled else None}


class Keys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=255)
    auth: str = Field(min_length=8, max_length=255)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: Keys


@router.post("/subscribe", status_code=201, summary="Подписать это устройство на уведомления", responses=AUTH)
def subscribe(data: SubscriptionIn, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)) -> dict:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=data.endpoint, user_id=user.id, p256dh=data.keys.p256dh, auth=data.keys.auth)
        db.add(sub)
    sub.user_id, sub.p256dh, sub.auth = user.id, data.keys.p256dh, data.keys.auth
    sub.user_agent = (request.headers.get("user-agent") or "")[:255]
    db.commit()
    n = db.scalars(select(PushSubscription.id).where(PushSubscription.user_id == user.id)).all()
    return {"subscribed": True, "devices": len(n)}


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


@router.post("/unsubscribe", summary="Отписать устройство", responses=AUTH)
def unsubscribe(data: UnsubscribeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    db.execute(delete(PushSubscription).where(PushSubscription.endpoint == data.endpoint,
                                              PushSubscription.user_id == user.id))
    db.commit()
    return {"subscribed": False}


@router.get("/status", summary="Сколько моих устройств подписано", responses=AUTH)
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id)).all()
    return {"enabled": get_isettings().push_enabled, "devices": len(rows),
            "last_success_at": max((r.last_success_at.isoformat() for r in rows if r.last_success_at), default=None)}


@router.post("/test", summary="Отправить тестовое уведомление на мои устройства",
             responses={**AUTH, 409: err("Нет подписанных устройств или Web Push не настроен")})
def test(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not get_isettings().push_enabled:
        raise api_error(409, "push_disabled", "Web Push на сервере не настроен")
    path = "/employer" if user.role.value == "employer" else "/candidate"
    sent = service.send_to_user(db, user.id, "Драфт: уведомления работают",
                                "Так будут приходить новые приглашения и статусы откликов.", path, "test")
    if not sent:
        raise api_error(409, "no_devices", "Не удалось доставить: подпишите устройство ещё раз")
    return {"sent": sent}
