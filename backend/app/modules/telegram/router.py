"""API уведомлений в Telegram: статус привязки, выпуск кода deep-link, отвязка, тест и вебхук бота."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.telegram import service as svc

TAGS = [{"name": "telegram", "description": "Уведомления в Telegram: привязка по одноразовому коду и быстрые ответы на приглашения"}]
router = APIRouter(prefix="/api/telegram", tags=["telegram"])
AUTH = {401: err("Не выполнен вход")}


@router.get("/status", summary="Статус привязки Telegram и готовности бота на сервере", responses=AUTH)
def get_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.status_out(db, user)


@router.post("/link", status_code=201, summary="Сгенерировать одноразовый код и ссылку для привязки Telegram", responses=AUTH)
def create_link(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.issue_link_code(db, user)


@router.delete("/link", summary="Отключить уведомления в Telegram и отвязать чат", responses=AUTH)
def delete_link(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.unlink(db, user)


@router.post("/test", summary="Отправить проверочное уведомление в привязанный чат Telegram",
             responses={**AUTH, 409: err("Бот не настроен или чат Telegram ещё не привязан")})
def send_test(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if not svc.is_configured():
        raise api_error(409, "telegram_not_configured", "Токен бота Telegram на сервере ещё не задан")
    path = "/employer/invitations" if user.role.value == "employer" else "/candidate/invitations"
    sent = svc.send_to_user(
        db,
        user.id,
        "Драфт: уведомления в Telegram работают",
        "Сюда будут приходить новые приглашения с вилкой зарплаты и сообщения в диалогах.",
        path,
        "test",
    )
    if not sent:
        raise api_error(409, "telegram_not_linked", "Сначала привяжите Telegram по кнопке «Получать в Telegram»")
    return {"sent": sent}


@router.post("/webhook", summary="Вебхук Telegram Bot API (/start <code> и кнопки Принять / Отклонить)")
def webhook(
    update: dict[str, Any] = Body(default_factory=dict),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    expected = svc.webhook_secret()
    if expected and x_telegram_bot_api_secret_token != expected:
        raise api_error(403, "telegram_webhook_forbidden", "Неверный секрет вебхука")
    return svc.handle_update(db, update or {})
