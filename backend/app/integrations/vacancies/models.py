"""Вакансии работодателя и самостоятельные отклики кандидатов (дополнительный сценарий к приглашениям).

Правила ТЗ: вилка «от–до» в рублях обязательна; контакты кандидата раскрываются работодателю после отклика;
статусы отклика видны обеим сторонам.
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk


class Vacancy(UUIDPk, Timestamps, Base):
    __tablename__ = "vacancies"
    __table_args__ = (
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name="salary_range"),
        sa.CheckConstraint("status IN ('draft', 'published', 'closed')", name="status"),
        sa.Index("ix_vacancies_status_published", "status", "published_at"),
        # И23: импорт из ATS — одна вакансия ATS = одна вакансия платформы (повторный импорт обновляет, не дублирует)
        sa.Index("uq_vacancies_company_source_external", "company_id", "source", "external_id", unique=True),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(sa.String(200))
    category_id: Mapped[str | None] = mapped_column(sa.ForeignKey("categories.id"))
    description: Mapped[str] = mapped_column(sa.Text)
    stack: Mapped[list] = mapped_column(default=list)  # id стек-тегов справочника
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    # gross — до вычета НДФЛ, net — на руки (app.modules.contact.salary)
    salary_basis: Mapped[str] = mapped_column(sa.String(8), default="gross", server_default="gross")
    work_format: Mapped[str] = mapped_column(sa.String(16), default="any")
    city: Mapped[str | None] = mapped_column(sa.String(100))
    status: Mapped[str] = mapped_column(sa.String(16), default="published")
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    # Импорт из ATS (И23, app/integrations/vacancies/ats_import.py): source = 'potok' и id вакансии в «Потоке»;
    # ручные вакансии — NULL. imported_at = updated_at сразу после импорта: правка работодателем позже — повторный
    # импорт её не перетирает
    source: Mapped[str | None] = mapped_column(sa.String(16))
    external_id: Mapped[str | None] = mapped_column(sa.String(64))
    external_url: Mapped[str | None] = mapped_column(sa.String(500))
    imported_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class VacancyApplication(UUIDPk, Timestamps, Base):
    __tablename__ = "vacancy_applications"
    __table_args__ = (
        sa.UniqueConstraint("vacancy_id", "candidate_user_id", name="uq_vacancy_applications_pair"),
        sa.CheckConstraint("status IN ('sent', 'viewed', 'accepted', 'rejected', 'withdrawn')", name="status"),
    )

    vacancy_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    cover_letter: Mapped[str | None] = mapped_column(sa.Text)
    # sent → viewed → accepted (приглашён на собеседование) | rejected; withdrawn — отозван кандидатом
    status: Mapped[str] = mapped_column(sa.String(16), default="sent")
    # История статусов: [{status, at, by, note}] — видна обеим сторонам
    events: Mapped[list] = mapped_column(default=list)
    employer_note: Mapped[str | None] = mapped_column(sa.Text)
    viewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Этап у работодателя по данным его ATS (обратный канал): {stage, title, stage_name, provider, at}
    ats_stage: Mapped[dict | None]
