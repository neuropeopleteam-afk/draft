"""ATS: настройки компании (Хантфлоу, вебхук), подключения Talantix и «Поток», журнал передач кандидатов,
связи «кандидат платформы → кандидат в ATS» (идемпотентность), записи тестовых ATS-заглушек."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow

# Адресаты передачи: ATS-провайдеры (общий интерфейс providers/) и универсальный вебхук
PROVIDERS = ("huntflow", "talantix", "potok")
TARGETS = (*PROVIDERS, "webhook")
TARGETS_SQL = ", ".join(f"'{t}'" for t in TARGETS)


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
    huntflow_token_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Универсальный вебхук: POST JSON, подпись HMAC-SHA256 в заголовке X-Draft-Signature
    webhook_enabled: Mapped[bool] = mapped_column(default=False)
    webhook_url: Mapped[str | None] = mapped_column(sa.String(500))
    webhook_secret_enc: Mapped[str | None] = mapped_column(sa.Text)  # Fernet
    webhook_secret_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Тестовая ATS-заглушка (демо): ключ входящего ящика, по нему заглушка относит записи к компании
    stub_key: Mapped[str | None] = mapped_column(sa.String(64), unique=True)


class AtsDelivery(UUIDPk, Timestamps, Base):
    __tablename__ = "ats_deliveries"
    __table_args__ = (
        sa.CheckConstraint(f"target IN ({TARGETS_SQL})", name="target"),
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
    # huntflow_applicant | huntflow_vacancy | webhook | talantix_person | talantix_response | talantix_comment |
    # talantix_transfer | talantix_token | potok_applicant | potok_join | potok_event
    kind: Mapped[str] = mapped_column(sa.String(32))
    external_id: Mapped[int | None]
    payload: Mapped[dict] = mapped_column(default=dict)
    signature_valid: Mapped[bool | None]
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class AtsConnection(Timestamps, Base):
    """Подключение компании к ATS-провайдеру (Talantix, «Поток»): режим, токены (Fernet), выбранная вакансия.

    ``mode = demo`` — наша заглушка, имитирующая API провайдера (жюри видит сценарий без реальных токенов);
    ``mode = real`` — настоящий API (api.talantix.ru, app.potok.io) с токенами владельца аккаунта.
    """

    __tablename__ = "ats_connections"
    __table_args__ = (sa.CheckConstraint("provider IN ('talantix', 'potok')", name="provider"),
                      sa.CheckConstraint("mode IN ('demo', 'real')", name="mode"))

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(sa.String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    mode: Mapped[str] = mapped_column(sa.String(8), default="real")
    base_url: Mapped[str | None] = mapped_column(sa.String(255))
    # JSON {access_token, refresh_token} (Talantix) или {token} («Поток») — зашифровано целиком
    secrets_enc: Mapped[str | None] = mapped_column(sa.Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    token_refreshed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Вакансия в ATS по умолчанию (для приглашений) и этап (необязательно)
    vacancy_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    vacancy_title: Mapped[str | None] = mapped_column(sa.String(255))
    stage_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    stage_title: Mapped[str | None] = mapped_column(sa.String(255))
    # Сопоставление вакансий платформы с вакансиями ATS: {platform_vacancy_id: {"id": 123, "title": "…"}}
    vacancy_map: Mapped[dict] = mapped_column(default=dict)
    # Источник кандидата «Драфт» в справочнике ATS (Talantix personSources) — находим или создаём один раз
    source_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    last_check_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_check_ok: Mapped[bool | None]
    last_check_info: Mapped[dict] = mapped_column(default=dict)
    # Обратный канал: последний опрос этапов кандидатов в ATS (раз в ATS_STAGE_POLL_S; воркер берёт строку CAS-ом)
    stages_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    stages_sync_info: Mapped[dict] = mapped_column(default=dict)


class AtsLink(UUIDPk, Timestamps, Base):
    """Кандидат платформы ↔ кандидат в ATS компании. Повторная передача не создаёт дубликат: берётся external_id.

    ``lock_until`` — короткая блокировка на время передачи (два воркера uvicorn, двойной клик, авто + вручную).
    """

    __tablename__ = "ats_links"
    __table_args__ = (sa.UniqueConstraint("company_id", "provider", "candidate_user_id",
                                          name="uq_ats_links_company_provider_candidate"),)

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(sa.String(16))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    external_id: Mapped[str | None] = mapped_column(sa.String(64))
    # Вакансии ATS, на которые кандидат уже добавлен: [{"id": 123, "join_id": 456}]
    vacancies: Mapped[list] = mapped_column(default=list)
    lock_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AtsStageEvent(UUIDPk, Base):
    """Журнал обратного канала: этап кандидата в ATS изменился → что поменялось на платформе. Без ПДн."""

    __tablename__ = "ats_stage_events"
    __table_args__ = (
        sa.CheckConstraint("status IN ('ok', 'error')", name="status"),
        sa.Index("ix_ats_stage_events_company_created", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(sa.String(16))
    candidate_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("invitations.id", ondelete="SET NULL"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("vacancy_applications.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(sa.String(64))  # id кандидата в ATS
    job_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    join_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    stage_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    stage_name: Mapped[str | None] = mapped_column(sa.String(255))
    stage_type: Mapped[str | None] = mapped_column(sa.String(64))
    active: Mapped[bool | None]
    stage: Mapped[str | None] = mapped_column(sa.String(16))  # этап на платформе: stages.PLATFORM_STAGES
    prev_stage: Mapped[str | None] = mapped_column(sa.String(16))
    effect: Mapped[str | None] = mapped_column(sa.String(255))  # что изменилось на платформе
    status: Mapped[str] = mapped_column(sa.String(8), default="ok")
    error: Mapped[str | None] = mapped_column(sa.String(500))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
