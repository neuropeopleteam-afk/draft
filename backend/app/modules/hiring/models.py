"""Найм после принятия приглашения: собеседование (слоты), оффер (со встречным) и исход найма.

Все три сущности привязаны к приглашению (invitations): кандидат принял его, контакты открыты — дальше работодатель
ведёт найм внутри платформы, а этапы уходят в его ATS (app.modules.hiring.ats) и возвращаются обратным каналом.
Правила переходов — app.modules.hiring.service (покрыты tests/test_hiring.py).
"""
from datetime import date, datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk

INTERVIEW_STATUSES = ("proposed", "reschedule", "scheduled", "done", "cancelled")
OFFER_STATUSES = ("sent", "accepted", "declined", "withdrawn", "expired")
OUTCOMES = ("hired", "declined", "rejected")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class HiringInterview(UUIDPk, Timestamps, Base):
    """Собеседование: работодатель предлагает 1–3 слота, кандидат выбирает один или просит другое время.

    proposed → scheduled (кандидат выбрал слот) | reschedule (попросил другое время) → proposed (новые слоты);
    scheduled → done (работодатель отметил «прошло») | proposed (перенос) ; любое активное → cancelled.
    Слот: {id, starts_at (UTC ISO), duration_min, format: video | phone | office, place: ссылка или адрес}.
    """

    __tablename__ = "hiring_interviews"
    __table_args__ = (
        sa.CheckConstraint(_in("status", INTERVIEW_STATUSES), name="status"),
        sa.Index("ix_hiring_interviews_invitation_created", "invitation_id", "created_at"),
        sa.Index("ix_hiring_interviews_status_starts", "status", "starts_at"),
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    round: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column(sa.String(120))
    status: Mapped[str] = mapped_column(sa.String(16), default="proposed")
    slots: Mapped[list] = mapped_column(default=list)
    chosen_slot: Mapped[str | None] = mapped_column(sa.String(8))
    starts_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_min: Mapped[int | None]
    format: Mapped[str | None] = mapped_column(sa.String(16))
    place: Mapped[str | None] = mapped_column(sa.String(500))
    note: Mapped[str | None] = mapped_column(sa.Text)  # комментарий работодателя к слотам
    candidate_note: Mapped[str | None] = mapped_column(sa.Text)  # «прошу другое время»: когда удобно
    reschedules: Mapped[int] = mapped_column(default=0)
    reminded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    result_note: Mapped[str | None] = mapped_column(sa.Text)


class HiringOffer(UUIDPk, Timestamps, Base):
    """Оффер: сумма (не ниже «от» вилки приглашения), дата выхода, срок ответа.

    sent → accepted | declined | withdrawn (работодатель отозвал) | expired (срок ответа прошёл).
    Встречное кандидата (counters, механика как у встречного на приглашение): своя сумма выше предложенной, не выше
    1,5 × оффера; одно ожидающее, не больше двух. Работодатель принимает встречное → сумма заменяется, оффер принят;
    отклоняет → оффер остаётся открытым с прежней суммой.
    """

    __tablename__ = "hiring_offers"
    __table_args__ = (
        sa.CheckConstraint(_in("status", OFFER_STATUSES), name="status"),
        sa.CheckConstraint("salary > 0", name="salary_positive"),
        sa.Index("ix_hiring_offers_invitation_created", "invitation_id", "created_at"),
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    salary: Mapped[int]
    salary_basis: Mapped[str] = mapped_column(sa.String(8), default="gross")
    start_date: Mapped[date] = mapped_column(sa.Date)
    respond_until: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(16), default="sent")
    # [{id, salary, salary_basis, comment, status: pending|accepted|declined|withdrawn, at, decided_at, note}]
    counters: Mapped[list] = mapped_column(default=list)
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(sa.Text)


class HiringOutcome(UUIDPk, Base):
    """Исход найма по приглашению (один): hired — вышел на работу, declined — отказ кандидата,
    rejected — не прошёл (решение работодателя). Уходит в ATS этапом, этап возвращается обратным каналом."""

    __tablename__ = "hiring_outcomes"
    __table_args__ = (sa.CheckConstraint(_in("outcome", OUTCOMES), name="outcome"),)

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"), unique=True)
    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    outcome: Mapped[str] = mapped_column(sa.String(16))
    start_date: Mapped[date | None] = mapped_column(sa.Date)
    note: Mapped[str | None] = mapped_column(sa.Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
