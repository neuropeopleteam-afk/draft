"""Одноразовые пароли по времени — TOTP (RFC 6238) поверх HOTP (RFC 4226), без сторонних библиотек.

Параметры — те, что понимают все распространённые приложения-аутентификаторы (Яндекс Ключ, Google Authenticator,
Microsoft Authenticator, FreeOTP, Aegis): HMAC-SHA1, 6 цифр, шаг 30 с. Секрет — 160 бит (20 байт) в Base32,
как рекомендует RFC 4226 §4. Проверка — только через ``verify``: сравнение за постоянное время и окно ±N шагов,
чтобы не зависеть от рассинхронизации часов телефона; защита от повтора кода (шаг не старше последнего
использованного) — на уровне хранилища (app/modules/auth/twofa.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD_S = 30
ALGORITHM = "SHA1"
SECRET_BYTES = 20


def generate_secret() -> str:
    """Новый секрет в Base32 без «=»: 32 символа, 160 бит случайности."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    s = secret_b32.strip().replace(" ", "").upper()
    s += "=" * (-len(s) % 8)
    return base64.b32decode(s, casefold=True)


def hotp(secret_b32: str, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226 §5.3: HMAC-SHA1(K, C) → динамическое усечение → digits цифр."""
    mac = hmac.new(_key(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def step_of(ts: float | None = None, period_s: int = PERIOD_S) -> int:
    """Номер шага времени T = floor(unix / period)."""
    return int((time.time() if ts is None else ts) // period_s)


def totp(secret_b32: str, ts: float | None = None, *, period_s: int = PERIOD_S, digits: int = DIGITS) -> str:
    return hotp(secret_b32, step_of(ts, period_s), digits)


def verify(secret_b32: str, code: str, ts: float | None = None, *, window: int = 1,
           period_s: int = PERIOD_S, digits: int = DIGITS) -> int | None:
    """Номер шага, которому соответствует код, или None. Окно ±window шагов (RFC 6238 §5.2 допускает один шаг
    назад; шаг вперёд — на случай, если часы телефона спешат). Все кандидаты проверяются за постоянное время."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != digits or not code.isdigit():
        return None
    now = step_of(ts, period_s)
    found: int | None = None
    for delta in range(-window, window + 1):
        step = now + delta
        if hmac.compare_digest(hotp(secret_b32, step, digits), code) and found is None:
            found = step
    return found


def otpauth_uri(issuer: str, account: str, secret_b32: str, *, period_s: int = PERIOD_S, digits: int = DIGITS) -> str:
    """Ссылка для QR по соглашению Key Uri Format: otpauth://totp/Issuer:account?secret=…&issuer=…"""
    label = quote(f"{issuer}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer, safe='')}"
            f"&algorithm={ALGORITHM}&digits={digits}&period={period_s}")


def grouped(secret_b32: str, size: int = 4) -> str:
    """Ключ для ручного ввода: группами по 4 символа."""
    return " ".join(secret_b32[i:i + size] for i in range(0, len(secret_b32), size))
