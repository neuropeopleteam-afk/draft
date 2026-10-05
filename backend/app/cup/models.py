"""«Кубок работодателя»: ограниченное по времени соревнование в категории на базе зонда.

Работодатель задаёт категорию, задачу, срок, вилку зарплаты и число приглашений лучшим. Кандидаты категории
участвуют; решения оцениваются автоматически (задания банка, у каждого свой вариант), по рубрике (LLM с запасным
путём «на проверке») или работодателем. Таблица результатов — под псевдонимами («Участник 07»). По окончании лучшим
уходят приглашения с зарплатой из кубка, участие записывается в паспорт ФСП как мероприятие платформы с местом.
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk


class Cup(UUIDPk, Timestamps, Base):
    __tablename__ = "cups"
    __table_args__ = (
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name="salary_range"),
        sa.CheckConstraint("invite_top_n >= 1 AND invite_top_n <= 20", name="invite_top_n"),
        sa.CheckConstraint("starts_at < ends_at", name="period"),
        sa.Index("ix_cups_category_ends", "category_id", "ends_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text, default="")  # суть кубка и задачи — видна до старта
    category_id: Mapped[str] = mapped_column(sa.ForeignKey("categories.id"))
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"))
    grade_id: Mapped[str] = mapped_column(sa.ForeignKey("grades.id"))
    # auto — задания банка с автопроверкой; rubric — открытая задача, оценка по рубрике; employer — оценивает работодатель
    mode: Mapped[str] = mapped_column(sa.String(16))
    task_text: Mapped[str | None] = mapped_column(sa.Text)  # rubric / employer: показывается после старта
    rubric: Mapped[dict | None]  # {criteria: [{id, title, weight, description}], strong, medium, weak}
    task_families: Mapped[list] = mapped_column(default=list)  # auto: семейства банка (варианты — у каждого свои)
    time_limit_min: Mapped[int] = mapped_column(default=15)
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    invite_top_n: Mapped[int] = mapped_column(default=3)
    min_score: Mapped[float] = mapped_column(default=0.5)  # приглашение — только при балле не ниже порога
    position_title: Mapped[str] = mapped_column(sa.String(200))
    offer_description: Mapped[str] = mapped_column(sa.Text)
    contact_method: Mapped[str] = mapped_column(sa.String(255))
    status: Mapped[str] = mapped_column(sa.String(16), default="active")  # active | finished | cancelled
    finalized_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(default=dict)  # итоги: участники, места, приглашения
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())


class CupEntry(UUIDPk, Timestamps, Base):
    """Участие кандидата. tasks хранит ключи вариантов — наружу отдаётся только публичная часть."""

    __tablename__ = "cup_entries"
    __table_args__ = (
        sa.UniqueConstraint("cup_id", "candidate_user_id", name="uq_cup_entries_cup_candidate"),
        sa.Index("ix_cup_entries_candidate", "candidate_user_id"),
    )

    cup_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cups.id", ondelete="CASCADE"), index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(sa.String(32))  # «Участник 07» — в таблице результатов вместо имени
    # joined → in_progress → submitted (ждёт оценки) → scored; expired — время вышло без ответа
    status: Mapped[str] = mapped_column(sa.String(16), default="joined")
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    tasks: Mapped[list] = mapped_column(default=list)
    answer: Mapped[dict | None]  # rubric / employer: {text, link, text_redacted}
    score: Mapped[float | None]  # 0..1
    score_method: Mapped[str | None] = mapped_column(sa.String(16))  # auto | llm | employer | demo
    grading: Mapped[dict | None]
    time_spent_s: Mapped[int | None]
    place: Mapped[int | None]
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("invitations.id", ondelete="SET NULL"))
    invite_note: Mapped[str | None] = mapped_column(sa.String(255))
    passport_status: Mapped[str | None] = mapped_column(sa.String(16))  # written | pending_link
    passport_written_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
