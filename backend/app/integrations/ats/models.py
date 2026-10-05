"""ATS: настройки компании (Хантфлоу, вебхук), журнал передач кандидатов, записи тестовой ATS-заглушки."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow


class AtsSettings(Timestamps, Base):
    __tablename__ = "ats_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    # Передавать кандидата автоматически при принятии приглашения
    auto_push: Mapped[bool] = mapped_column(default=True)
    # Хантфлоу (публичный API v2): токен и id вакансии задаёт работодатель
    huntflow_enabled: Mapped[bool] = mapped_column(default=False)
    huntflow_base_url: Mapped[str | None] = mapped_column(sa.String(255))
    huntflow_account_id: Mapped[int | None]
    huntflow_vacancy_id: Mapped[int | None]
    huntflow_status_id: Mapped[int | None]
    huntflow_token_enc: Mapped[str | None] = mapped_column(sa.Text)  # Fernet
    # Универсальный вебхук: POST JSON, подпись HMAC-SHA256 в заголовке X-Vstrechny-Signature
    webhook_enabled: Mapped[bool] = mapped_column(default=False)
    webhook_url: Mapped[str | None] = mapped_column(sa.String(500))
    webhook_secret_enc: Mapped[str | None] = mapped_column(sa.Text)  # Fernet
    # Тестовая ATS-заглушка (демо): ключ входящего ящика, по нему заглушка относит записи к компании
    stub_key: Mapped[str | None] = mapped_column(sa.String(64), unique=True)


class AtsDelivery(UUIDPk, Timestamps, Base):
    __tablename__ = "ats_deliveries"
    __table_args__ = (
        sa.CheckConstraint("target IN ('huntflow', 'webhook')", name="target"),
        sa.CheckConstraint("status IN ('pending', 'ok', 'error')", name="status"),
        sa.Index("ix_ats_deliveries_company_created", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("invitations.id", ondelete="SET NULL"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("vacancy_applications.id", ondelete="SET NULL"))
    target: Mapped[str] = mapped_column(sa.String(16))
    status: Mapped[str] = mapped_column(sa.String(16), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    http_status: Mapped[int | None]
    # Что получилось на стороне ATS: id кандидата, id записи на вакансии; без ПДн
    result: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(sa.String(500))
    trigger: Mapped[str] = mapped_column(sa.String(32), default="invitation_accepted")


class AtsStubRecord(UUIDPk, Base):
    """Что «пришло» в тестовую ATS: кандидаты Хантфлоу-совместимого API и вебхуки (с проверкой подписи)."""

    __tablename__ = "ats_stub_records"
    __table_args__ = (sa.Index("ix_ats_stub_records_key_created", "stub_key", "created_at"),)

    stub_key: Mapped[str] = mapped_column(sa.String(64))
    kind: Mapped[str] = mapped_column(sa.String(32))  # huntflow_applicant | huntflow_vacancy | webhook
    external_id: Mapped[int | None]
    payload: Mapped[dict] = mapped_column(default=dict)
    signature_valid: Mapped[bool | None]
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
