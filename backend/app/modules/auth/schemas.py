from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import UserRole


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="Не менее 8 символов, буквы и цифры")
    role: UserRole = Field(description="candidate или employer")
    full_name: str | None = Field(None, max_length=200)
    company_name: str | None = Field(None, max_length=200, description="Для работодателя")
    consent_processing: bool = Field(description="Согласие на обработку персональных данных (152-ФЗ)")

    @field_validator("role")
    @classmethod
    def _public_role(cls, v: UserRole) -> UserRole:
        if v not in (UserRole.candidate, UserRole.employer):
            raise ValueError("Допустимые роли: candidate, employer")
        return v

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("Пароль должен содержать буквы и цифры")
        return v


class RegisterOut(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    role: UserRole
    email_verification_required: bool = True
    dev_verification_code: str | None = Field(None, description="Только в режиме разработки (DEV_MODE)")


class VerifyEmailIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendCodeIn(BaseModel):
    email: EmailStr


class ResendCodeOut(BaseModel):
    sent: bool = True
    dev_verification_code: str | None = None


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ForgotPasswordOut(BaseModel):
    sent: bool = True
    dev_reset_code: str | None = Field(None, description="Только в режиме разработки (DEV_MODE)")


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128, description="Не менее 8 символов, буквы и цифры")

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("Пароль должен содержать буквы и цифры")
        return v


class ResetPasswordOut(BaseModel):
    ok: bool = True


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    is_email_verified: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------------------------- второй фактор (TOTP)

class TwoFactorChallengeOut(BaseModel):
    """Пароль (или ссылка) принят, но входа ещё нет: нужен код из приложения (или обязательное подключение).
    ``pending_token`` принимают только /api/auth/2fa/verify (или /setup, /confirm при setup_required)."""

    second_factor_required: Literal[True] = True
    pending_token: str
    expires_in: int = Field(description="Секунд до истечения промежуточного токена")
    setup_required: bool = Field(description="Роль с обязательным вторым фактором, приложение ещё не подключено")
    methods: list[str]
    email: str
    role: UserRole
    landing: str | None = None
    persona: str | None = None
    scenario: str | None = None
    shared: bool | None = None


class TwoFactorCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=16, description="6 цифр из приложения или резервный код XXXX-XXXX")


class TwoFactorSetupIn(BaseModel):
    code: str | None = Field(None, min_length=6, max_length=16, description="Текущий код — только при перевыпуске")


class TwoFactorVerifyIn(BaseModel):
    pending_token: str = Field(min_length=16)
    code: str = Field(min_length=6, max_length=16)


class TwoFactorSetupOut(BaseModel):
    secret: str = Field(description="Ключ Base32 для ручного ввода — показывается только при подключении")
    secret_grouped: str
    otpauth_uri: str
    qr_svg: str
    issuer: str
    account: str
    algorithm: str
    digits: int
    period_s: int
    rotation: bool


class TwoFactorConfirmOut(BaseModel):
    enabled: bool = True
    recovery_codes: list[str] = Field(description="Показываются один раз, каждый действует однократно")
    token: TokenOut | None = Field(None, description="Полноценный вход, если подключение шло по токену обязательного подключения")


class TwoFactorStatusOut(BaseModel):
    enabled: bool
    required: bool
    pending_setup: bool
    rotation_pending: bool
    confirmed_at: datetime | None
    last_verified_at: datetime | None
    recovery_codes_left: int
    recovery_codes_total: int
    locked_until: datetime | None
    method: str
    params: dict
    can_disable: bool
    is_demo: bool
    demo_note: str | None


class TwoFactorLoginOut(TokenOut):
    """Итог входа с кодом: токен и контекст первого фактора (куда вести, песочница жюри)."""

    method: str
    landing: str | None = None
    persona: str | None = None
    scenario: str | None = None
    shared: bool | None = None
    code: str | None = None


class AdminTwoFactorResetIn(BaseModel):
    email: EmailStr
