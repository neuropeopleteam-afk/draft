"""Настройки приложения. Все значения берутся из переменных окружения (см. .env.example).

Секреты (JWT_SECRET, пароль БД, ключ OpenRouter) в репозиторий не попадают.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Спецтрек ФСП — платформа подбора ИТ-специалистов"
    app_version: str = "0.1.0"
    env: str = Field(default="dev", description="dev | test | prod")

    # Режим разработки: код подтверждения почты пишется в лог и возвращается в ответе API.
    # Не задан (None) — включается автоматически, пока не настроены ключи Postbox.
    dev_mode: bool | None = None
    # «Песочница жюри»: снимает ограничение частоты смены грейда (90 дней) и т. п.
    demo_sandbox: bool = False

    database_url: str = "postgresql+psycopg://fsp:fsp@db:5432/fsp"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 12 * 60
    jwt_issuer: str = "spectrek-fsp"

    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    email_code_resend_seconds: int = 60

    # Бизнес-правила из брифа
    grade_change_interval_days: int = 90
    invitation_cooldown_days: int = 30
    probe_time_limit_s: int = 15 * 60

    mail_backend: str = Field(default="auto", description="auto | dev | postbox")
    mail_from: str = "noreply@neuropeople.pro"
    # Yandex Cloud Postbox (SESv2-совместимый HTTPS API). Ключи — только из env_file на сервере.
    postbox_access_key_id: str | None = None
    postbox_secret_access_key: str | None = None
    postbox_endpoint: str = "https://postbox.cloud.yandex.net"
    postbox_region: str = "ru-central1"
    public_base_url: str = "http://localhost:8080"

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Внешние сервисы (только из окружения)
    openrouter_api_key: str | None = None

    # Будущая интеграция с ФСП ID (Keycloak, OIDC)
    fsp_oidc_issuer: str | None = None
    fsp_oidc_client_id: str | None = None

    @property
    def postbox_configured(self) -> bool:
        return bool(self.postbox_access_key_id and self.postbox_secret_access_key)

    @property
    def effective_mail_backend(self) -> str:
        if self.mail_backend == "auto":
            return "postbox" if self.postbox_configured else "dev"
        return self.mail_backend

    @property
    def effective_dev_mode(self) -> bool:
        return self.dev_mode if self.dev_mode is not None else not self.postbox_configured

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
