"""Модуль profiles: профиль кандидата, компания и профиль работодателя, факты с уровнем доказанности."""
from datetime import datetime
from decimal import Decimal
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum, utcnow
from app.core.enums import EvidenceLevel, FactSource, WorkFormat


class CandidateProfile(Timestamps, Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (sa.CheckConstraint("salary_min_hidden IS NULL OR salary_min_hidden > 0", name="salary_min"),)

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Персональные данные — работодатель видит их только после принятия приглашения.
    full_name: Mapped[str | None] = mapped_column(sa.String(200))
    phone: Mapped[str | None] = mapped_column(sa.String(32))
    telegram: Mapped[str | None] = mapped_column(sa.String(64))
    city: Mapped[str | None] = mapped_column(sa.String(100))
    work_format: Mapped[WorkFormat] = mapped_column(str_enum(WorkFormat, "work_format"), default=WorkFormat.any)
    relocation: Mapped[bool] = mapped_column(default=False)
    experience_years: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 1))
    headline: Mapped[str | None] = mapped_column(sa.String(200))
    about: Mapped[str | None] = mapped_column(sa.Text)
    # Скрытый минимум зарплаты: работодателю не показывается никогда.
    salary_min_hidden: Mapped[int | None]
    # Текущая подтверждённая категория (только по результатам теста, не по самоописанию).
    current_direction_id: Mapped[str | None] = mapped_column(sa.ForeignKey("directions.id"))
    current_grade_id: Mapped[str | None] = mapped_column(sa.ForeignKey("grades.id"))
    current_category_id: Mapped[str | None] = mapped_column(sa.ForeignKey("categories.id"), index=True)
    rating_score: Mapped[float | None]
    # «Junior (предварительно)»: тест на Junior не подтвердил грейд, но и не доказал уровень ниже порога.
    # Категория видна работодателю с пометкой и уровнем доказанности; подтверждение — не смена грейда.
    grade_provisional: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    grade_locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Приватность: что видно работодателю в обезличенной карточке.
    privacy: Mapped[dict] = mapped_column(default=dict)
    visible_to_employers: Mapped[bool] = mapped_column(default=False)
    # Обезличенный идентификатор для работодателя (К-XXXXXX): по нему идут подборки, зонды, приглашения.
    public_ref: Mapped[str | None] = mapped_column(sa.String(16), unique=True)
    # Опрос после регистрации пройден
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Роли в команде (самоописание, T0)
    roles: Mapped[list] = mapped_column(default=list)
    # Заявленный кандидатом ФСП ID (заглушка до подключения ФСП ID на Keycloak)
    fsp_id_claimed: Mapped[str | None] = mapped_column(sa.String(64))
    # Демо-режим жюри: снимает правило «смена грейда не чаще раза в 90 дней» для этой учётной записи
    jury_mode: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    age_group: Mapped[str] = mapped_column(sa.String(8), default="18+", server_default="18+")
    parental_consent: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    parental_consent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Учётная запись удалена кандидатом (md01): запись остаётся обезличенной — только public_ref для истории работодателей
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class CandidateSpecialization(Timestamps, Base):
    """Категория одного направления. История — grade_history по (user_id, direction_id).

    Поля current_* профиля зеркалируют только основное направление для старых клиентов.
    declared — опрос без подтверждения; provisional зарезервирован для потока статусов.
    """

    __tablename__ = "candidate_specializations"
    __table_args__ = (
        sa.CheckConstraint("status IN ('declared', 'confirmed', 'provisional')", name="status"),
        sa.CheckConstraint(
            "(grade_id IS NULL AND category_id IS NULL) OR "
            "(grade_id IS NOT NULL AND category_id IS NOT NULL AND category_id = direction_id || '.' || grade_id)",
            name="category_direction",
        ),
        sa.Index("ix_candidate_specializations_category_id", "category_id"),
        sa.Index("uq_candidate_specializations_primary", "user_id", unique=True,
                 sqlite_where=sa.text("is_primary = 1"), postgresql_where=sa.text("is_primary = true")),
        sa.Index("uq_candidate_specializations_secondary", "user_id", unique=True,
                 sqlite_where=sa.text("is_primary = 0"), postgresql_where=sa.text("is_primary = false")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), primary_key=True)
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    grade_id: Mapped[str | None] = mapped_column(sa.ForeignKey("grades.id"))
    category_id: Mapped[str | None] = mapped_column(sa.ForeignKey("categories.id"))
    status: Mapped[str] = mapped_column(sa.String(32), default="declared", server_default="declared")
    theta: Mapped[float | None]
    theta_se: Mapped[float | None]
    rating_score: Mapped[float | None]
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    test_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("test_sessions.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Company(UUIDPk, Timestamps, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(sa.String(200))
    inn: Mapped[str | None] = mapped_column(sa.String(12))
    industry: Mapped[str | None] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text)
    website: Mapped[str | None] = mapped_column(sa.String(255))
    city: Mapped[str | None] = mapped_column(sa.String(100))
    contact_email: Mapped[str | None] = mapped_column(sa.String(254))
    contact_phone: Mapped[str | None] = mapped_column(sa.String(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())


class EmployerProfile(Timestamps, Base):
    __tablename__ = "employer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    full_name: Mapped[str | None] = mapped_column(sa.String(200))
    position: Mapped[str | None] = mapped_column(sa.String(200))


class CandidateFact(UUIDPk, Base):
    """Факт о кандидате с уровнем доказанности T0/T1/T2.

    Категоризация и ранжирование используют только T1/T2; T0 показывается как «заявлено».
    """

    __tablename__ = "candidate_facts"
    __table_args__ = (sa.Index("ix_candidate_facts_user_level", "user_id", "evidence_level"),)

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sa.String(32))  # skill | stack | experience | achievement | test_result
    key: Mapped[str] = mapped_column(sa.String(100))  # например, stack_tag id или skill id
    title: Mapped[str] = mapped_column(sa.String(255))
    value: Mapped[dict] = mapped_column(default=dict)
    evidence_level: Mapped[EvidenceLevel] = mapped_column(str_enum(EvidenceLevel, "evidence_level"))
    source: Mapped[FactSource] = mapped_column(str_enum(FactSource, "fact_source"))
    source_ref: Mapped[str | None] = mapped_column(sa.String(100))  # test_session:<uuid>, fsp_achievement:<uuid>
    weight: Mapped[float] = mapped_column(default=1.0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class CandidateResume(UUIDPk, Base):
    """Загруженное резюме. Исходный PDF не хранится: только текст с вырезанными ФИО и контактами
    (вырезаются локально, до любой отправки во внешние сервисы) и извлечённые поля (все — T0)."""

    __tablename__ = "candidate_resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(sa.String(255))
    size_bytes: Mapped[int]
    page_count: Mapped[int] = mapped_column(default=0)
    text_redacted: Mapped[str] = mapped_column(sa.Text, default="")
    # Сколько и каких ПДн найдено и вырезано (без самих значений)
    pii_summary: Mapped[dict] = mapped_column(default=dict)
    extracted: Mapped[dict] = mapped_column(default=dict)
    method: Mapped[str] = mapped_column(sa.String(32), default="rules")  # rules | llm+rules
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
