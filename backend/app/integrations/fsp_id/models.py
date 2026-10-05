"""Состояние входа через ФСП ID: state / nonce / code_verifier (PKCE) и одноразовый билет для фронтенда."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class OidcLoginState(UUIDPk, Base):
    __tablename__ = "oidc_login_states"
    __table_args__ = (sa.CheckConstraint("intent IN ('login', 'link')", name="intent"),)

    state: Mapped[str] = mapped_column(sa.String(64), unique=True)
    nonce: Mapped[str] = mapped_column(sa.String(64))
    code_verifier: Mapped[str] = mapped_column(sa.String(128))
    intent: Mapped[str] = mapped_column(sa.String(8), default="login")
    # Для intent=link — кто связывает аккаунт (вошедший кандидат)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    return_to: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # После callback: одноразовый билет (живёт 5 минут), по нему фронтенд получает наш JWT
    ticket: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    ticket_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Проверенные claims (sub, email, паспорт ФСП) — до согласия нового пользователя на обработку ПДн
    claims: Mapped[dict | None] = mapped_column()
    result_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    error: Mapped[str | None] = mapped_column(sa.String(255))
