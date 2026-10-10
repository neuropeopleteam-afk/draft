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
    study_enabled: bool = True  # обезличенная статистика прохождения (app.modules.study); False — не собирается и не показывается
    # Разрешить демо-учёткам (users.is_demo, вход жюри в один клик) включать «демо-режим жюри» в кабинете.
    jury_mode_available: bool = True

    database_url: str = "postgresql+psycopg://fsp:fsp@db:5432/fsp"
    # Пул соединений с БД на ОДИН воркер uvicorn. 10.10 под нагрузкой 100 пользователей (docs/LOAD.md, раздел 6) пул
    # 5 + 10 при 40 потоках FastAPI на воркер исчерпывался: запросы ждали соединение 30 с и падали 500. Бюджет:
    # API_WORKERS × (DB_POOL_SIZE + DB_MAX_OVERFLOW) ≤ max_connections PostgreSQL (50 в docker-compose.yml) − Keycloak
    # (KC_DB_POOL_MAX_SIZE=6) − 3 (резерв суперпользователя) − ≈ 5 (миграции, резервная копия, консоль):
    # 2 × (8 + 10) = 36 ≤ 36. Больше воркеров — меньше пул на воркер или выше max_connections (docs/LOAD.md, раздел 8).
    db_pool_size: int = 8
    db_max_overflow: int = 10
    # Ожидание свободного соединения; дольше — 503 db_busy с Retry-After (фронтенд повторяет GET), а не 500 через 30 с
    db_pool_timeout_s: float = 10.0
    db_busy_retry_after_s: int = 3
    # Готовый ответ /api/validation/report на воркер, секунд (validation/router.py); 0 — считать на каждый запрос
    validation_report_ttl_s: float = 20.0

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 12 * 60
    jwt_issuer: str = "spectrek-fsp"

    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    email_code_resend_seconds: int = 60

    # Второй фактор входа (TOTP, RFC 6238; app/modules/auth/twofa.py). Обязателен для перечисленных ролей с реальной
    # учётной записью (не демо-песочница жюри, не вход эксперта по ссылке); остальным — по желанию.
    twofa_required_roles: str = "admin,fsp_analyst"
    # Имя издателя в приложении-аутентификаторе; пусто — product_name
    twofa_issuer: str | None = None
    # Ключ шифрования секретов TOTP в БД; пусто — производный от JWT_SECRET
    twofa_secret_key: str | None = None
    twofa_max_fails: int = 5  # неверных кодов подряд до блокировки
    twofa_lock_minutes: int = 15
    twofa_pending_ttl_minutes: int = 5  # пароль принят, ждём код
    twofa_setup_ttl_minutes: int = 15  # обязательное подключение при первом входе
    twofa_window_steps: int = 1  # допуск рассинхронизации часов: ±1 шаг по 30 с
    twofa_recovery_codes: int = 10

    @property
    def twofa_required_role_set(self) -> set[str]:
        return {r.strip() for r in self.twofa_required_roles.split(",") if r.strip()}

    # Бизнес-правила из брифа
    grade_change_interval_days: int = 90
    # Неподтверждённый тест на грейд G: повтор на G (и выше) — не раньше чем через N дней; на грейд ниже — сразу,
    # без зачёта попыток (видео организаторов №7, №20). Демо-режим жюри снимает ограничение.
    retake_same_grade_days: int = 30
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
    # Запасной провайдер — Yandex AI Studio (YandexGPT): заголовки «Authorization: Api-Key …» и «OpenAI-Project».
    # Основная модель — Claude Sonnet 5.5 через OpenRouter (LLM_CHAIN, разрешено организаторами); данные хранятся
    # на сервере в Москве, в модель уходит только обезличенный текст (docs/LLM.md).
    llm_provider: str = Field(default="openai_compatible", description="openai_compatible | yandex_ai_studio")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_folder_id: str | None = None
    llm_model: str | None = None
    llm_timeout_s: float = 25.0
    llm_disabled: bool = False
    # Цепочка провайдеров (docs/LLM.md): порядок через запятую, например «openrouter,yandex»; пусто — один
    # провайдер из LLM_* (поведение прежнее). yandex — провайдер из LLM_* (Yandex AI Studio или иной совместимый),
    # openrouter — OpenRouter (ключ на сервере, /opt/spectrek_fsp/secrets/openrouter.env). Последний рубеж — правила.
    llm_chain: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Ретранслятор вне РФ (с сервера в РФ OpenRouter отвечает 403): если задан, запросы OpenRouter идут на него
    # с заголовком X-Relay-Token, Authorization с ключом OpenRouter передаётся как есть
    llm_relay_url: str | None = None
    llm_relay_token: str | None = None
    # Собственный сертификат ретранслятора (самоподписанный, IP в SAN): путь к PEM — проверка TLS по нему, а не по certifi
    llm_relay_ca_file: str | None = None
    # То же содержимым (PEM в base64) — удобно для env_file в docker compose без монтирования файла
    llm_relay_ca_pem_b64: str | None = None
    # Открытая модель на этой машине (docs/LLM.md, раздел 9; профиль docker compose llm-local — llama.cpp server на CPU):
    # провайдер local — любой OpenAI-совместимый сервер (llama.cpp, Ollama, vLLM). Включается только через LLM_CHAIN
    # («local» или «openrouter,local»); без него поведение прежнее. Ключ нужен, только если сервер его требует.
    llm_local_base_url: str | None = None
    llm_local_model: str | None = None
    llm_local_api_key: str | None = None
    # Тайм-аут попытки local, с (CPU медленнее облака); пусто — как у функции. Общий бюджет оценки и дедлайн — те же
    llm_local_timeout_s: float | None = None
    # response_format = json_object при want_json (у llama.cpp — грамматика: ответ всегда разбираемый JSON)
    llm_local_json_mode: bool = True
    # chat_template_kwargs.enable_thinking = false: Qwen3.x по умолчанию рассуждает, на CPU это минуты
    llm_local_no_think: bool = True
    # Доп. поля тела запроса (JSON-объект) — например, для сравнения тех же весов через облачный совместимый API
    llm_local_extra_body: str | None = None
    # Модель на функцию: «модель» (для первого провайдера цепочки) или «провайдер=модель,провайдер=модель»;
    # пусто — по умолчанию (openrouter: Sonnet 5.5, вторая оценка — Fable 5.1; yandex: LLM_MODEL / LLM_GRADING_MODEL)
    llm_model_parse_need: str | None = None
    llm_model_resume: str | None = None
    llm_model_grade: str | None = None
    llm_model_grade_second: str | None = None
    # Тайм-аут одной попытки на функцию, с; пусто — LLM_TIMEOUT_S (разбор, резюме) и LLM_GRADING_TIMEOUT_S (оценка)
    llm_timeout_parse_need: float | None = None
    llm_timeout_resume: float | None = None
    llm_timeout_grade: float | None = None
    llm_timeout_grade_second: float | None = None
    # Рассуждения моделей OpenRouter на функцию (у Sonnet 5.5 их нельзя выключить): low | medium | high | default
    # (параметр не передаётся). Разбор и резюме — low: извлечению рассуждения не нужны, а ответ в 2 раза дешевле и
    # не обрезается лимитом токенов (docs/LLM.md, «качество / время»)
    llm_reasoning_parse_need: str = "low"
    llm_reasoning_resume: str = "low"
    llm_reasoning_grade: str = "default"
    llm_reasoning_grade_second: str = "low"  # Fable 5.1 по умолчанию рассуждает долго: ответ обрезался лимитом
    # Автомат-выключатель: после N ошибок подряд провайдер (с этой моделью) пропускается M секунд
    llm_breaker_failures: int = 3
    llm_breaker_cooldown_s: float = 60.0
    # Вторая оценка спорных ответов (grade_second, docs/LLM.md): «близко к порогу» — |балл − 0,5| ≤ LLM_GRADING_NEAR
    llm_grading_near: float = 0.05
    # Модель для оценки открытых ответов теста по рубрике (короткое имя или gpt://…); пусто — LLM_MODEL.
    # Окончательный выбор — по согласию с экспертами на проверочном наборе (docs/ARCHITECTURE.md, раздел 8).
    llm_grading_model: str | None = None
    llm_grading_timeout_s: float = 40.0
    # Вторая оценка при сомнении (grader.doubts): расхождение двух оценок больше порога — ответ эксперту
    llm_grading_second_opinion: bool = True
    llm_grading_disagree: float = 0.25
    # Чья экспертная разметка пакета (раздел «Экспертная разметка» /validation): human | model | auto (по профилям).
    # model — критерий допуска модели-оценщика абсолютный (κ с консенсусом и MAE), а не разрыв с межэкспертной κ.
    expert_panel_kind: str = "auto"
    # Общий бюджет оценки одного ответа (первая + вторая оценка, с переходами по цепочке), с: ответ кандидата ждёт
    # оценку синхронно, а proxy_read_timeout nginx — 60 с. Не хватило на вторую оценку — ответ «на проверке»
    llm_grading_budget_s: float = 50.0
    # И27: вторая оценка спорных ответов — в фоне (итог теста её не ждёт, результат дописывается в оценку с пометкой
    # «пересмотрено второй моделью»); false — как раньше, синхронно внутри ответа кандидата
    llm_grading_second_async: bool = True
    # И27: кэш разбора потребности по нормализованному тексту (таблица need_parse_jobs), с; 0 — без кэша
    parse_cache_ttl_s: int = 3600

    # Движок тестирования: bank — пакет assessment_bank (адаптивный тест); stub — заглушка из 6 вопросов.
    assessment_engine: str = "bank"
    # Невидимая «ИИ-метка» в тексте развёрнутых заданий (assessment/ai_mark.py) — сигнал достоверности
    assessment_ai_mark: bool = True
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
    # Я22: порог уверенности решения по грейду — подтверждение заявленного грейда и «принять уровень ниже»:
    # P(θ ≥ порога) ≥ значения. 0,6 — по перебору на симуляции всего пути (docs/validation/GRADE_ACCURACY.md): точно
    # истинный уровень 64 % против 57 % при 0,8, завышение 6,5 % (≤ 7 %), κw повтора 0,874 против 0,844, время то же.
    # 0,8 — прежнее правило (до 10.10)
    assessment_confirm_level: float = 0.6
    # Я22: позиция внутри уровня (нижняя / середина / верхняя часть) в результате кандидата и в карточке работодателя —
    # только когда погрешность позволяет, иначе «точнее — после дотестирования»; без чисел θ (grades.level_position).
    # false — как раньше (поля нет)
    grade_position_enabled: bool = False
    # Камера во время теста по согласию (app/modules/proctor): false — экран камеры не показывается вообще,
    # тест идёт без камеры. Камера и так необязательна: без неё тест доступен полностью, грейд не меняется
    proctor_camera_enabled: bool = True
    # Демо-учётки жюри: вход в один клик, сброс своей песочницы (не чаще раза в N секунд)
    jury_reset_cooldown_s: int = 20
    # Демо-режим жюри снимает правило 90 дней; чтобы перезапусками нельзя было выкачать банк заданий —
    # не больше N новых сессий теста за 24 часа на демо-учётку (счётчик по почте, переживает сброс жюри).
    # 30: жюри само проходит и повторяет тест (полный и экспресс), 5 было мало
    jury_max_test_starts_per_day: int = 30
    # Экспресс-тест для жюри (только демо-режим): 5–7 коротких автопроверяемых заданий без канареек и дотестирования,
    # ≈ 5 минут; интервал θ шире — об этом сказано в результате
    assessment_express_min_items: int = 5
    assessment_express_max_items: int = 7
    assessment_express_item_time_s: int = 240
    assessment_express_max_minutes: int = 20
    # За Senior экспресс длиннее (консилиум 07.10, решение 5): 7 заданий с лимитом 240 с не подтверждают Senior даже при
    # всех верных (потолок θ̂ ≈ 1,4 при SE 0,7), а лимит 240 с отсекает трудные задания. 8–12 заданий с лимитом 360 с —
    # «всё верно» даёт Senior, правило P ≥ 0,8 то же. Лимит сессии 45 мин — верхняя граница по рекомендуемому времени
    # заданий (жюри при темпе 30–60 с отвечает за 8–12 мин); при 30 мин движок не успевал выдать 12 заданий
    assessment_express_senior_min_items: int = 8
    assessment_express_senior_max_items: int = 12
    assessment_express_senior_item_time_s: int = 360
    assessment_express_senior_max_minutes: int = 45
    # Песочницы жюри (свой набор персон у каждого эксперта): сверх лимита удаляются самые давние.
    # 60 — с запасом на жюри целиком и повторные входы с других устройств (песочница ≈ 5 учёток, ≈ 0,1 МБ в БД).
    jury_sandboxes_max: int = 60
    # Новые песочницы в час: с одного адреса (жюри может сидеть за одним NAT) и всего. С адреса — счётчик в памяти
    # воркера (каждый воркер пропускает не меньше лимита — эксперты за общим NAT не упрутся раньше); всего — по БД,
    # точно для всех воркеров. Создание песочницы — 2–9 с CPU, поэтому общий предел нужен.
    jury_new_sandboxes_per_ip_hour: int = 40
    jury_new_sandboxes_total_hour: int = 120
    # Запас готовых песочниц (создаются в фоне): первый вход эксперта — мгновенно, а не ~4 с создания
    jury_spare_sandboxes: int = 1
    # Задания работодателя (И7): лента «Задания для вас» — предложение раз в N дней; фоновый обход раз в M секунд
    # (0 — выключен, тогда только лениво при обращении кандидата и из консоли python -m app.modules.assignments.feed)
    # К5: по умолчанию раз в неделю (7), не больше assignments_feed_monthly_limit предложений за 30 дней, напоминание
    # кандидату через assignments_remind_days дней (до двух раз), предложение без ответа истекает через
    # assignments_offer_ttl_days; работодателю — напоминание об оценке по рубрике через assignments_review_remind_days
    assignments_feed_days: int = 7
    assignments_feed_interval_s: int = 3600
    assignments_feed_monthly_limit: int = 4
    assignments_remind_days: int = 2
    assignments_offer_ttl_days: int = 14
    assignments_review_remind_days: int = 3
    # Живая демонстрация (QR → мини-тест на телефоне → автоприглашение, app/jury_live): пауза перед появлением в
    # подборке и перед приглашением (с; в тестах 0) и лимиты мини-тестов (гостей) в час — с адреса, на зал, всего
    jury_live_select_delay_s: float = 1.5
    jury_live_invite_delay_s: float = 4.0
    jury_live_guests_per_ip_hour: int = 20
    jury_live_guests_per_room_hour: int = 60
    jury_live_guests_total_hour: int = 200
    # Релевантность дисциплины ФСП специализации (И23, ответ организаторов E08): мягкий коэффициент 1,0 / 0,9 / 0,8
    # к вкладу результата в силу паспорта (app/modules/fsp/relevance.py). По умолчанию выключено — порядок выдачи
    # match-v1 не меняется; включать только без падения метрик make bench / ranking_guard (цифры — внутренний отчёт разработки)
    fsp_discipline_relevance: bool = False

    # Подписка на потребность и напоминания (И25, Н6; app/modules/subs): фоновый обход раз в N секунд (0 — выключен:
    # тесты и консольный запуск python -m app.modules.subs.runner). Топ-N подписки, не чаще одного пересчёта в
    # subs_min_recompute_s секунд, страховочный полный пересчёт раз в subs_full_refresh_h часов, «новый» живёт
    # subs_new_ttl_days дней. Тихие часы (по Москве, UTC+3) — только для живых пользователей: push и письма ждут утра.
    subs_tick_interval_s: int = 300
    subs_top_n: int = 10
    subs_min_recompute_s: int = 60
    subs_full_refresh_h: int = 24
    subs_new_ttl_days: int = 14
    subs_quiet_from: int = 22
    subs_quiet_to: int = 8
    subs_digest_hour: int = 9
    subs_tz_offset_h: int = 3
    reminder_invite_days: int = 3
    reminder_expiry_hours: int = 24
    reminder_application_days: int = 5

    # Резюме: максимальный размер PDF, разбор — в отдельном процессе с тайм-аутом и лимитом памяти
    resume_max_bytes: int = 5 * 1024 * 1024
    resume_max_pages: int = 20
    resume_parse_timeout_s: float = 10.0
    resume_parse_memory_mb: int = 256  # адресное пространство процесса разбора; обычному PDF хватает ~100 МБ
    resume_uploads_per_hour: int = 5

    # Подписанный паспорт грейда (app/passport): ключ Ed25519 — только из secrets/passport.env на сервере
    # (генератор tools/passport/genkey.py); пусто — эфемерный «тестовый ключ» процесса. Срок действия — от даты теста.
    passport_signing_key: str | None = None
    passport_retired_public_keys: str = ""  # открытые ключи выведенных из оборота ключей (base64url через запятую)
    passport_ttl_days: int = 365

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
        """Хотя бы один провайдер цепочки настроен и LLM не выключен."""
        if self.llm_disabled:
            return False
        return any(self.llm_provider_configured(p) for p in self.llm_chain_list)

    @property
    def llm_chain_list(self) -> list[str]:
        items = [p.strip().lower() for p in (self.llm_chain or "").split(",") if p.strip()]
        return list(dict.fromkeys(items)) or ["yandex"]

    def llm_provider_configured(self, name: str) -> bool:
        if name == "yandex":
            return bool(self.llm_base_url and self.llm_api_key and self.llm_model)
        if name == "openrouter":
            return bool(self.openrouter_api_key and (self.llm_relay_url or self.openrouter_base_url))
        if name == "local":
            return bool(self.llm_local_base_url and self.llm_local_model)
        return False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
