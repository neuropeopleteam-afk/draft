"""Ответы на опрос SUS (System Usability Scale, Brooke 1996): 10 утверждений, шкала 1–5, балл 0–100."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class SusResponse(UUIDPk, Base):
    __tablename__ = "sus_responses"
    __table_args__ = (
        sa.CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        sa.CheckConstraint("context IN ('e2e', 'jury', 'pilot', 'other')", name="context"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    role: Mapped[str] = mapped_column(sa.String(16))  # candidate | employer | jury | guest
    context: Mapped[str] = mapped_column(sa.String(16), default="e2e")
    answers: Mapped[list] = mapped_column(default=list)  # 10 чисел 1..5 в порядке стандартных утверждений
    score: Mapped[float]
    comment: Mapped[str | None] = mapped_column(sa.Text)
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
