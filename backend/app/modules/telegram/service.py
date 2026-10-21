"""Логика привязки Telegram по одноразовому коду, отправки уведомлений с инлайн-кнопками и обработки вебхука."""
from __future__ import annotations

from datetime import timedelta
import html
import logging
import os
from pathlib import Path
import secrets
from typing import Any
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, as_aware, utcnow
from app.core.enums import InvitationStatus
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.profiles.models import Company
from app.modules.telegram.models import TelegramLink

log = logging.getLogger(__name__)
CODE_TTL_MIN = 30
SECRET_ENV_PATH = Path("/opt/spectrek_fsp/secrets/telegram.env")
_cached_bot_username: str | None = None


def _read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        if SECRET_ENV_PATH.is_file():
            for raw in SECRET_ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return out


def bot_token() -> str:
    tok = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if tok:
        return tok
    return (_read_env_file().get("TELEGRAM_BOT_TOKEN") or "").strip()


def webhook_secret() -> str:
    sec = (os.environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if sec:
        return sec
    return (_read_env_file().get("TELEGRAM_WEBHOOK_SECRET") or "").strip()


def is_configured() -> bool:
    return bool(bot_token())


def bot_username() -> str:
    global _cached_bot_username
    env_name = (os.environ.get("TELEGRAM_BOT_USERNAME") or _read_env_file().get("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@")
    if env_name:
        return env_name
    if _cached_bot_username:
        return _cached_bot_username
    tok = bot_token()
    if tok:
        try:
            r = httpx.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=3.0)
            if r.status_code == 200 and r.json().get("ok"):
                uname = (r.json().get("result") or {}).get("username")
                if uname:
                    _cached_bot_username = str(uname).lstrip("@")
                    return _cached_bot_username
        except Exception:  # noqa: BLE001
            pass
    return "fsp_draft_bot"


def _api_call(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    tok = bot_token()
    if not tok:
        return None
    try:
        r = httpx.post(f"https://api.telegram.org/bot{tok}/{method}", json=payload, timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                return data
            log.warning("telegram %s not ok: %s", method, data.get("description"))
    except Exception:  # noqa: BLE001
        log.exception("telegram %s failed", method)
    return None


def status_out(db: Session, user: User) -> dict[str, Any]:
    link = db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    cfg = is_configured()
    bname = bot_username()
    linked = bool(link and link.chat_id and link.enabled)
    now = utcnow()
    active_code = (
        link.link_code
        if link and link.link_code and link.code_expires_at and as_aware(link.code_expires_at) > now
        else None
    )
    return {
        "configured": cfg,
        "bot_username": bname,
        "linked": linked,
        "enabled": bool(link.enabled) if link else False,
        "tg_username": link.tg_username if linked and link else None,
        "tg_first_name": link.tg_first_name if linked and link else None,
        "linked_at": as_aware(link.linked_at).isoformat() if linked and link and link.linked_at else None,
        "last_sent_at": as_aware(link.last_sent_at).isoformat() if link and link.last_sent_at else None,
        "code": active_code,
        "deep_link": f"https://t.me/{bname}?start={active_code}" if active_code else None,
        "code_expires_at": as_aware(link.code_expires_at).isoformat() if active_code and link and link.code_expires_at else None,
        "status_text": (
            "Уведомления в Telegram подключены"
            if linked and cfg
            else "Бот Telegram готов к привязке"
            if cfg
            else "Бот Telegram ещё не настроен на сервере (токен не задан) — вы можете сгенерировать код привязки заранее"
        ),
    }


def issue_link_code(db: Session, user: User) -> dict[str, Any]:
    link = db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    now = utcnow()
    code = secrets.token_urlsafe(18)
    expires = now + timedelta(minutes=CODE_TTL_MIN)
    if link is None:
        link = TelegramLink(user_id=user.id, link_code=code, code_expires_at=expires, enabled=True)
        db.add(link)
    else:
        link.link_code = code
        link.code_expires_at = expires
        link.enabled = True
    db.commit()
    return status_out(db, user)


def unlink(db: Session, user: User) -> dict[str, Any]:
    link = db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    if link is not None:
        link.chat_id = None
        link.link_code = None
        link.code_expires_at = None
        link.tg_username = None
        link.tg_first_name = None
        link.enabled = False
        db.commit()
    return status_out(db, user)


def build_keyboard(url: str = "/", tag: str | None = None) -> dict[str, Any]:
    base = get_settings().public_base_url.rstrip("/")
    full_url = url if url.startswith(("http://", "https://")) else f"{base}{url if url.startswith('/') else '/' + url}"
    rows: list[list[dict[str, str]]] = [[{"text": "Открыть на платформе", "url": full_url}]]
    if tag and tag.startswith("inv-") and "/candidate/invitations" in url:
        inv_id = tag[4:]
        try:
            uuid.UUID(inv_id)
            rows.append([
                {"text": "Принять", "callback_data": f"inv_accept:{inv_id}"},
                {"text": "Отклонить", "callback_data": f"inv_decline:{inv_id}"},
            ])
        except ValueError:
            pass
    return {"inline_keyboard": rows}


def send_to_user(db: Session, user_id: uuid.UUID, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Отправить уведомление в Telegram привязанному пользователю. Возвращает 1 при успехе, иначе 0."""
    if not is_configured():
        return 0
    link = db.scalar(select(TelegramLink).where(TelegramLink.user_id == user_id))
    if link is None or not link.enabled or not link.chat_id:
        return 0
    text = f"<b>{html.escape(title)}</b>\n{html.escape(body)}"
    kb = build_keyboard(url=url, tag=tag)
    res = _api_call("sendMessage", {
        "chat_id": link.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": kb,
    })
    if res:
        link.last_sent_at = utcnow()
        db.commit()
        return 1
    return 0


def notify_user_telegram(user_id: uuid.UUID, title: str, body: str, url: str = "/", tag: str | None = None) -> None:
    db = SessionLocal()
    try:
        send_to_user(db, user_id, title, body, url, tag)
    except Exception:  # noqa: BLE001
        log.exception("telegram notify_user failed")
    finally:
        db.close()


def handle_update(db: Session, update: dict[str, Any]) -> dict[str, Any]:
    """Обработка входящего обновления от Telegram Bot API (/start <code> и нажатия кнопок Принять/Отклонить)."""
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    chat_id = str(chat.get("id") or "")

    if text.startswith("/start") and chat_id:
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            _api_call("sendMessage", {
                "chat_id": chat_id,
                "text": "Чтобы подключить уведомления «Драфт», нажмите кнопку «Получать в Telegram» в личном кабинете на fsp-draft.ru.",
            })
            return {"ok": True, "action": "welcome"}
        now = utcnow()
        link = db.scalar(select(TelegramLink).where(TelegramLink.link_code == code))
        if link is None or not link.code_expires_at or as_aware(link.code_expires_at) < now:
            _api_call("sendMessage", {
                "chat_id": chat_id,
                "text": "Код привязки не найден или истёк. Запросите новый код в разделе «Приложение и уведомления» на fsp-draft.ru.",
            })
            return {"ok": False, "reason": "invalid_or_expired_code"}
        link.chat_id = chat_id
        link.tg_username = (sender.get("username") or chat.get("username") or "")[:128] or None
        link.tg_first_name = (sender.get("first_name") or chat.get("first_name") or "")[:128] or None
        link.linked_at = now
        link.link_code = None
        link.code_expires_at = None
        link.enabled = True
        db.commit()
        _api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "Уведомления «Драфт» подключены. Сюда будут приходить новые приглашения с вилкой зарплаты и сообщения с кнопками быстрого ответа.",
        })
        return {"ok": True, "action": "linked", "user_id": str(link.user_id)}

    cb = update.get("callback_query") or {}
    cb_id = cb.get("id")
    cb_data = (cb.get("data") or "").strip()
    cb_msg = cb.get("message") or {}
    cb_chat_id = str((cb_msg.get("chat") or {}).get("id") or (cb.get("from") or {}).get("id") or "")

    if cb_data.startswith(("inv_accept:", "inv_decline:")) and cb_chat_id:
        action, inv_raw = cb_data.split(":", 1)
        accept = action == "inv_accept"
        link = db.scalar(select(TelegramLink).where(TelegramLink.chat_id == cb_chat_id, TelegramLink.enabled.is_(True)))
        if link is None:
            if cb_id:
                _api_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Аккаунт не привязан", "show_alert": True})
            return {"ok": False, "reason": "not_linked"}
        try:
            inv_uuid = uuid.UUID(inv_raw)
        except ValueError:
            return {"ok": False, "reason": "bad_invitation_id"}
        inv = db.get(Invitation, inv_uuid)
        if inv is None or inv.candidate_user_id != link.user_id:
            if cb_id:
                _api_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Приглашение не найдено", "show_alert": True})
            return {"ok": False, "reason": "invitation_not_found"}
        if inv.status not in (InvitationStatus.sent, InvitationStatus.viewed):
            if cb_id:
                _api_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "На это приглашение уже дан ответ"})
            return {"ok": True, "action": "already_responded", "status": inv.status.value}

        from app.integrations.events import invitation_answered
        from app.modules.invitations import service as inv_svc

        inv_svc.respond(db, inv, link.user_id, accept=accept, reason=None if accept else "Отклонено через Telegram")
        invitation_answered(inv.id, accepted=accept)

        comp = db.get(Company, inv.company_id)
        comp_name = comp.name if comp else "компании"
        verdict = (
            f"Вы приняли приглашение от {comp_name} («{inv.position_title}») — ваши контакты открыты работодателю."
            if accept
            else f"Вы отклонили приглашение от {comp_name} («{inv.position_title}») — контакты остались скрытыми."
        )
        if cb_id:
            _api_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Приглашение принято" if accept else "Приглашение отклонено"})
        if cb_msg.get("message_id"):
            _api_call("editMessageReplyMarkup", {
                "chat_id": cb_chat_id,
                "message_id": cb_msg["message_id"],
                "reply_markup": build_keyboard(url="/candidate/invitations", tag=None),
            })
        _api_call("sendMessage", {"chat_id": cb_chat_id, "text": verdict})
        return {"ok": True, "action": action, "invitation_id": str(inv.id), "status": inv.status.value}

    return {"ok": True, "action": "ignored"}
