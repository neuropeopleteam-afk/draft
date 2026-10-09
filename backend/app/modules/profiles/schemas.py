from datetime import datetime
from decimal import Decimal
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import UserRole, WorkFormat


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CandidateProfileOut(_ORM):
    full_name: str | None
    phone: str | None
    telegram: str | None
    city: str | None
    work_format: WorkFormat
    relocation: bool
    experience_years: Decimal | None
    headline: str | None
    about: str | None
    salary_min_hidden: int | None = Field(description="Сумма видна только самому кандидату; с его разрешения (включено по "
                                                      "умолчанию, выключается в настройках) работодатель видит лишь "
                                                      "«вилка в ожиданиях / ниже ожиданий»")
    current_direction_id: str | None
    current_grade_id: str | None
    current_category_id: str | None
    rating_score: float | None
    grade_locked_until: datetime | None
    visible_to_employers: bool
    privacy: dict
    public_ref: str | None = Field(None, description="Обезличенный идентификатор для работодателей")
    onboarding_completed_at: datetime | None = None
    roles: list = Field(default_factory=list)
    fsp_id_claimed: str | None = None
    jury_mode: bool = False
    specializations: list[dict] = Field(default_factory=list)
    age_group: Literal["18+", "16-17", "14-15"] = "18+"
    parental_consent: bool = False
    parental_consent_at: datetime | None = None


class CandidateProfileUpdate(BaseModel):
    age_group: Literal["18+", "16-17", "14-15"] | None = None
    parental_consent: bool | None = None
    full_name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=32)
    telegram: str | None = Field(None, max_length=64)
    city: str | None = Field(None, max_length=100)
    work_format: WorkFormat | None = None
    relocation: bool | None = None
    experience_years: Decimal | None = Field(None, ge=0, le=60)
    headline: str | None = Field(None, max_length=200)
    about: str | None = Field(None, max_length=5000)
    salary_min_hidden: int | None = Field(None, gt=0, le=10_000_000)
    # Видимость работодателям управляется согласием на публикацию (POST/DELETE /api/me/consents/publication),
    # видимость отдельных полей — PUT /api/me/privacy.


class CompanyOut(_ORM):
    id: uuid.UUID
    name: str
    inn: str | None
    industry: str | None
    description: str | None
    website: str | None
    city: str | None
    contact_email: str | None
    contact_phone: str | None


class CompanyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    inn: str | None = Field(None, pattern=r"^\d{10}(\d{2})?$")
    industry: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=5000)
    website: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(None, max_length=32)


class EmployerOut(_ORM):
    full_name: str | None
    position: str | None
    company: CompanyOut | None


class FspStatusOut(BaseModel):
    linked: bool = Field(description="False — нейтральное состояние: истории ФСП нет, штрафа нет")
    link_source: str | None = None
    achievements_count: int = 0


class MeOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    is_email_verified: bool
    created_at: datetime
    candidate: CandidateProfileOut | None = None
    employer: EmployerOut | None = None
    fsp: FspStatusOut | None = None
