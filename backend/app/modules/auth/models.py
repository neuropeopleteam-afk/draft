"""Модуль auth: учётные записи, роли, подтверждение почты, согласия (152-ФЗ)."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum, utcnow
from app.core.enums import ConsentKind, UserRole, VerificationPurpose


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"))
    is_email_verified: Mapped[bool] = mapped_column(default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True)
    # Инкремент отзывает все выданные JWT пользователя (выход со всех устройств).
    token_version: Mapped[int] = mapped_column(default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Внешний идентификатор ФСП ID (sub из Keycloak) — заполняется при связке аккаунтов.
    fsp_subject: Mapped[str | None] = mapped_column(sa.String(255), unique=True)
    # Синтетическая демо-запись (скрипт сидирования). Письма демо-пользователям не отправляются.
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())


class EmailVerification(UUIDPk, Base):
    __tablename__ = "email_verifications"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[VerificationPurpose] = mapped_column(
        str_enum(VerificationPurpose, "verification_purpose"), default=VerificationPurpose.email_confirm
    )
    code_hash: Mapped[str] = mapped_column(sa.String(128))
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class UserTwoFactor(Timestamps, Base):
    """Второй фактор входа (TOTP, RFC 6238) — одна запись на пользователя (app/modules/auth/twofa.py).

    Секрет хранится зашифрованным (Fernet, ключ TWOFA_SECRET_KEY или производный от JWT_SECRET) и никогда не
    возвращается API после подключения. ``confirmed_at`` пустой — подключение начато, но первый код ещё не введён.
    ``pending_secret_enc`` — новый ключ при перевыпуске: старый действует, пока новый не подтверждён.
    ``last_used_step`` — защита от повтора: код шага не новее последнего использованного не принимается.
    ``fail_count``/``locked_until`` — защита от перебора в БД (переживает перезапуск и общая для воркеров).
    """

    __tablename__ = "user_two_factor"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    secret_enc: Mapped[str] = mapped_column(sa.String(255))
    pending_secret_enc: Mapped[str | None] = mapped_column(sa.String(255))
    confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_used_step: Mapped[int | None] = mapped_column(sa.BigInteger)
    last_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    fail_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TwoFactorRecoveryCode(UUIDPk, Base):
    """Одноразовый резервный код второго фактора: хранится только HMAC-хеш, после использования — ``used_at``."""

    __tablename__ = "user_two_factor_recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(sa.String(128))
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Consent(UUIDPk, Base):
    """Согласие на обработку / публикацию данных профиля (версия документа фиксируется)."""

    __tablename__ = "consents"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ConsentKind] = mapped_column(str_enum(ConsentKind, "consent_kind"))
    document_version: Mapped[str] = mapped_column(sa.String(32))
    granted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
