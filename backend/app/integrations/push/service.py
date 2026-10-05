"""Отправка Web Push (VAPID, RFC 8291/8292) через pywebpush. Ключи VAPID — только из secrets/vapid.env.

Сбой доставки не влияет на бизнес-операцию: уведомления отправляются в фоне. Подписки, на которые push-сервис
ответил 404/410 (пользователь отписался или переустановил приложение), удаляются.
"""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.integrations.push.models import PushSubscription
from app.integrations.settings import get_isettings

log = logging.getLogger(__name__)
SENT_LOG: list[dict] = []  # для тестов и отладки: последние отправки (без ключей), не более 50


def _remember(item: dict) -> None:
    SENT_LOG.append(item)
    del SENT_LOG[:-50]


def send_to_user(db: Session, user_id: uuid.UUID, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Уведомление на все устройства пользователя. Возвращает число успешных доставок."""
    s = get_isettings()
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
    payload = {"title": title, "body": body, "url": url, "tag": tag or url, "icon": "/icons/icon-192.png",
               "badge": "/icons/badge-72.png"}
    _remember({"user_id": str(user_id), "title": title, "url": url, "devices": len(subs), "enabled": s.push_enabled})
    if not subs or not s.push_enabled:
        return 0
    from pywebpush import WebPushException, webpush

    ok = 0
    for sub in subs:
        try:
            webpush(subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                    data=json.dumps(payload, ensure_ascii=False), vapid_private_key=s.vapid_private_key,
                    vapid_claims={"sub": s.vapid_subject}, ttl=24 * 3600, timeout=10)
            sub.last_success_at = utcnow()
            sub.failures = 0
            ok += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                db.delete(sub)
            else:
                sub.failures += 1
                log.warning("web push failed: %s %s", code, str(e)[:120])
        except Exception as e:  # noqa: BLE001 — сеть, неверный ключ; не роняем фоновую задачу
            sub.failures += 1
            log.warning("web push error: %s", type(e).__name__)
    db.commit()
    return ok


def notify_user(user_id: uuid.UUID | None, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Для фоновых задач: своя сессия БД."""
    if user_id is None:
        return 0
    db = SessionLocal()
    try:
        return send_to_user(db, user_id, title, body, url, tag)
    finally:
        db.close()
