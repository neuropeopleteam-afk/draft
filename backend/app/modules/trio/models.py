"""Трёхсторонний канал по приглашению: работодатель, кандидат и представитель ФСП в одной переписке.

status: pending — работодатель позвал ФСП, ждём согласия кандидата (представитель ФСП ещё не видит тред);
active — кандидат согласен (или сам позвал ФСП), пишут все трое; closed — любой участник закрыл канал (только чтение).
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class TrioThread(UUIDPk, Base):
    __tablename__ = "trio_threads"
    __table_args__ = (
        sa.CheckConstraint("status IN ('pending', 'active', 'closed')", name="status"),
        sa.CheckConstraint("created_by_side IN ('candidate', 'employer')", name="created_by_side"),
        sa.UniqueConstraint("invitation_id", name="invitation"),
        sa.Index("ix_trio_threads_candidate", "candidate_user_id"),
        sa.Index("ix_trio_threads_company", "company_id"),
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(sa.String(32), default="general")
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    created_by_side: Mapped[str] = mapped_column(sa.String(16))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class TrioMessage(UUIDPk, Base):
    __tablename__ = "trio_messages"
    __table_args__ = (
        sa.CheckConstraint("sender_side IN ('candidate', 'employer', 'fsp', 'system')", name="sender_side"),
        sa.Index("ix_trio_messages_thread_created", "thread_id", "created_at"),
        sa.Index("ix_trio_messages_sender_created", "sender_user_id", "created_at"),
    )

    thread_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("trio_threads.id", ondelete="CASCADE"))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    sender_side: Mapped[str] = mapped_column(sa.String(16))
    body: Mapped[str] = mapped_column(sa.Text)
    masked: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
