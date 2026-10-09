"""Таблицы модуля mydata (миграция md01).

``candidate_interest_events`` — события «работодатель открыл карточку» и «кандидат попал в подборку» без названия
компании: ``company_key`` и ``need_key`` — только ключи для подсчёта различных работодателей и подборок (без внешних
ключей: компания и потребность могут быть удалены, счётчик от этого не ломается). События удаляются вместе с
кандидатом. Старше 90 дней — не нужны (``interest.purge_old``).

``account_deletion_log`` — журнал уничтожения персональных данных (ст. 21 152-ФЗ): дата, роль и перечень категорий с
числом записей. Ни идентификатора учётной записи, ни почты, ни имени в журнале нет.
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class InterestEvent(UUIDPk, Base):
    __tablename__ = "candidate_interest_events"
    __table_args__ = (
        sa.CheckConstraint("kind IN ('card_view', 'selection')", name="kind"),
        sa.Index("ix_candidate_interest_events_cand_created", "candidate_user_id", "created_at"),
    )

    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sa.String(16))  # card_view | selection
    company_key: Mapped[uuid.UUID] = mapped_column(sa.Uuid)  # работодатель (компания); название не хранится в событии
    need_key: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)  # потребность работодателя (для selection)
    rank: Mapped[int | None] = mapped_column(sa.SmallInteger)  # место в подборке (для selection)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class AccountDeletionLog(UUIDPk, Base):
    __tablename__ = "account_deletion_log"

    deleted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    role: Mapped[str] = mapped_column(sa.String(16))
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    reason: Mapped[str] = mapped_column(sa.String(32), default="user_request")  # user_request | consent_revoked
    details: Mapped[dict] = mapped_column(default=dict)  # {"deleted": {категория: число}, "anonymized": {…}}
