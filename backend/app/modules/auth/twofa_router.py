"""API второго фактора: /api/auth/2fa/* (пользователь) и /api/admin/2fa/* (сброс администратором).

Политика прав (для матрицы tests/security_policy.py):
* GET  /api/auth/2fa, POST /setup, POST /confirm — любой вошедший пользователь ИЛИ токен обязательного
  подключения (typ=2fa_setup); аноним — 401;
* POST /api/auth/2fa/check, /disable, /recovery-codes — любой вошедший пользователь (401 анониму), промежуточные
  токены не принимаются;
* POST /api/auth/2fa/verify — без входа (принимает только промежуточный токен typ=2fa; 401 на любой другой);
* GET /api/admin/2fa/users, POST /api/admin/2fa/reset — только admin (401 аноним, 403 остальные).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, oauth2_scheme, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.modules.auth import twofa
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AdminTwoFactorResetIn,
    TwoFactorCodeIn,
    TwoFactorConfirmOut,
    TwoFactorLoginOut,
    TwoFactorSetupIn,
    TwoFactorSetupOut,
    TwoFactorStatusOut,
    TwoFactorVerifyIn,
)

router = APIRouter(prefix="/api/auth/2fa", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin/2fa", tags=["auth"])
AUTH = {401: err("Не выполнен вход"), 400: err("Код не подошёл или подключение не начато"), 429: err("Слишком много неверных кодов")}
# Перебор кода с одного адреса: 30 попыток за 15 минут (вдобавок к блокировке учётки после 5 неверных подряд)
_verify_ip = SlidingWindow(30, 15 * 60)


def setup_auth(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> tuple[User, bool]:
    """Обычный токен или токен обязательного подключения (роль с обязательным вторым фактором без приложения)."""
    if not token:
        raise api_error(401, "not_authenticated", "Требуется вход в систему")
    return twofa.user_for_setup(db, token)


@router.get("", response_model=TwoFactorStatusOut, summary="Состояние второго фактора текущего пользователя",
            responses={401: err("Не выполнен вход")})
def status(auth: tuple[User, bool] = Depends(setup_auth), db: Session = Depends(get_db)):
    return twofa.status(db, auth[0])


@router.post("/setup", response_model=TwoFactorSetupOut,
             summary="Начать подключение приложения-аутентификатора: QR, ключ для ручного ввода (перевыпуск — с текущим кодом)",
             responses=AUTH)
def setup(data: TwoFactorSetupIn | None = None, auth: tuple[User, bool] = Depends(setup_auth), db: Session = Depends(get_db)):
    return twofa.begin_setup(db, auth[0], data.code if data else None)


@router.post("/confirm", response_model=TwoFactorConfirmOut,
             summary="Подтвердить первый код: второй фактор включён, выданы резервные коды", responses=AUTH)
def confirm(data: TwoFactorCodeIn, auth: tuple[User, bool] = Depends(setup_auth), db: Session = Depends(get_db)):
    user, from_setup_token = auth
    codes = twofa.confirm_setup(db, user, data.code)
    return TwoFactorConfirmOut(recovery_codes=codes, token=twofa.finish_setup_token(db, user) if from_setup_token else None)


@router.post("/check", summary="Проверить код из приложения без входа заново (демонстрация: повтор кода не принимается)",
             responses=AUTH)
def check(data: TwoFactorCodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    method = twofa.verify_second_factor(db, user, data.code)
    return {"ok": True, "method": method}


@router.post("/recovery-codes", response_model=TwoFactorConfirmOut,
             summary="Выпустить новые резервные коды (старые перестают действовать); нужен код", responses=AUTH)
def recovery_codes(data: TwoFactorCodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return TwoFactorConfirmOut(recovery_codes=twofa.regenerate_recovery(db, user, data.code))


@router.post("/disable", summary="Отключить второй фактор (нужен код); для обязательных ролей — 403",
             responses={**AUTH, 403: err("Для роли второй фактор обязателен")})
def disable(data: TwoFactorCodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    twofa.disable(db, user, data.code)
    return {"ok": True, "enabled": False}


@router.post("/verify", response_model=TwoFactorLoginOut,
             summary="Завершить вход: промежуточный токен + код из приложения (или резервный) → токен доступа",
             responses={400: err("Код не подошёл или уже использован"), 401: err("Сеанс входа истёк"),
                        429: err("Слишком много попыток")})
def verify(data: TwoFactorVerifyIn, request: Request, db: Session = Depends(get_db)):
    hit(_verify_ip, client_ip(request), "too_many_attempts", "Слишком много попыток ввода кода с вашего адреса")
    token, ctx, method = twofa.complete_login(db, data.pending_token, data.code)
    return TwoFactorLoginOut(**token.model_dump(), method=method, **ctx)


# ----------------------------------------------------------------------------------------------- администратор

admin = require_role(UserRole.admin)
ADMIN = {401: err("Не выполнен вход"), 403: err("Только для администратора")}


@admin_router.get("/users", summary="Пользователи с подключённым или начатым вторым фактором (администратор)", responses=ADMIN)
def users(db: Session = Depends(get_db), _: User = Depends(admin)):
    return {"items": twofa.admin_list(db), "required_roles": sorted(twofa.get_settings().twofa_required_role_set)}


@admin_router.post("/reset", summary="Сбросить второй фактор пользователю по почте: подключение удаляется, сеансы отзываются",
                   responses={**ADMIN, 404: err("Пользователь не найден или без второго фактора"), 409: err("Нельзя сбросить себе")})
def reset(data: AdminTwoFactorResetIn, db: Session = Depends(get_db), user: User = Depends(admin)):
    return twofa.admin_reset(db, user, data.email)
