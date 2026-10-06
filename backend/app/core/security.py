"""Пароли (argon2id), JWT и одноразовые коды подтверждения."""
from datetime import timedelta
import hashlib
import hmac
import secrets
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
import jwt

from app.core.config import get_settings
from app.core.db import utcnow

_ph = PasswordHasher()  # argon2id, параметры по умолчанию библиотеки (RFC 9106 low-memory)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def create_access_token(user_id: uuid.UUID, role: str, token_version: int = 0,
                        extra: dict | None = None) -> tuple[str, int]:
    s = get_settings()
    now = utcnow()
    ttl = timedelta(minutes=s.jwt_ttl_minutes)
    payload = {
        **(extra or {}),  # например, jsc — песочница жюри (app/modules/jury/scope.py); стандартные поля не перекрывает
        "sub": str(user_id),
        "role": role,
        "ver": token_version,
        "iss": s.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], issuer=s.jwt_issuer)


def generate_code(length: int = 6) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_code(code: str) -> str:
    """Коды храним только в виде HMAC — утечка БД не раскрывает их."""
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()


def codes_equal(code_hash: str, code: str) -> bool:
    return hmac.compare_digest(code_hash, hash_code(code))
