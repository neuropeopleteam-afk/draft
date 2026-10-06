"""Настройки интеграций (день 3Б). Отдельно от app.core.config, чтобы пакеты интеграций были независимыми.

Все секреты — только из окружения / env-файлов в /opt/spectrek_fsp/secrets (в репозиторий не попадают):
* VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY — Web Push (secrets/vapid.env);
* FSP_OIDC_CLIENT_SECRET, FSP_DEMO_PASSWORD — ФСП ID на Keycloak (secrets/keycloak.env);
* INTEGRATIONS_SECRET_KEY — шифрование токенов ATS в БД (если не задан — производный от JWT_SECRET).
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationSettings(BaseSettings):
    # пустые значения в .env — как незаданные (так же, как в app.core.config)
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    public_base_url: str = "http://localhost:8080"
    jwt_secret: str = "dev-only-change-me"
    integrations_secret_key: str | None = None

    # --- ФНС ЕГРЮЛ (egrul.nalog.ru) ---
    egrul_base_url: str = "https://egrul.nalog.ru"
    egrul_cache_days: int = 7
    egrul_timeout_s: float = 12.0
    egrul_disabled: bool = False

    # --- ФСП ID (Keycloak, OIDC Authorization Code + PKCE) ---
    # Публичный issuer (как его видит браузер и как он записан в токенах)
    fsp_oidc_issuer: str | None = None
    # Внутренний адрес Keycloak для обмена кода и JWKS (из контейнера api), например http://keycloak:8080/auth/realms/fsp
    fsp_oidc_internal_base: str | None = None
    fsp_oidc_client_id: str = "spectrek-platform"
    fsp_oidc_client_secret: str | None = None
    fsp_oidc_scopes: str = "openid email profile"  # claims fsp_* — мапперы клиента
    # Демо-учётки ФСП ID показываются на странице входа (только демо-realm, без реальных данных)
    fsp_demo_accounts: str = "fsp-champion,fsp-prizer,fsp-newcomer"
    fsp_demo_password: str | None = None

    # --- ATS ---
    huntflow_default_base_url: str = "https://api.huntflow.ru/v2"
    ats_timeout_s: float = 10.0
    ats_max_attempts: int = 3
    # Адрес тестовой ATS-заглушки (по умолчанию — наш публичный адрес, запросы идут по настоящему HTTP)
    ats_stub_base_url: str | None = None

    # --- Web Push ---
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = Field(default="mailto:noreply@neuropeople.pro")
    push_disabled: bool = False

    @property
    def fsp_enabled(self) -> bool:
        return bool(self.fsp_oidc_issuer)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key and not self.push_disabled)

    @property
    def stub_base(self) -> str:
        return (self.ats_stub_base_url or self.public_base_url).rstrip("/")


@lru_cache
def get_isettings() -> IntegrationSettings:
    return IntegrationSettings()
