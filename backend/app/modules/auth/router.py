from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.modules.auth import service, twofa
from app.modules.auth.schemas import (
    ForgotPasswordIn,
    ForgotPasswordOut,
    LoginIn,
    RegisterIn,
    RegisterOut,
    ResendCodeIn,
    ResendCodeOut,
    ResetPasswordIn,
    ResetPasswordOut,
    TokenOut,
    TwoFactorChallengeOut,
    VerifyEmailIn,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация по почте (кандидат или работодатель)",
    responses={409: err("Почта уже занята"), 422: err("Ошибка валидации или нет согласия на обработку ПДн")},
)
def register(data: RegisterIn, db: Session = Depends(get_db)) -> RegisterOut:
    user, code = service.register_user(db, data)
    dev = get_settings().effective_dev_mode
    return RegisterOut(user_id=user.id, email=user.email, role=user.role, dev_verification_code=code if dev else None)


@router.post(
    "/verify-email",
    response_model=TokenOut,
    summary="Подтверждение почты кодом; при успехе сразу выдаётся токен",
    responses={400: err("Неверный или просроченный код"), 429: err("Превышено число попыток")},
)
def verify_email(data: VerifyEmailIn, db: Session = Depends(get_db)) -> TokenOut:
    return service.issue_token(service.verify_email(db, data.email, data.code))


@router.post(
    "/resend-code",
    response_model=ResendCodeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Повторная отправка кода подтверждения",
    responses={429: err("Слишком частые запросы")},
)
def resend_code(data: ResendCodeIn, db: Session = Depends(get_db)) -> ResendCodeOut:
    code = service.resend_code(db, data.email)
    return ResendCodeOut(dev_verification_code=code if get_settings().effective_dev_mode else None)


_forgot_ip_rl = SlidingWindow(10, 900)
_forgot_email_rl = SlidingWindow(3, 900)


@router.post(
    "/forgot",
    response_model=ForgotPasswordOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запрос кода восстановления пароля по почте (15 минут, без раскрытия наличия адреса)",
    responses={429: err("Слишком частые запросы")},
)
def forgot_password(request: Request, data: ForgotPasswordIn, db: Session = Depends(get_db)) -> ForgotPasswordOut:
    hit(_forgot_ip_rl, client_ip(request), "too_many_requests", "Слишком частые запросы. Повторите попытку позже")
    hit(_forgot_email_rl, service.normalize_email(data.email), "too_many_requests", "Слишком частые запросы. Повторите попытку позже")
    code = service.forgot_password(db, data.email)
    return ForgotPasswordOut(dev_reset_code=code if get_settings().effective_dev_mode else None)


@router.post(
    "/reset",
    response_model=ResetPasswordOut,
    summary="Установка нового пароля по 6-значному коду из письма (до 5 попыток)",
    responses={400: err("Неверный или просроченный код"), 429: err("Превышено число попыток ввода кода")},
)
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)) -> ResetPasswordOut:
    service.reset_password(db, data.email, data.code, data.new_password)
    return ResetPasswordOut(ok=True)


@router.post(
    "/login",
    response_model=TokenOut | TwoFactorChallengeOut,
    summary="Вход по почте и паролю (JWT); при подключённом втором факторе — промежуточный токен и запрос кода",
    responses={401: err("Неверная почта или пароль"), 403: err("Почта не подтверждена")},
)
def login(data: LoginIn, db: Session = Depends(get_db)) -> TokenOut | TwoFactorChallengeOut:
    user = service.authenticate(db, data.email, data.password)
    # второй фактор подключён → код; обязателен для роли, но не подключён → токен только для подключения
    return twofa.after_first_factor(db, user, landing=None)


@router.post(
    "/token",
    response_model=TokenOut,
    summary="Вход в форме OAuth2 (для кнопки Authorize в Swagger UI)",
    responses={401: err("Неверная почта или пароль"), 403: err("Почта не подтверждена")},
)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenOut:
    user = service.authenticate(db, form.username, form.password)
    out = twofa.after_first_factor(db, user)
    if not isinstance(out, TokenOut):
        # форма OAuth2 не умеет второй шаг: вход таких учёток — через /api/auth/login и /api/auth/2fa/verify
        raise api_error(403, "second_factor_required",
                        "Для этой учётной записи нужен второй фактор: войдите через POST /api/auth/login, затем /api/auth/2fa/verify")
    return out
