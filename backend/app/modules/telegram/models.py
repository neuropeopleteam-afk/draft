"""Привязка учётной записи (кандидат или работодатель) к чату Telegram."""
from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class TelegramLink(UUIDPk, Base):
    __tablename__ = "telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    link_code: Mapped[str | None] = mapped_column(sa.String(64), unique=True, index=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    chat_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    tg_username: Mapped[str | None] = mapped_column(sa.String(128))
    tg_first_name: Mapped[str | None] = mapped_column(sa.String(128))
    enabled: Mapped[bool] = mapped_column(sa.Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    linked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
