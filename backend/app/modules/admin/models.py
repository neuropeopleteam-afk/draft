"""Модели заявок на тарифы работодателей и обращений в службу поддержки (миграция a1_01)."""
from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class TariffRequest(UUIDPk, Base):
    """Заявка работодателя или гостя на подключение тарифа «Найм» или «Партнёр ФСП»."""

    __tablename__ = "tariff_requests"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    plan: Mapped[str] = mapped_column(sa.String(16), default="hire")
    company_name: Mapped[str] = mapped_column(sa.String(200))
    contact_name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    contact_email: Mapped[str] = mapped_column(sa.String(254))
    contact_phone: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")  # pending | approved | rejected
    admin_note: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class SupportTicket(UUIDPk, Base):
    """Обращение пользователя или гостя в службу поддержки (/support)."""

    __tablename__ = "support_tickets"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    role: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    email: Mapped[str] = mapped_column(sa.String(254))
    name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    category: Mapped[str] = mapped_column(sa.String(32), default="general")
    subject: Mapped[str] = mapped_column(sa.String(200))
    message: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.String(16), default="open")  # open | resolved | closed
    admin_reply: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
