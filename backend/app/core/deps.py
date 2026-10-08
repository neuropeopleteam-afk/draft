"""Зависимости FastAPI: БД, текущий пользователь, проверка роли."""
from collections.abc import Callable
import uuid

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import UserRole
from app.core.errors import api_error
from app.core.security import decode_access_token
from app.modules.auth.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token:
        raise api_error(401, "not_authenticated", "Требуется вход в систему")
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise api_error(401, "invalid_token", "Токен недействителен или истёк") from None
    if payload.get("typ"):
        # Промежуточные токены второго фактора (пароль принят, код не введён; обязательное подключение) — не вход:
        # их принимают только /api/auth/2fa/* (app/modules/auth/twofa_router.py)
        raise api_error(401, "second_factor_required", "Подтвердите вход кодом из приложения-аутентификатора")
    user = db.get(User, user_id)
    if user is None or not user.is_active or payload.get("ver", 0) != user.token_version:
        raise api_error(401, "invalid_token", "Токен недействителен или истёк")
    return user


def require_role(*roles: UserRole) -> Callable[[User], User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise api_error(403, "forbidden", "Недостаточно прав для этого действия")
        return user

    return checker
