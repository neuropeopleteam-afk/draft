"""Настройки приложения. Все значения берутся из переменных окружения (см. .env.example).

Секреты (JWT_SECRET, пароль БД, ключи LLM и Postbox) в репозиторий не попадают.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Рабочее название продукта — единственное место, где оно задано (фронтенд берёт его из /api/meta).
    product_name: str = "Встречный"
    app_name: str = "Спецтрек ФСП — платформа подбора ИТ-специалистов"
    app_version: str = "0.2.0"
    env: str = Field(default="dev", description="dev | test | prod")

    # Режим разработки: код подтверждения почты пишется в лог и возвращается в ответе API.
    # Не задан (None) — включается автоматически, пока не настроены ключи Postbox.
    dev_mode: bool | None = None
    # «Песочница жюри»: снимает ограничение частоты смены грейда (90 дней) для всех.
    demo_sandbox: bool = False
    # Разрешить кандидату самому включить «демо-режим жюри» в кабинете (на время конкурса — да).
    jury_mode_available: bool = True

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

    # LLM: любой OpenAI-совместимый провайдер. Значения — только из env-файла на сервере
    # (/opt/spectrek_fsp/secrets/llm.env). Без них все функции работают по правилам и словарям.
    # Выбран Yandex AI Studio (модели и данные в РФ): заголовки «Authorization: Api-Key …» и «OpenAI-Project».
    llm_provider: str = Field(default="openai_compatible", description="openai_compatible | yandex_ai_studio")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_folder_id: str | None = None
    llm_model: str | None = None
    llm_timeout_s: float = 25.0
    llm_disabled: bool = False

    # Движок тестирования: stub — временная заглушка; bank — пакет assessment_bank (подключается отдельно).
    assessment_engine: str = "stub"

    # Резюме: максимальный размер PDF
    resume_max_bytes: int = 5 * 1024 * 1024

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
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model and not self.llm_disabled)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
