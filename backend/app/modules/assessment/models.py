"""Модуль assessment: опрос, банк заданий (семейство → вариант), сессии теста, ответы, история грейда.

Формат банка — см. пакет assessment_bank и docs/ARCHITECTURE.md. Ключи ответов хранятся
только на сервере и никогда не отдаются клиенту. Код кандидатов на сервере не исполняется.
"""
from datetime import datetime
from decimal import Decimal
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, str_enum, utcnow
from app.core.enums import BankDirection, GradeChangeReason, TaskFormat, TestSessionStatus


class SurveyResponse(UUIDPk, Base):
    """Опрос при регистрации: направление, стек, опыт, предполагаемый грейд."""

    __tablename__ = "survey_responses"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"))
    claimed_grade_id: Mapped[str] = mapped_column(sa.ForeignKey("grades.id"))
    experience_years: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 1))
    answers: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class SurveyStackTag(Base):
    __tablename__ = "survey_stack_tags"

    survey_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("survey_responses.id", ondelete="CASCADE"), primary_key=True
    )
    stack_tag_id: Mapped[str] = mapped_column(sa.ForeignKey("stack_tags.id"), primary_key=True)
    self_level: Mapped[int] = mapped_column(sa.SmallInteger, default=1)  # 1 знаком … 3 уверенно


class TaskFamily(Base):
    """Семейство заданий: YAML-описание + генератор generate(seed) -> Variant."""

    __tablename__ = "task_families"

    id: Mapped[str] = mapped_column(sa.String(80), primary_key=True)  # family_id
    direction: Mapped[BankDirection] = mapped_column(str_enum(BankDirection, "bank_direction"), index=True)
    skills: Mapped[list] = mapped_column(default=list)
    target_grades: Mapped[list] = mapped_column(default=list)
    format: Mapped[TaskFormat] = mapped_column(str_enum(TaskFormat, "task_format"))
    invariants: Mapped[dict] = mapped_column(default=dict)
    time_limit_s: Mapped[int]
    canary: Mapped[bool] = mapped_column(default=False)  # канареечное задание для детекта утечек
    prior_difficulty: Mapped[float] = mapped_column(default=0.0)  # предкалибровка по признакам шаблона
    calibrated_difficulty: Mapped[float | None]
    version: Mapped[int] = mapped_column(default=1)
    source_hash: Mapped[str | None] = mapped_column(sa.String(64))
    is_active: Mapped[bool] = mapped_column(default=True)
    quarantined_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    exposure_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class TaskVariant(Base):
    __tablename__ = "task_variants"
    __table_args__ = (sa.UniqueConstraint("family_id", "seed", name="uq_task_variants_family_seed"),)

    id: Mapped[str] = mapped_column(sa.String(100), primary_key=True)  # variant_id = family_id + seed
    family_id: Mapped[str] = mapped_column(sa.ForeignKey("task_families.id", ondelete="CASCADE"), index=True)
    seed: Mapped[int] = mapped_column(sa.BigInteger)
    stem: Mapped[str] = mapped_column(sa.Text)
    code: Mapped[str | None] = mapped_column(sa.Text)
    code_language: Mapped[str | None] = mapped_column(sa.String(24))
    options: Mapped[list | None]
    answer_key: Mapped[dict]
    rubric: Mapped[dict | None]
    meta: Mapped[dict] = mapped_column(default=dict)
    exposure_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class TestSession(UUIDPk, Base):
    __tablename__ = "test_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    survey_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("survey_responses.id", ondelete="SET NULL"))
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"))
    claimed_grade_id: Mapped[str] = mapped_column(sa.ForeignKey("grades.id"))
    status: Mapped[TestSessionStatus] = mapped_column(
        str_enum(TestSessionStatus, "test_session_status"), default=TestSessionStatus.created
    )
    form_seed: Mapped[int] = mapped_column(sa.BigInteger)  # seed сборки формы — воспроизводимость
    is_sandbox: Mapped[bool] = mapped_column(default=False)  # «песочница жюри»
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    score: Mapped[float | None]
    theta: Mapped[float | None]  # оценка уровня
    theta_se: Mapped[float | None]  # стандартная ошибка оценки
    result_grade_id: Mapped[str | None] = mapped_column(sa.ForeignKey("grades.id"))
    result: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class TestSessionItem(UUIDPk, Base):
    __tablename__ = "test_session_items"
    __table_args__ = (sa.UniqueConstraint("session_id", "position", name="uq_test_session_items_position"),)

    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("test_sessions.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[str] = mapped_column(sa.ForeignKey("task_variants.id"))
    position: Mapped[int]
    shown_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TestAnswer(UUIDPk, Base):
    __tablename__ = "test_answers"

    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("test_sessions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("test_session_items.id", ondelete="CASCADE"), unique=True
    )
    answer: Mapped[dict]
    is_correct: Mapped[bool | None]
    score: Mapped[float | None]  # 0..1, для открытых ответов — по рубрике
    grading: Mapped[dict] = mapped_column(default=dict)  # кто/как оценил, эталоны, парные сравнения
    time_spent_ms: Mapped[int | None]
    answered_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class GradeHistory(UUIDPk, Base):
    """История подтверждённого грейда. Грейд не понижается принудительно; смена — не чаще раза в 90 дней."""

    __tablename__ = "grade_history"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"))
    from_grade_id: Mapped[str | None] = mapped_column(sa.ForeignKey("grades.id"))
    to_grade_id: Mapped[str] = mapped_column(sa.ForeignKey("grades.id"))
    reason: Mapped[GradeChangeReason] = mapped_column(str_enum(GradeChangeReason, "grade_change_reason"))
    test_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("test_sessions.id", ondelete="SET NULL"))
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class SandboxTestStart(UUIDPk, Base):
    """Начало теста в демо-режиме жюри (правило 90 дней снято) — для лимита перезапусков за 24 часа.

    Ключ — почта, без внешнего ключа на users: счётчик переживает сброс демо-учёток жюри (иначе сброс +
    перезапуски позволяли бы выкачивать банк заданий).
    """

    __tablename__ = "sandbox_test_starts"

    email: Mapped[str] = mapped_column(sa.String(320), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
