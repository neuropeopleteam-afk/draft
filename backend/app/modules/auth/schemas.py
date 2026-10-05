from datetime import datetime
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
