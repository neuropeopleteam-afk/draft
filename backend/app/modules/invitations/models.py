"""Модуль invitations: зонд (короткая задача с вилкой) и приглашение-оффер со статусами и историей.

Правила: вилка «от–до» в рублях обязательна; не более одного приглашения кандидату от одного
работодателя за 30 дней; контакты кандидата раскрываются только после принятия приглашения.
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum, utcnow
from app.core.enums import InvitationStatus, ProbeStatus


class Probe(UUIDPk, Timestamps, Base):
    __tablename__ = "probes"
    __table_args__ = (
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name="salary_range"),
        sa.Index("ix_probes_candidate_status", "candidate_user_id", "status"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    employer_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    need_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="SET NULL"))
    variant_id: Mapped[str | None] = mapped_column(sa.ForeignKey("task_variants.id"))
    title: Mapped[str] = mapped_column(sa.String(200))
    task_text: Mapped[str] = mapped_column(sa.Text)
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    # gross — до вычета НДФЛ, net — на руки (app.modules.contact.salary)
    salary_basis: Mapped[str] = mapped_column(sa.String(8), default="gross", server_default="gross")
    time_limit_s: Mapped[int] = mapped_column(default=900)
    status: Mapped[ProbeStatus] = mapped_column(str_enum(ProbeStatus, "probe_status"), default=ProbeStatus.sent)
    # solution — прислать решение; approach — описать подход; any — на выбор кандидата
    answer_mode: Mapped[str] = mapped_column(sa.String(16), default="any", server_default="any")
    answer: Mapped[dict | None]
    score: Mapped[float | None]
    review: Mapped[dict | None]
    # История статусов: [{status, at, actor}] — видна обеим сторонам
    events: Mapped[list] = mapped_column(default=list)
    viewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Invitation(UUIDPk, Timestamps, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name="salary_range"),
        sa.Index("ix_invitations_pair_created", "company_id", "candidate_user_id", "created_at"),
        sa.Index("ix_invitations_candidate_status", "candidate_user_id", "status"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    employer_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    need_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="SET NULL"))
    probe_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("probes.id", ondelete="SET NULL"))
    position_title: Mapped[str] = mapped_column(sa.String(200))
    offer_description: Mapped[str] = mapped_column(sa.Text)
    salary_from: Mapped[int]
    salary_to: Mapped[int]
    # gross — до вычета НДФЛ, net — на руки (app.modules.contact.salary)
    salary_basis: Mapped[str] = mapped_column(sa.String(8), default="gross", server_default="gross")
    contact_method: Mapped[str] = mapped_column(sa.String(255))  # способ связи со стороны работодателя
    employment_terms: Mapped[dict | None]
    # Подтверждённые факты (T1/T2), на которые опирается приглашение — «приглашение-доказательство».
    evidence: Mapped[list] = mapped_column(default=list)
    status: Mapped[InvitationStatus] = mapped_column(
        str_enum(InvitationStatus, "invitation_status"), default=InvitationStatus.sent
    )
    viewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    contacts_revealed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Кандидат отозвал доступ к контактам после принятия: contacts_revealed_at сброшен, карточка снова обезличена
    contacts_revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(sa.Text)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Этап у работодателя по данным его ATS (обратный канал, app/integrations/ats/stages.py): после «Принять»
    # статус приглашения остаётся accepted (контакты открыты), а этап подбора — {stage, title, stage_name, provider, at}
    ats_stage: Mapped[dict | None]


class InvitationEvent(UUIDPk, Base):
    """История статусов приглашения (видна обеим сторонам по своим записям)."""

    __tablename__ = "invitation_events"

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"), index=True)
    # Разные имена перечислений — уникальные имена CHECK-ограничений в PostgreSQL.
    from_status: Mapped[InvitationStatus | None] = mapped_column(str_enum(InvitationStatus, "invitation_from_status"))
    to_status: Mapped[InvitationStatus] = mapped_column(str_enum(InvitationStatus, "invitation_to_status"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(sa.Text)
    # Событие без смены статуса (from = to): встречное предложение, отзыв и возврат доступа к контактам
    # (app.modules.contact). None — обычная смена статуса.
    kind: Mapped[str | None] = mapped_column(sa.String(32))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class InvitationComplaint(UUIDPk, Base):
    """Жалоба кандидата на приглашение: нереальная вилка, не та роль, спам. Учитывается в индексе доверия."""

    __tablename__ = "invitation_complaints"

    invitation_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"), unique=True)
    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(sa.String(16))
    comment: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
