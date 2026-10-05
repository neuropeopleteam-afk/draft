"""Подписки Web Push (PWA): endpoint push-сервиса браузера и ключи шифрования p256dh/auth."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class PushSubscription(UUIDPk, Base):
    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(sa.String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(sa.String(255))
    auth: Mapped[str] = mapped_column(sa.String(255))
    user_agent: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    last_success_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(default=0)
