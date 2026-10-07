"""Реестр паспортов грейда и открытых ключей подписи.

Подписанный документ хранится строкой (канонический JSON, ровно те байты, что подписаны): любое изменение строки в
БД обнаруживается проверкой подписи («Подпись не сходится»). Статус (отозван, причина) — свойство реестра и в подпись
не входит: отзыв не требует переподписи. user_id — SET NULL: после удаления учётной записи паспорт остаётся в
реестре и показывается как отозванный («учётная запись удалена»), а не пропадает молча.
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class GradePassport(Base):
    __tablename__ = "grade_passports"
    __table_args__ = (sa.Index("ix_grade_passports_user_active", "user_id", "revoked_at"),)

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)  # случайный, 96 бит: ссылку нельзя угадать
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    public_ref: Mapped[str | None] = mapped_column(sa.String(16))
    category_id: Mapped[str] = mapped_column(sa.String(64))
    grade_status: Mapped[str] = mapped_column(sa.String(16))  # confirmed | preliminary
    kid: Mapped[str] = mapped_column(sa.String(64))
    document: Mapped[str] = mapped_column(sa.Text)  # канонический JSON — подписанные байты
    signature: Mapped[str] = mapped_column(sa.String(128))  # Ed25519, base64url
    fingerprint: Mapped[str] = mapped_column(sa.String(64))  # SHA-256 содержания без id и дат выпуска — для перевыпуска
    test_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # superseded | downgraded | integrity_annulled | account_deleted | candidate_revoked | admin
    revoke_reason: Mapped[str | None] = mapped_column(sa.String(32))


class PassportKey(Base):
    """Открытые ключи, которыми когда-либо подписывались паспорта (JWKS /api/passport/keys)."""

    __tablename__ = "passport_keys"

    kid: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    public_key: Mapped[str] = mapped_column(sa.String(64))  # base64url 32 байт
    test_key: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
