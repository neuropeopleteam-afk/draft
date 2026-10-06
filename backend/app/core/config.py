"""Настройки приложения. Все значения берутся из переменных окружения (см. .env.example).

Секреты (JWT_SECRET, пароль БД, ключи LLM и Postbox) в репозиторий не попадают.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: пустая переменная (DEV_MODE= в .env из .env.example) — как незаданная, берётся значение
    # по умолчанию; иначе `make env && make up` на чистой машине падал на разборе bool из пустой строки.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

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
    # Разрешить демо-учёткам (users.is_demo, вход жюри в один клик) включать «демо-режим жюри» в кабинете.
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
    # Модель для оценки открытых ответов теста по рубрике (короткое имя или gpt://…); пусто — LLM_MODEL.
    # Окончательный выбор — по согласию с экспертами на проверочном наборе (docs/ARCHITECTURE.md, раздел 8).
    llm_grading_model: str | None = None
    llm_grading_timeout_s: float = 40.0

    # Движок тестирования: bank — пакет assessment_bank (адаптивный тест); stub — заглушка из 6 вопросов.
    assessment_engine: str = "bank"
    # Параметры адаптивного теста. Длина: 8–16 оцениваемых заданий (+3 канарейки, +до 6 дотестирования),
    # не дольше 60 минут; open_book_3step — не больше 2, open_answer — не больше 1 (см. exposure.py)
    assessment_min_items: int = 8
    assessment_max_items: int = 16
    assessment_se_target: float = 0.35
    assessment_max_minutes: int = 60
    # Классификация по грейду: остановка, когда ни один порог грейда не попадает в θ̂ ± z·SE (classification;
    # z = 1,28 — 90 % с одной стороны, строже правила подтверждения 80 %, чтобы досрочная остановка не завышала грейд),
    # или только по SE (se); выбор заданий по информации в неопределённом пороге (cut) или в θ̂ (theta)
    assessment_stop_rule: str = "classification"
    assessment_classify_z: float = 1.28
    assessment_select_at: str = "cut"
    # Дотестирование у порога: ближайший порог внутри θ̂ ± z·SE → короткие задания (лимит ≤ 5 мин) по информации
    # в пороге, пока порог не выйдет из интервала; не больше N заданий и M минут сверх основной части
    assessment_extension_items: int = 6
    assessment_extension_minutes: int = 20
    # сначала свободные короткие задания своего субпула, затем остальной банк (ниже частота показа, ротация чище)
    assessment_extension_own_first: bool = True
    assessment_max_open_book: int = 2
    assessment_max_open_answer: int = 1
    # Ротация субпулов банка: 2 параллельные формы; повторная попытка получает другой субпул.
    # Утёкший субпул — в карантин: ASSESSMENT_SUBPOOL_QUARANTINE=0 (номера через запятую)
    assessment_subpools: int = 2
    assessment_subpool_quarantine: str = ""
    # Контроль частоты показа: sympson_hetter (K_f из assessment/exposure_k.json) | none
    assessment_exposure: str = "sympson_hetter"
    # Демо-учётки жюри: вход в один клик, сброс своей песочницы (не чаще раза в N секунд)
    jury_reset_cooldown_s: int = 20
    # Демо-режим жюри снимает правило 90 дней; чтобы перезапусками нельзя было выкачать банк заданий —
    # не больше N новых сессий теста за 24 часа на демо-учётку (счётчик по почте, переживает сброс жюри)
    jury_max_test_starts_per_day: int = 5
    # Песочницы жюри (свой набор персон у каждого эксперта): сверх лимита удаляются самые давние
    jury_sandboxes_max: int = 30
    # Запас готовых песочниц (создаются в фоне): первый вход эксперта — мгновенно, а не ~4 с создания
    jury_spare_sandboxes: int = 1

    # Резюме: максимальный размер PDF, разбор — в отдельном процессе с тайм-аутом и лимитом памяти
    resume_max_bytes: int = 5 * 1024 * 1024
    resume_max_pages: int = 20
    resume_parse_timeout_s: float = 10.0
    resume_parse_memory_mb: int = 256  # адресное пространство процесса разбора; обычному PDF хватает ~100 МБ
    resume_uploads_per_hour: int = 5

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
