"""Переписка по приглашению или отклику и встречные предложения кандидата."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class ContactMessage(UUIDPk, Base):
    """Сообщение в переписке. Тред — приглашение (invitation_id) или отклик на вакансию (application_id).

    mode: qa — до принятия приглашения (контакты в тексте замаскированы при сохранении, лимит сообщений подряд),
    chat — после принятия или по отклику (кандидат сам раскрыл контакты компании).
    """

    __tablename__ = "contact_messages"
    __table_args__ = (
        sa.CheckConstraint("(invitation_id IS NULL) <> (application_id IS NULL)", name="one_thread"),
        sa.CheckConstraint("sender_side IN ('candidate', 'employer')", name="sender_side"),
        sa.CheckConstraint("mode IN ('qa', 'chat')", name="mode"),
        sa.Index("ix_contact_messages_invitation_created", "invitation_id", "created_at"),
        sa.Index("ix_contact_messages_application_created", "application_id", "created_at"),
        sa.Index("ix_contact_messages_sender_created", "sender_user_id", "created_at"),
    )

    invitation_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("vacancy_applications.id", ondelete="CASCADE"))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    sender_side: Mapped[str] = mapped_column(sa.String(16))
    mode: Mapped[str] = mapped_column(sa.String(8))
    body: Mapped[str] = mapped_column(sa.Text)  # уже замаскированный текст (в режиме qa)
    masked: Mapped[int] = mapped_column(default=0, server_default="0")  # сколько контактов скрыто
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))  # прочитано другой стороной
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class InvitationCounter(UUIDPk, Base):
    """Встречное предложение кандидата: своя вилка в ответ на приглашение.

    pending → accepted (работодатель согласился: вилка приглашения заменяется встречной, приглашение принято,
    контакты открыты) | declined (приглашение остаётся открытым с исходной вилкой) | withdrawn (кандидат принял
    исходную вилку, отклонил приглашение или работодатель отозвал приглашение).
    """

    __tablename__ = "invitation_counters"
    __table_args__ = (
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name="salary_range"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'withdrawn')", name="status"),
        sa.Index("ix_invitation_counters_invitation_created", "invitation_id", "created_at"),
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    salary_basis: Mapped[str] = mapped_column(sa.String(8), default="gross")
    # исходная вилка приглашения на момент встречного предложения — для истории
    offer_from: Mapped[int]
    offer_to: Mapped[int]
    comment: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    employer_note: Mapped[str | None] = mapped_column(sa.Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
