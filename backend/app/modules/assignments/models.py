"""Задания работодателя: само задание (набор семейств банка по стеку) и попытки кандидатов."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk

MODES = ("probe", "vacancy", "open")  # зонд конкретным кандидатам | к вакансии | «на общее обозрение»
ATTEMPT_SOURCES = ("probe", "vacancy", "feed")
# offered → in_progress → scored; declined — кандидат отказался; expired — время вышло без ответа
ATTEMPT_STATUSES = ("offered", "in_progress", "scored", "declined", "expired")


class Assignment(UUIDPk, Timestamps, Base):
    __tablename__ = "assignments"
    __table_args__ = (
        sa.CheckConstraint("mode IN ('probe', 'vacancy', 'open')", name="mode"),
        sa.CheckConstraint("status IN ('active', 'closed')", name="status"),
        sa.CheckConstraint("n_tasks >= 3 AND n_tasks <= 5", name="n_tasks"),
        sa.CheckConstraint("salary_from IS NULL OR (salary_from > 0 AND salary_from <= salary_to)", name="salary_range"),
        sa.Index("ix_assignments_mode_status", "mode", "status"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    # Откуда взяты требования: потребность или вакансия (стек и категория можно задать и вручную)
    need_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="SET NULL"))
    vacancy_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(sa.String(16))
    title: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text, default="")  # что проверяем — видно кандидату до старта
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"))
    grade_id: Mapped[str] = mapped_column(sa.ForeignKey("grades.id"))
    stack_tags: Mapped[list] = mapped_column(default=list)  # теги стека, по которым собраны задания
    # Семейства банка: [{family_id, tags, difficulty, format}] — у каждого кандидата свои варианты (seed)
    families: Mapped[list] = mapped_column(default=list)
    coverage: Mapped[dict] = mapped_column(default=dict)  # {covered: [tags], missing: [tags]} — честно о банке
    n_tasks: Mapped[int] = mapped_column(default=5)
    time_limit_min: Mapped[int] = mapped_column(default=15)
    salary_from: Mapped[int | None]  # probe/open: вилка обязательна (правило платформы); vacancy — из вакансии
    salary_to: Mapped[int | None]
    status: Mapped[str] = mapped_column(sa.String(16), default="active")
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    # Задание из песочницы жюри (app.modules.jury.scope): видно в ленте только кандидатам этой песочницы
    jury_scope: Mapped[str | None] = mapped_column(sa.String(16), index=True)


class AssignmentAttempt(UUIDPk, Timestamps, Base):
    """Попытка кандидата. tasks хранит ключи вариантов — наружу отдаётся только публичная часть."""

    __tablename__ = "assignment_attempts"
    __table_args__ = (
        sa.UniqueConstraint("assignment_id", "candidate_user_id", name="uq_assignment_attempts_pair"),
        sa.CheckConstraint("source IN ('probe', 'vacancy', 'feed')", name="source"),
        sa.CheckConstraint("status IN ('offered', 'in_progress', 'scored', 'declined', 'expired')", name="status"),
        sa.Index("ix_assignment_attempts_candidate_status", "candidate_user_id", "status"),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(sa.String(16))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("vacancy_applications.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(sa.String(16), default="offered")
    offered_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    tasks: Mapped[list] = mapped_column(default=list)
    score: Mapped[float | None]  # 0..1
    correct: Mapped[int | None]
    total: Mapped[int | None]
    skills: Mapped[dict] = mapped_column(default=dict)  # {tag: {correct, total, score}} — основа фактов T1
    time_spent_s: Mapped[int | None]
    score_method: Mapped[str | None] = mapped_column(sa.String(16))  # auto | demo
