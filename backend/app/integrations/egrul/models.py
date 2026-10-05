"""Кэш проверок работодателя по ЕГРЮЛ (egrul.nalog.ru): одна строка на ИНН, срок жизни 7 дней."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class RegistryCheck(UUIDPk, Base):
    __tablename__ = "company_registry_checks"
    __table_args__ = (
        sa.CheckConstraint("status IN ('found', 'not_found', 'captcha', 'error', 'invalid')", name="status"),
    )

    inn: Mapped[str] = mapped_column(sa.String(12), unique=True)
    # found — запись найдена; not_found — по ИНН ничего нет; captcha/error — сервис не ответил (мягкая деградация)
    status: Mapped[str] = mapped_column(sa.String(16))
    # Нормализованные сведения: name, short_name, ogrn, kpp, registered_at, liquidated_at, director, region, kind
    data: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(sa.String(255))
    source: Mapped[str] = mapped_column(sa.String(64), default="egrul.nalog.ru")
    checked_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    requested_by_company: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("companies.id", ondelete="SET NULL"))
