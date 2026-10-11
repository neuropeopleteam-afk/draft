"""Модели ответов для OpenAPI (Я3), часть «интеграции»: ATS (Хантфлоу, Talantix, «Поток»), тестовые ATS-заглушки, проверка
компании по реестру, паспорт навыков, ФСП ID, push-уведомления, опрос удобства SUS, выгрузки в ATS.

ТОЛЬКО ДОКУМЕНТАЦИЯ: в декораторах нет `response_model`, поведение API не меняется (см. app/core/api_models.py). Формы взяты из
кода (integrations/ats/router.py `provider_out`, `settings_out`, service.py `delivery_out`; egrul/trust; passport/service.py
`public_view`, `evaluate`) и сверены с реальными ответами (tests/test_openapi_models.py). Токены и секреты в ответах
всегда маскированы (`token_masked`: «ab…yz»), целиком отдаётся только секрет подписи вебхука его владельцу.
Заглушки ATS повторяют форматы чужих API (Хантфлоу, Talantix, «Поток»): поля ответов — как у этих систем, а не как у платформы.
Таблица подключения — `TYPES` в конце файла.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.api_models_base import Doc, Obj

# ---------------------------------------------------------------- ATS работодателя


class AtsProviderOut(Doc):
    """Подключение ATS: режим (демо или настоящая), маска токена, вакансия и этап для передачи, итог последней проверки."""

    code: str = Field(description="huntflow, talantix или potok")
    title: str
    docs_url: str = Field(description="Документация API этой ATS")
    real_base_url: str = Field(description="Официальный адрес API")
    demo_base_url: str = Field(description="Адрес встроенной заглушки (демо-режим)")
    candidates_linked: int = Field(description="Сколько кандидатов уже связано с записями в ATS (повторная передача не создаёт дубль)")
    enabled: bool
    mode: str = Field(description="demo — встроенная заглушка, real — настоящая ATS")
    base_url: str = Field(description="Адрес API, который используется сейчас")
    custom_base_url: str | None = Field(default=None, description="Свой адрес API, если задан (иначе официальный)")
    token_set: bool
    token_masked: str = Field(description="Маска токена; сам токен не отдаётся")
    refresh_set: bool | None = Field(default=None, description="Talantix: сохранён ли refresh-токен")
    token_expires_at: str | None = Field(default=None)
    refresh_expires_at: str | None = Field(default=None)
    token_refreshed_at: str | None = Field(default=None)
    account_id: int | None = Field(default=None, description="Хантфлоу: идентификатор организации")
    vacancy_id: int | None = Field(description="Вакансия в ATS по умолчанию")
    vacancy_title: str | None
    stage_id: int | None = Field(description="Этап (статус) подбора в ATS по умолчанию")
    stage_title: str | None
    vacancy_map: Obj = Field(description="Вакансия платформы (uuid) → вакансия и этап в ATS")
    source_id: int | None = Field(default=None, description="Talantix: идентификатор источника «Встречный (ФСП)»")
    last_check_at: str | None
    last_check_ok: bool | None
    last_check_info: Obj = Field(description="Итог последней проверки: account, vacancies_active, details, token_refreshed либо error")


class AtsHuntflowSettingsOut(Doc):
    enabled: bool
    base_url: str
    account_id: int | None
    vacancy_id: int | None
    status_id: int | None
    token_set: bool
    token_masked: str


class AtsWebhookSettingsOut(Doc):
    enabled: bool
    url: str | None
    secret_set: bool
    secret_masked: str
    signature_header: str = Field(description="Заголовок с подписью тела запроса (HMAC-SHA256)")


class AtsStubSettingsOut(Doc):
    connected: bool
    huntflow_base_url: str
    webhook_url: str


class AtsSettingsOut(Doc):
    """Настройки передачи кандидатов: Хантфлоу, вебхук, тестовая заглушка."""

    auto_push: bool = Field(description="Передавать кандидата автоматически, когда приглашение принято")
    huntflow: AtsHuntflowSettingsOut
    webhook: AtsWebhookSettingsOut
    stub: AtsStubSettingsOut


class AtsCheckOut(Doc):
    """Итог проверки связи с ATS."""

    ok: bool
    account: str | None = Field(description="Владелец токена или организация")
    details: list[str] = Field(description="Что проверено, по строкам")
    me: Obj | None = Field(default=None, description="Хантфлоу: id и имя владельца токена")
    accounts: list[Obj] | None = Field(default=None, description="Хантфлоу: организации (id, name)")
    statuses: list[Obj] | None = Field(default=None, description="Хантфлоу: этапы подбора (id, name, order)")
    account_id: int | None = Field(default=None, description="Talantix: идентификатор владельца")
    vacancies_active: int | None = Field(default=None, description="Talantix и «Поток»: число активных вакансий")
    token_refreshed: bool | None = Field(default=None, description="Talantix: токен обновлён в ходе проверки")
    token_expires_at: str | None = Field(default=None)


class AtsVacancyOut(Doc):
    id: int
    title: str | None
    status: str | None
    department: str | None = Field(default=None)
    url: str | None = Field(default=None)
    salary: Obj | None = Field(default=None, description="Вилка в ATS: from, to, currency")
    stages: list[Obj] | None = Field(default=None, description="Этапы вакансии (id, title) — «Поток»")


class AtsStageOut(Doc):
    id: int
    title: str | None = Field(default=None)
    name: str | None = Field(default=None, description="Название этапа (Talantix отдаёт name и position)")
    position: int | None = Field(default=None)


class AtsDeliveryOut(Doc):
    """Запись журнала передач кандидата в ATS."""

    id: str
    target: str = Field(description="huntflow, talantix, potok или webhook")
    target_title: str
    status: str = Field(description="sent, failed, pending, …")
    attempts: int
    http_status: int | None
    result: Obj = Field(description="Что сделано в ATS: шаги, идентификаторы, способ защиты от дубля")
    error: str | None
    trigger: str = Field(description="auto — автоматически, manual — вручную, retry — повтор")
    candidate_ref: str | None
    position_title: str | None
    invitation_id: str | None
    application_id: str | None
    created_at: str
    updated_at: str
    already_sent: bool | None = Field(default=None, description="Только в ответе на «передать»: кандидат уже был передан, дубль не создан")


class AtsStageProviderOut(Doc):
    code: str
    title: str
    enabled: bool
    mode: str
    synced_at: str | None
    info: Obj | None
    linked: int


class AtsStagesOut(Doc):
    """Обратный канал: этапы кандидатов в ATS."""

    poll_s: int = Field(description="Как часто платформа опрашивает ATS, секунд")
    providers: list[AtsStageProviderOut]
    events: list[Obj] = Field(description="Последние смены этапов: кандидат, этап, время")


class AtsStageSyncOut(Doc):
    at: str
    trigger: str
    checked: int
    changed: int
    errors: int
    mode: str
    error: str | None
    ms: int


class AtsWebhookSecretOut(Doc):
    secret: str = Field(description="Секрет подписи вебхука: показывается его владельцу — работодателю")


class AtsStubRecordOut(Doc):
    id: str
    kind: str
    system: str = Field(description="Какую ATS изображает запись: Хантфлоу, Talantix, «Поток», вебхук")
    external_id: int | None
    signature_valid: bool | None
    payload: Obj
    created_at: str


class PotokPipelineRowOut(Doc):
    """Кандидат на вакансии в демо-«Потоке» — как его видит рекрутёр."""

    join_id: int
    applicant_id: int | None
    applicant: str
    job_id: int
    job_name: str
    stage_id: int | None
    stage_name: str | None
    active: bool
    stages: list[Obj] = Field(description="Этапы воронки вакансии: id, name, stage_type")


class AtsPotokMoveOut(Doc):
    moved: Obj | None = Field(description="Запись кандидата на вакансии после перевода")
    pipeline: list[PotokPipelineRowOut]


class VacancyImportItemOut(Doc):
    job_id: int | None
    vacancy_id: str | None
    title: str | None
    state: str
    state_title: str | None = Field(default=None)
    text: str | None = Field(default=None)
    result: str | None = Field(default=None, description="created, updated или skipped (только в ответе на импорт)")
    notes: list[str]
    closed: bool | None = Field(default=None)
    similar_vacancy_id: str | None = Field(default=None)
    category_id: str | None = Field(default=None)
    stack: list[str] | None = Field(default=None)
    salary_from: int | None = Field(default=None)
    salary_to: int | None = Field(default=None)
    salary_from_ats: int | None = Field(default=None)
    city: str | None = Field(default=None)
    work_format: str | None = Field(default=None)
    applicants: int | None = Field(default=None)
    url: str | None = Field(default=None)
    status: str | None = Field(default=None)


class VacancyImportPreviewOut(Doc):
    provider: str
    provider_title: str
    demo: bool
    total: int
    items: list[VacancyImportItemOut]


class VacancyImportOut(Doc):
    created: int
    updated: int
    skipped: int
    items: list[VacancyImportItemOut]


class AtsExportOut(Doc):
    """Выгрузка карточки кандидата для ATS: схема, контекст приглашения или отклика, контакты — только когда раскрыты."""

    schema_: str = Field(alias="schema", description="Версия схемы выгрузки")
    exported_at: str
    source: Obj = Field(description="Откуда выгрузка: platform, url")
    company: Obj = Field(description="Компания: id, name, inn")
    candidate: Obj = Field(description="Кандидат: ref, category_id, category_title, card; contacts — после принятия приглашения")
    context: Obj = Field(description="Приглашение или отклик: type, id, status, position_title, вилка, даты")
    links: Obj = Field(description="Ссылки: card, pdf")
    evidence_levels: dict[str, str] = Field(description="Уровни доказательства T0, T1, T2 — расшифровка")


# ---------------------------------------------------------------- тестовые ATS-заглушки (формат чужих API)


class HuntflowAccountsOut(Doc):
    items: list[Obj] = Field(description="Организации: id, name, nick, member_type")


class HuntflowMeOut(Doc):
    id: int
    name: str
    position: str | None
    email: str | None
    phone: str | None
    locale: str


class HuntflowVacanciesOut(Doc):
    page: int
    count: int
    total_pages: int
    total_items: int
    items: list[Obj] = Field(description="Вакансии: id, position, company, state, …")


class HuntflowStatusesOut(Doc):
    items: list[Obj] = Field(description="Этапы подбора: id, name, type, order, removed")


class HuntflowApplicantOut(Doc):
    id: int
    created: str
    first_name: str | None
    last_name: str | None
    middle_name: str | None
    money: str | None
    phone: str | None
    email: str | None
    position: str | None
    company: str | None


class HuntflowVacancyLinkOut(Doc):
    id: int
    changed: str
    vacancy: int
    status: int
    rejection_reason: Any


class PotokJobOut(Doc):
    id: int
    name: str
    state_id: str = Field(description="opened или closed")
    archived: bool
    company_department: Obj
    salary_from: int | None
    salary_to: int | None
    currency_type: str
    city: str | None
    employment_type: str
    description: str
    key_skills: list[str]
    stages: list[Obj] = Field(description="Этапы: id, name, serial, stage_type")


class PotokJobsOut(Doc):
    data: list[PotokJobOut]


class PotokJoinOut(Doc):
    id: int
    job: Obj
    stage: Obj
    applicant: Obj


class PotokJoinsPageOut(Doc):
    objects: list[Obj]
    has_next_page: bool
    page_next_cursor: str | None


class PotokStageChangeOut(Doc):
    id: int
    stage: Obj


class PotokApplicantOut(Doc):
    id: int
    first_name: str | None
    last_name: str | None
    middle_name: str | None
    emails: list[str]
    phones: list[str]
    source_type: str | None
    created_at: str
    ajs_joins: list[Obj]


class PotokEventOut(Doc):
    id: int
    created_at: str


class PotokDeclineOut(Doc):
    result: str


class TalantixTokenOut(Doc):
    name: str
    access_token: str = Field(description="Токен доступа демо-Talantix (одноразовая пара с refresh-токеном)")
    expires_in: int
    refresh_token: str
    refresh_token_expires_in: int
    token_type: str
    created_at: int


class TalantixGraphqlOut(Doc):
    data: Obj | None
    errors: list[Obj]
    dataPresent: bool


class AtsWebhookReceivedOut(Doc):
    received: bool


# ---------------------------------------------------------------- проверка компании по реестру


class TrustFactorOut(Doc):
    id: str
    title: str
    status: str = Field(description="ok, warn, bad или unknown")
    points: float | int
    max: float | int
    text: str


class TrustCheckOut(Doc):
    kind: str
    title: str
    status: str
    text: str
    hh: Obj | None = Field(None, description="Я12б, при HH_ENABLED: сравнение с рынком hh.ru — n, медиана, p25, p75, "
                                             "регион, дата снимка, conclusive (n ≥ 10)")


class TrustOut(Doc):
    """Оценка надёжности компании по реестру (ЕГРЮЛ) и сравнению вилки с рынком — для кандидата и работодателя."""

    company_id: str
    company_name: str
    score: int = Field(description="0…100")
    level: str
    level_title: str
    preliminary: bool = Field(description="Предварительная оценка: реестр недоступен или данных мало")
    critical: bool = Field(description="Есть критичный сигнал (ликвидация, свежая регистрация и т. п.)")
    demo: bool
    factors: list[TrustFactorOut]
    registry: Obj = Field(description="Сведения реестра: name, registered_at, liquidated_at, director, ogrn, source, note, age_years")
    offer_salary: Obj | None = Field(description="Сравнение вилки приглашения с рынком: status, text")
    salary_checks: list[TrustCheckOut]
    summary: str
    computed_at: str
    method: str


class TrustBriefOut(Doc):
    score: int
    level: str
    level_title: str
    preliminary: bool
    critical: bool
    summary: str
    offer_salary: Obj | None
    demo: bool
    company_id: str


class CompanyVacancyBriefOut(Doc):
    id: str
    title: str
    salary_from: int | None
    salary_to: int | None
    category_id: str | None


class CompanyProfileOut(Doc):
    """Публичная карточка компании для кандидата: описание, вакансии, оценка надёжности."""

    id: str
    name: str
    industry: str | None
    description: str | None
    website: str | None
    city: str | None
    inn: str | None
    is_demo: bool
    trust: TrustOut
    vacancies: list[CompanyVacancyBriefOut]


# ---------------------------------------------------------------- паспорт навыков


class PassportKeyOut(Doc):
    kty: str
    crv: str
    x: str = Field(description="Открытый ключ (Ed25519), base64url")
    kid: str
    alg: str
    use: str
    test_key: bool = Field(description="Тестовый ключ стенда: подписи не имеют силы вне демонстрации")


class PassportKeysOut(Doc):
    alg: str
    keys: list[PassportKeyOut]
    schema_: str = Field(alias="schema", description="Версия формата паспорта")


class PassportStatusOut(Doc):
    """Статус паспорта по реестру: valid, revoked, expired или invalid_signature."""

    state: str
    title: str
    reason: str | None = Field(description="Причина отзыва, если отозван")
    reason_title: str | None
    revoked_at: str | None
    issued_at: str
    valid_until: str
    checked_at: str
    signature_valid: bool
    kid_known: bool
    test_key: bool


class PassportPublicOut(Doc):
    """Публичная проверка паспорта: подписанный документ, подпись, статус и ключ."""

    passport: Obj = Field(description="Разобранный подписанный документ: категория, уровень, достижения, срок")
    document: str = Field(description="Подписанный документ строкой (канонический JSON)")
    signature: Obj = Field(description="alg, kid, value — подпись Ed25519")
    status: PassportStatusOut
    keys: list[PassportKeyOut]
    verify_url: str
    canonicalization: str = Field(description="Как строка документа получается из JSON — чтобы проверить подпись самостоятельно")


class PassportVerifyOut(Doc):
    signature_valid: bool
    kid_known: bool
    test_key: bool
    state: str | None = Field(description="Статус в реестре, если паспорт выпущен платформой")
    registry: Obj | None
    matches_registry: bool | None
    kid_note: str | None = Field(description="Пояснение, если ключ с таким kid платформе неизвестен")


class EmployerPassportLinkOut(Doc):
    """Ссылка работодателю на паспорт кандидата (только если кандидат открыл профиль)."""

    id: str
    url: str
    path: str
    state: str
    title: str
    grade_status: str
    issued_at: str
    valid_until: str
    test_key: bool


# ---------------------------------------------------------------- ФСП ID, push, опрос SUS


class FspIdConfigOut(Doc):
    enabled: bool
    title: str
    demo: bool = Field(description="Демо-режим: вход через встроенный имитатор ФСП ID")
    issuer: str | None
    client_id: str
    flow: str
    demo_accounts: list[Obj] = Field(description="Демо-аккаунты имитатора")
    demo_password: str | None = Field(description="Пароль имитатора, только в демо-режиме")
    note: str


class FspIdStartOut(Doc):
    authorize_url: str
    state: str


class FspIdResultOut(Doc):
    """Результат входа через ФСП ID: готов (токен) или нужно согласие на обработку данных."""

    status: str = Field(description="ok — вход выполнен, consent_required — нужно согласие")
    intent: str | None = Field(default=None, description="login — вход, link — привязка к существующему аккаунту")
    created: bool | None = Field(default=None, description="Аккаунт создан сейчас")
    token: Obj | None = Field(default=None, description="Токен доступа платформы: access_token, token_type, expires_in")
    passport: Obj = Field(description="Что ФСП ID сообщил о человеке (предпросмотр)")
    email_taken: bool | None = Field(default=None)
    registration_role: str | None = Field(default=None)


class PushConfigOut(Doc):
    enabled: bool
    vapid_public_key: str | None


class PushStatusOut(Doc):
    enabled: bool
    devices: int
    last_success_at: str | None


class PushSubscribedOut(Doc):
    subscribed: bool
    devices: int | None = Field(default=None)


class PushTestOut(Doc):
    sent: int


class SusQuestionOut(Doc):
    n: int
    text: str
    positive: bool = Field(description="Утверждение в пользу удобства (иначе — обратное)")


class SusQuestionsOut(Doc):
    questions: list[SusQuestionOut]
    scale: dict[str, str] = Field(description="Шкала ответов 1…5")
    formula: str


class SusSubmitOut(Doc):
    id: str
    score: float = Field(description="Оценка SUS, 0…100")
    adjective: str
    grade: str
    benchmark: float = Field(description="Ориентир — средняя по отрасли (68)")
    above_benchmark: bool


class SusMineOut(Doc):
    answered: bool
    score: float | None = Field(default=None)
    at: str | None = Field(default=None)


class SusStatOut(Doc):
    n: int
    mean: float | None
    median: float | None
    sd: float | None
    ci95: list[float] | None


class SusSummaryOut(Doc):
    """Сводка опроса удобства SUS: среднее с доверительным интервалом, по ролям, распределение."""

    n: int
    mean: float | None
    median: float | None
    sd: float | None
    ci95: list[float] | None = Field(description="95 % доверительный интервал среднего")
    adjective: str | None
    grade: str | None
    benchmark: float
    by_role: dict[str, SusStatOut]
    by_context: dict[str, SusStatOut]
    items_mean: list[float | None] = Field(description="Среднее по каждому из 10 утверждений")
    histogram: list[Obj] = Field(description="Распределение: from, to, n")
    updated_at: str | None
    scope: str = Field(description="Чьи ответы учтены")
    anonymous: Obj = Field(description="Ответы без входа: n, mean, median, sd, ci95, by_context, note")
    all: Obj = Field(description="Все ответы вместе: n, mean, median, sd, ci95")
    method: str


class SusAdminOut(Doc):
    total: int
    summary: SusSummaryOut
    items: list[Obj] = Field(description="Отдельные ответы: роль, контекст, оценка, время")


# Таблица подключения: «МЕТОД /путь» → тип ответа.
TYPES: dict[str, Any] = {
    "GET /api/employer/ats/providers": list[AtsProviderOut],
    "POST /api/employer/ats/demo/connect-all": list[AtsProviderOut],
    "PUT /api/employer/ats/providers/{code}": AtsProviderOut,
    "POST /api/employer/ats/providers/{code}/demo": AtsProviderOut,
    "POST /api/employer/ats/providers/{code}/check": AtsCheckOut,
    "POST /api/employer/ats/huntflow/check": AtsCheckOut,
    "GET /api/employer/ats/providers/{code}/vacancies": list[AtsVacancyOut],
    "GET /api/employer/ats/providers/{code}/vacancies/{vacancy_id}/stages": list[AtsStageOut],
    "GET /api/employer/ats/settings": AtsSettingsOut,
    "PUT /api/employer/ats/settings": AtsSettingsOut,
    "POST /api/employer/ats/stub/connect": AtsSettingsOut,
    "GET /api/employer/ats/deliveries": list[AtsDeliveryOut],
    "POST /api/employer/ats/deliveries/{delivery_id}/retry": list[AtsDeliveryOut],
    "POST /api/employer/ats/push": list[AtsDeliveryOut],
    "GET /api/employer/ats/stages": AtsStagesOut,
    "POST /api/employer/ats/stages/sync": AtsStageSyncOut,
    "GET /api/employer/ats/webhook-secret": AtsWebhookSecretOut,
    "GET /api/employer/ats/stub/records": list[AtsStubRecordOut],
    "GET /api/employer/ats/stub/potok/pipeline": list[PotokPipelineRowOut],
    "POST /api/employer/ats/stub/potok/move": AtsPotokMoveOut,
    "GET /api/employer/vacancies/import/potok/preview": VacancyImportPreviewOut,
    "POST /api/employer/vacancies/import/potok": VacancyImportOut,
    "GET /api/employer/applications/{app_id}/export.json": AtsExportOut,
    "GET /api/employer/invitations/{inv_id}/export.json": AtsExportOut,
    "GET /api/ats-stub/huntflow/v2/accounts": HuntflowAccountsOut,
    "GET /api/ats-stub/huntflow/v2/me": HuntflowMeOut,
    "GET /api/ats-stub/huntflow/v2/accounts/{account_id}/vacancies": HuntflowVacanciesOut,
    "GET /api/ats-stub/huntflow/v2/accounts/{account_id}/vacancies/statuses": HuntflowStatusesOut,
    "POST /api/ats-stub/huntflow/v2/accounts/{account_id}/applicants": HuntflowApplicantOut,
    "POST /api/ats-stub/huntflow/v2/accounts/{account_id}/applicants/{applicant_id}/vacancy": HuntflowVacancyLinkOut,
    "GET /api/ats-stub/potok/api/v3/jobs.json": PotokJobsOut,
    "GET /api/ats-stub/potok/api/v3/jobs/{job_id}.json": PotokJobOut,
    "GET /api/ats-stub/potok/api/v3/jobs/{job_id}/ajs_joins.json": PotokJoinsPageOut,
    "POST /api/ats-stub/potok/api/v3/ajs_joins.json": PotokJoinOut,
    "POST /api/ats-stub/potok/api/v3/ajs_joins/{join_id}/change_stage.json": PotokStageChangeOut,
    "POST /api/ats-stub/potok/api/v3/applicants.json": PotokApplicantOut,
    "GET /api/ats-stub/potok/api/v3/applicants/{applicant_id}.json": PotokApplicantOut,
    "POST /api/ats-stub/potok/api/v3/events.json": PotokEventOut,
    "POST /api/ats-stub/potok/api/v3/jobs/{job_id}/{applicant_id}/decline.json": PotokDeclineOut,
    "POST /api/ats-stub/talantix/graphql": TalantixGraphqlOut,
    "POST /api/ats-stub/talantix/oauth/token": TalantixTokenOut,
    "POST /api/ats-stub/webhook/{stub_key}": AtsWebhookReceivedOut,
    "GET /api/employer/company/trust": TrustOut,
    "POST /api/employer/company/registry-check": TrustOut,
    "GET /api/candidate/invitations/{inv_id}/trust": TrustOut,
    "GET /api/candidate/invitations-trust": dict[str, TrustBriefOut],
    "GET /api/companies/{company_id}": CompanyProfileOut,
    "GET /api/passport/keys": PassportKeysOut,
    "GET /api/passport/{pid}": PassportPublicOut,
    "POST /api/passport/verify": PassportVerifyOut,
    "POST /api/admin/passports/{pid}/revoke": PassportStatusOut,
    "GET /api/employer/candidates/{ref}/passport": EmployerPassportLinkOut,
    "GET /api/fsp-id/config": FspIdConfigOut,
    "POST /api/fsp-id/start": FspIdStartOut,
    "POST /api/fsp-id/exchange": FspIdResultOut,
    "POST /api/fsp-id/complete": FspIdResultOut,
    "GET /api/push/config": PushConfigOut,
    "GET /api/push/status": PushStatusOut,
    "POST /api/push/subscribe": PushSubscribedOut,
    "POST /api/push/unsubscribe": PushSubscribedOut,
    "POST /api/push/test": PushTestOut,
    "GET /api/sus/questions": SusQuestionsOut,
    "POST /api/sus": SusSubmitOut,
    "GET /api/sus/mine": SusMineOut,
    "GET /api/sus/summary": SusSummaryOut,
    "GET /api/admin/sus": SusAdminOut,
}
