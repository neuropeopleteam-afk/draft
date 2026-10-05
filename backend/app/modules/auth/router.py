from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import err
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginIn,
    RegisterIn,
    RegisterOut,
    ResendCodeIn,
    ResendCodeOut,
    TokenOut,
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


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Вход по почте и паролю (JWT)",
    responses={401: err("Неверная почта или пароль"), 403: err("Почта не подтверждена")},
)
def login(data: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    return service.issue_token(service.authenticate(db, data.email, data.password))


@router.post(
    "/token",
    response_model=TokenOut,
    summary="Вход в форме OAuth2 (для кнопки Authorize в Swagger UI)",
    responses={401: err("Неверная почта или пароль"), 403: err("Почта не подтверждена")},
)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenOut:
    return service.issue_token(service.authenticate(db, form.username, form.password))
