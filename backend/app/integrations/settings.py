"""Настройки интеграций (день 3Б). Отдельно от app.core.config, чтобы пакеты интеграций были независимыми.

Все секреты — только из окружения / env-файлов в /opt/spectrek_fsp/secrets (в репозиторий не попадают):
* VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY — Web Push (secrets/vapid.env);
* FSP_OIDC_CLIENT_SECRET, FSP_DEMO_PASSWORD — ФСП ID на Keycloak (secrets/keycloak.env);
* INTEGRATIONS_SECRET_KEY — шифрование токенов ATS в БД (если не задан — производный от JWT_SECRET);
* TALANTIX_*, POTOK_*, HUNTFLOW_* — начальные токены ATS (secrets/ats.env), импорт в компанию командой
  ``python -m app.integrations.ats.cli import-env`` (после импорта токены живут в БД зашифрованными).
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
    fsp_oidc_discovery: bool = True
    fsp_oidc_claims_map: dict[str, str] = Field(default_factory=dict)
    fsp_oidc_token_auth_method: str = "client_secret_basic"  # basic | post | none
    fsp_id_demo: bool = True
    fsp_registry_mode: str = "claims"  # claims | mock | external
    fsp_registry_base_url: str | None = None  # …/api/fsp-registry/v1
    fsp_registry_token: str | None = None
    fsp_registry_timeout_s: float = 5.0
    # Демо-учётки ФСП ID показываются на странице входа (только демо-realm, без реальных данных)
    fsp_demo_accounts: str = "fsp-champion,fsp-prizer,fsp-newcomer"
    fsp_demo_password: str | None = None

    # --- ATS ---
    huntflow_default_base_url: str = "https://api.huntflow.ru/v2"
    ats_timeout_s: float = 10.0
    ats_max_attempts: int = 3
    # Куда api сам ходит к тестовой ATS-заглушке (по настоящему HTTP). Пусто — публичный адрес сайта; в docker-compose
    # по умолчанию http://127.0.0.1:8000 — сам api в контейнере (адрес сайта изнутри контейнера может быть недоступен)
    ats_stub_base_url: str | None = None
    # User-Agent для Talantix обязателен: компания и контакт для связи при проблемах
    ats_user_agent_company: str = "Vstrechny, FSP special track, fsp.neuropeople.pro"
    ats_user_agent_contact: str = "noreply@neuropeople.pro"
    talantix_base_url: str = "https://api.talantix.ru"
    potok_base_url: str = "https://app.potok.io/api/v3"
    # Начальные токены из secrets/ats.env (импорт командой python -m app.integrations.ats.cli import-env)
    talantix_tokens_json: str | None = None
    talantix_access_token: str | None = None
    talantix_refresh_token: str | None = None
    talantix_vacancy_id: int | None = None
    potok_token: str | None = None
    potok_vacancy_id: int | None = None
    huntflow_token: str | None = None
    huntflow_account_id: int | None = None
    huntflow_vacancy_id: int | None = None
    huntflow_base_url: str | None = None

    # --- Web Push ---
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = Field(default="mailto:noreply@neuropeople.pro")
    push_disabled: bool = False

    @property
    def fsp_enabled(self) -> bool:
        return bool(self.fsp_oidc_issuer and self.fsp_oidc_client_id)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key and not self.push_disabled)

    @property
    def stub_base(self) -> str:
        """Адрес заглушек для вызовов изнутри api (clients.check_url переписывает на него публичный)."""
        return (self.ats_stub_base_url or self.public_base_url).rstrip("/")

    @property
    def stub_public_base(self) -> str:
        """Адрес заглушек в настройках компании и в интерфейсе — публичный адрес сайта
        (не зависит от ATS_STUB_BASE_URL)."""
        return self.public_base_url.rstrip("/")


@lru_cache
def get_isettings() -> IntegrationSettings:
    return IntegrationSettings()
