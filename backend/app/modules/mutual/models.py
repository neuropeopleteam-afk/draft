"""Модели взаимного подбора: интересы кандидата, отзывы по подборке, ссылки для руководителя, журнал проверок вилки."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow


class CandidatePreference(Base):
    """Что интересно кандидату (самоописание T0): готовность к предложениям, стек и задачи. В скор match-v1 не входит."""

    __tablename__ = "candidate_preferences"
    __table_args__ = (
        sa.CheckConstraint("offers_status IS NULL OR offers_status IN ('active', 'open', 'not_looking')",
                           name="offers_status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    offers_status: Mapped[str | None] = mapped_column(sa.String(16))
    interest_tags: Mapped[list] = mapped_column(default=list)
    interest_tasks: Mapped[list] = mapped_column(default=list)
    # Сообщать работодателю только «вилка ниже ожиданий / в ожиданиях» (сам минимум не показывается никогда)
    salary_signal: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SelectionFeedback(UUIDPk, Timestamps, Base):
    """Отзыв работодателя о кандидате в подборке: подходит / не подходит + причина. Один на (потребность, кандидат)."""

    __tablename__ = "selection_feedback"
    __table_args__ = (
        sa.UniqueConstraint("need_id", "candidate_ref", name="uq_selection_feedback_need_ref"),
        sa.CheckConstraint("verdict IN ('fit', 'unfit')", name="verdict"),
        sa.CheckConstraint("reason IS NULL OR reason IN ('skill', 'grade', 'format', 'salary', 'other')",
                           name="reason"),
    )

    need_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    candidate_ref: Mapped[str] = mapped_column(sa.String(16))
    verdict: Mapped[str] = mapped_column(sa.String(8))
    reason: Mapped[str | None] = mapped_column(sa.String(16))
    comment: Mapped[str | None] = mapped_column(sa.String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))


class SelectionShare(UUIDPk, Base):
    """Ссылка «только чтение» на версию подборки для нанимающего руководителя: без ПДн, 7 дней, отзывается.
    Хранится только SHA-256 токена — сам токен показывается рекрутеру один раз."""

    __tablename__ = "selection_shares"

    need_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    label: Mapped[str | None] = mapped_column(sa.String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    views: Mapped[int] = mapped_column(default=0, server_default="0")
    last_viewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ShareReaction(UUIDPk, Timestamps, Base):
    """Отметка руководителя по ссылке: «интересно / нет» с комментарием. Одна на (ссылка, кандидат)."""

    __tablename__ = "share_reactions"
    __table_args__ = (
        sa.UniqueConstraint("share_id", "candidate_ref", name="uq_share_reactions_share_ref"),
        sa.CheckConstraint("verdict IN ('interesting', 'no')", name="verdict"),
    )

    share_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("selection_shares.id", ondelete="CASCADE"), index=True)
    candidate_ref: Mapped[str] = mapped_column(sa.String(16))
    verdict: Mapped[str] = mapped_column(sa.String(16))
    comment: Mapped[str | None] = mapped_column(sa.String(500))
    author: Mapped[str | None] = mapped_column(sa.String(80))


class OfferFitCheck(UUIDPk, Base):
    """Журнал сравнений вилки со скрытым минимумом: ограничивает подбор минимума перебором вилок.
    candidate_user_id NULL — вилка потребности для всей подборки (лимит на компанию)."""

    __tablename__ = "offer_fit_checks"
    __table_args__ = (sa.Index("ix_offer_fit_checks_company_created", "company_id", "created_at"),)

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    salary_bucket: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
