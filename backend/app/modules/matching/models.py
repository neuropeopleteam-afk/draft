"""Модуль matching: потребность работодателя и версии подборок.

Каждое уточнение фильтров создаёт новую версию подборки — прежние не теряются (п. 2.1 ТЗ).
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum, utcnow
from app.core.enums import NeedStatus


class EmployerNeed(UUIDPk, Timestamps, Base):
    __tablename__ = "employer_needs"
    __table_args__ = (
        sa.CheckConstraint(
            "salary_from IS NULL OR salary_to IS NULL OR salary_from <= salary_to", name="salary_range"
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(sa.String(200))
    raw_text: Mapped[str] = mapped_column(sa.Text)  # потребность «как написал работодатель»
    requirements: Mapped[dict] = mapped_column(default=dict)  # структурированные требования
    direction_id: Mapped[str | None] = mapped_column(sa.ForeignKey("directions.id"))
    grade_id: Mapped[str | None] = mapped_column(sa.ForeignKey("grades.id"))
    salary_from: Mapped[int | None]
    salary_to: Mapped[int | None]
    status: Mapped[NeedStatus] = mapped_column(str_enum(NeedStatus, "need_status"), default=NeedStatus.draft)


class SelectionVersion(UUIDPk, Base):
    __tablename__ = "selection_versions"
    __table_args__ = (sa.UniqueConstraint("need_id", "version", name="uq_selection_versions_need_version"),)

    need_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    parent_version: Mapped[int | None]
    filters: Mapped[dict] = mapped_column(default=dict)
    requirements: Mapped[dict] = mapped_column(default=dict)
    # [{candidate_ref, category_id, score, reasons:[{fact_id, level, text}]}] — обезличено
    results: Mapped[list] = mapped_column(default=list)
    algorithm_version: Mapped[str] = mapped_column(sa.String(32), default="v0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class NeedParseJob(UUIDPk, Base):
    """И27: фоновое уточнение разбора потребности моделью и кэш разбора по нормализованному тексту.

    Ответ правилами уходит работодателю сразу, модель работает в фоне (поток процесса api); карточка опрашивает
    задачу. Строка с status=done и свежим created_at служит кэшем: тот же текст (ключ — хеш нормализованного
    текста и подсказок, без ПДн) отдаётся мгновенно. Старые строки удаляются при создании новых."""
    __tablename__ = "need_parse_jobs"

    key: Mapped[str] = mapped_column(sa.String(64), index=True)  # sha256 нормализованного текста + подсказки + версия
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")  # pending | done | failed
    result: Mapped[dict | None] = mapped_column(default=None)  # итоговые требования (словарь + модель)
    delta: Mapped[list | None] = mapped_column(default=None)  # что добавила/предложила модель поверх правил
    llm: Mapped[dict | None] = mapped_column(default=None)  # кто ответил, время, причина отказа
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
