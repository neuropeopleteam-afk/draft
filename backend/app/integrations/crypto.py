"""Шифрование секретов интеграций в БД (токены Хантфлоу, секрет вебхука): Fernet (AES-128-CBC + HMAC-SHA256).

Ключ — INTEGRATIONS_SECRET_KEY или производный от JWT_SECRET (SHA-256). Утечка дампа БД без ключа не раскрывает токены.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.integrations.settings import get_isettings


def _fernet() -> Fernet:
    s = get_isettings()
    raw = (s.integrations_secret_key or f"integrations:{s.jwt_secret}").encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def mask(value: str | None) -> str | None:
    """Для показа в интерфейсе: только последние 4 символа."""
    if not value:
        return None
    return "•" * 6 + value[-4:]
