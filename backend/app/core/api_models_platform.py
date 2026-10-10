"""Модели ответов для OpenAPI (Я3), часть «платформа»: валидация («Красная кнопка», отчёты, закрытый набор), кабинет ФСП,
живой зал жюри, экспертная панель и очередь оценки.

ТОЛЬКО ДОКУМЕНТАЦИЯ: в декораторах нет `response_model`, поведение API не меняется (см. app/core/api_models.py). Формы взяты из кода
обработчиков и сервисов и сверены с реальными ответами (tests/test_openapi_models.py). Отчёты валидации читаются из файлов,
которые собирает `make validate`/`make bench`; если файла нет, ответ — `{"missing": true}`, поэтому у них все поля необязательные.
Таблица подключения — `TYPES` в конце файла.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.api_models import FspOverviewOut, UserBriefOut
from app.core.api_models_base import Doc, Obj

# ---------------------------------------------------------------- валидация: отчёты (файлы make validate / bench / …)


class ValidationReportOut(Doc):
    """Метрики валидации: банк заданий, калибровка, подбор, симуляция, живые данные, атаки, эксперты."""

    missing: bool | None = Field(default=None, description="true — отчёт ещё не собран (make validate); других полей нет")
    generated_at: str | None = None
    n_per_direction: int | None = Field(default=None, description="Сколько симулированных кандидатов на направление")
    quick: bool | None = Field(default=None, description="Быстрый прогон (меньше выборка)")
    bank: Obj | None = Field(default=None, description="Банк заданий: размер, охват тем, уровни")
    calibration: Obj | None = Field(default=None, description="Калибровка параметров заданий")
    matching: Obj | None = Field(default=None, description="Метрики подбора")
    simulation: Obj | None = Field(default=None, description="Симуляция тестирования: точность оценки, длина теста, доля подтверждений")
    exposure_calibration: Obj | None = Field(default=None, description="Контроль частоты показа заданий")
    seconds: float | None = Field(default=None, description="Сколько секунд считался отчёт")
    provenance: Obj | None = Field(default=None, description="Чем получено: команда, коммит, конфигурация, хеш")
    live: Obj | None = Field(default=None, description="Живые данные платформы: число сеансов, уровни добросовестности")
    attacks: list[Obj] | None = Field(default=None, description="Перечень атак «Красной кнопки»: id, title, action, expected")
    experts: Obj | None = Field(default=None, description="Сводка по экспертной панели (без имён)")
    intern_cut: Obj | None = Field(default=None, description="Порог уровня «Стажёр»")
    self_check: Obj | None = Field(default=None, description="Сводка самопроверки теста")


class ValidationMatchingBenchOut(Doc):
    """Бенчмарк подбора со скрытой истиной: методы, метрики, парные разности, чувствительность, абляции."""

    missing: bool | None = Field(default=None, description="true — отчёт ещё не собран (make bench)")
    version: str | None = None
    algorithm: str | None = None
    weights: Obj | None = Field(default=None, description="Веса компонентов подбора")
    fsp_rating: Obj | None = Field(default=None, description="Версия и параметры рейтинга ФСП")
    generated_at: str | None = None
    command: str | None = Field(default=None, description="Команда, которой отчёт воспроизводится")
    config: Obj | None = None
    config_hash: str | None = None
    seeds: Obj | None = None
    caveat: str | None = Field(default=None, description="Оговорка: на чём получены цифры")
    truth_rules: list[str] | None = Field(default=None, description="Правила, по которым в мире симуляции задана «истина»")
    methods: Obj | None = None
    world: Obj | None = None
    metrics: Obj | None = None
    paired_platform_minus: Obj | None = Field(default=None, description="Парные разности платформы с базовыми методами и доверительные интервалы")
    groups: Obj | None = None
    breakdown: Obj | None = None
    world2: Obj | None = Field(default=None, description="Второй мир симуляции для проверки устойчивости")
    heldout_weights: Obj | None = None
    sensitivity: list[Obj] | None = None
    junior: Obj | None = None
    score_rebuild_max_error: float | None = None
    must_have: Obj | None = None
    ablations: list[Obj] | None = None
    signature: Obj | None = Field(default=None, description="Подпись расчёта: команда, коммит, конфигурация")
    seconds: float | None = None


class ValidationPathRetestOut(Doc):
    """Повторное тестирование всего пути кандидата (test–retest) и характеристики заданий."""

    missing: bool | None = None
    signature: Obj | None = None
    quick: bool | None = None
    n_per_direction: int | None = None
    directions: list[str] | None = None
    config: Obj | None = None
    claimed: Obj | None = Field(default=None, description="Распределение по заявленным грейдам")
    true_grades: Obj | None = None
    total: Obj | None = Field(default=None, description="Итоговые метрики по всем направлениям")
    by_direction: Obj | None = None
    by_claimed: Obj | None = None
    transitions: list[list[int]] | None = Field(default=None, description="Матрица переходов между грейдами при повторном прохождении")
    block_gap: Obj | None = None
    discrimination: Obj | None = None
    procedure: list[str] | None = None
    caveat: str | None = None
    other_reference: Obj | None = Field(default=None, description="Опубликованные показатели других платформ для сравнения")
    seconds: float | None = None


class ValidationJuniorStabilityOut(Doc):
    """Стабильность статуса «Junior (предварительно)» на симулированных кандидатах."""

    missing: bool | None = None
    generated_at: str | None = None
    n_per_direction: int | None = None
    quick: bool | None = None
    seed: int | None = None
    config: Obj | None = None
    rule: Obj | None = None
    directions: Obj | None = None
    total: Obj | None = None
    how_to_read: str | None = None
    signature: Obj | None = None
    seconds: float | None = None
    caveat: str | None = None


class ValidationGraderCheckOut(Doc):
    """Оценщик открытых ответов на наборе панели: инъекции и завышение, до и после защиты."""

    missing: bool | None = None
    generated_at: str | None = None
    dataset: Obj | None = None
    model: str | None = None
    reference: str | None = None
    prompt_version: str | None = None
    disagree: float | None = Field(default=None, description="Доля расхождений с эталоном")
    conditions: Obj | None = None
    routes_v2: Obj | None = None
    tokens: Obj | None = None
    worst_attacks_v2: list[Obj] | None = None
    filter_false_positives: Obj | None = None
    strip_meta_false_positives: Obj | None = None
    attack_filter_caught: Obj | None = None
    llm_pending: bool | None = None
    llm_how: str | None = None


class ValidationLlmModelsOut(Doc):
    """Какая модель где работает: облачные модели, открытая модель на CPU и правила — на одних и тех же наборах."""

    missing: bool | None = None
    date: str | None = None
    rows: list[Obj] | None = None
    cpu: Obj | None = None
    caveat: str | None = None
    how: str | None = None


class ValidationFspRatingOut(Doc):
    """Парный регрессионный бенчмарк формулы рейтинга ФСП (версии v1 и v2)."""

    missing: bool | None = None
    seed: int | None = None
    needs: int | None = None
    candidates: int | None = None
    metrics: Obj | None = None
    weights_changed: bool | None = None
    truth_changed: bool | None = None
    interpretation: str | None = None


class ValidationTestLengthOut(Doc):
    """Длина теста для экрана старта: лимиты и итоги симуляции (синтетика, не люди)."""

    min_items: int | None = None
    max_items: int | None = None
    max_minutes: int | None = None
    ext_items: int | None = Field(default=None, description="Сколько заданий можно добавить при продлении")
    ext_minutes: int | None = None
    sim_mean_items: float | None = None
    sim_extension_share: float | None = Field(default=None, description="Доля симулированных тестов, где потребовалось продление")
    sim_n_per_direction: int | None = None
    sim_directions: int | None = None
    generated_at: str | None = None
    world: str | None = None


class ValidationAttemptsRepeatOut(Doc):
    """Доля повторов заданий между попытками теста: по базе платформы и по синтетике."""

    synthetic: Obj
    live: Obj


class ValidationCriteriaOut(Doc):
    """Страница критериев ТЗ: критерий → что сделать → что увидите → чем доказано."""

    criteria: list[Obj]
    pitch: Obj
    unique: list[Obj]
    how_to_read: str
    personas: Obj
    total_weight: int


class ValidationSelfCheckOut(Doc):
    """Самопроверка теста на синтетическом кандидате с заданной способностью: сколько заданий, какая оценка, чем закончилось."""

    strategy: str
    theta: float
    direction: str
    claimed_grade: str
    mode: str
    n: int
    repeat: bool
    runs_total: int
    seconds: float
    expected: Obj
    confirm_rate: float
    assigned: Obj
    point_grade: Obj
    theta_hat: Obj
    se: Obj
    n_items: Obj
    time_min: Obj
    extension_share: float
    correct_share: float
    stops: Obj
    theta_hat_max: float
    runs: list[Obj]
    retest: Obj
    verdict: Obj


class ValidationAttackOut(Doc):
    """Результат атаки «Красной кнопки»: что делали, что ожидалось и что получилось. Ничего не записывается."""

    id: str
    title: str
    action: str
    expected: str
    seconds: float
    need: str | None = Field(default=None, description="Текст потребности, на которой запускалась атака")
    fact: str | None = Field(default=None, description="Итог одной строкой, который показывают жюри")


# ---------------------------------------------------------------- валидация: закрытый набор жюри


class ClosedSetTemplateOut(Doc):
    """Шаблон анонимного набора жюри. Формат `csv` отдаёт те же данные таблицей с колонкой `kind`; здесь — вид `json`."""

    needs: list[Obj]
    candidates: list[Obj]
    labels: list[Obj]


class ClosedSetNeedResultOut(Doc):
    need_id: str
    requirements: Obj = Field(description="Разобранные требования потребности")
    eligible: int = Field(description="Сколько профилей прошло фильтр по направлению и грейду")
    returned: int
    label_coverage: float = Field(description="Доля профилей с разметкой релевантности")
    metrics: Obj | None = Field(description="p@k, nDCG@k — только если разметка полная")
    results: list[Obj] = Field(description="Выдача: candidate_id, rank, score, components, reasons, relevance")


class ClosedSetResultOut(Doc):
    """Подбор на закрытом наборе жюри: выдача по каждой потребности и метрики. Данные обрабатываются в памяти запроса."""

    algorithm: str
    n_needs: int
    n_candidates: int
    k: int
    evaluated_needs: int
    summary: Obj | None = Field(description="Средние p@k и nDCG@k по потребностям с полной разметкой")
    per_need: list[ClosedSetNeedResultOut]
    note: str


# ---------------------------------------------------------------- кабинет ФСП (агрегаты, малые группы скрыты)


class CabinetCupOut(Doc):
    id: str
    title: str
    company: str
    category_id: str | None = None
    category_title: str | None = None
    mode: str | None = None
    phase: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    invite_top_n: int | None = None
    participants: int | None = None
    placed: int | None = None
    invited: int | None = None
    accepted: int | None = None
    passport_written: int | None = None
    passport_pending: int | None = None
    score_median_pct: float | None = Field(default=None, description="Медиана результата, %; скрыта в малых группах")


class DemandCategoryOut(Doc):
    category_id: str
    title: str
    direction: str
    grade: str
    needs: int | None = None
    companies: int | None = None
    invitations: int | None = None
    invited_candidates: int | None = None
    supply: int | None = Field(default=None, description="Сколько кандидатов подтвердили категорию")
    invitations_per_10: float | None = None
    invite_rate: float | None = None
    accepted_candidates: int | None = None
    accept_rate: float | None = None
    market_median: int | None = None


class DemandSkillOut(Doc):
    tag: str
    title: str
    direction: str | None = None
    needs_required: int | None = None
    needs_desired: int | None = None
    demand_weight: float | None = None
    companies: int | None = None
    supply_confirmed: int | None = None
    invited_with_skill: int | None = None
    invite_rate_with_skill: float | None = None


class CabinetDemandOut(Doc):
    """Спрос работодателей по категориям и навыкам против предложения."""

    categories: list[DemandCategoryOut]
    needs_without_grade: dict[str, int] = Field(description="Потребности без грейда по направлениям")
    skills: list[DemandSkillOut]


class FspEffectCellOut(Doc):
    candidates: int | None = None
    invited: int | None = None
    invite_rate: float | None = None
    accepted: int | None = None
    accept_rate: float | None = None
    invitations_per_candidate: float | None = None
    lift_vs_no_fsp: float | None = Field(default=None, description="Во сколько раз чаще приглашают, чем без достижений ФСП")
    adjusted_ratio: float | None = Field(default=None, description="То же с поправкой на категорию")


class FspEffectRowOut(FspEffectCellOut):
    key: str
    title: str


class FspEffectDirectionOut(Doc):
    direction: str
    title: str
    fsp: FspEffectCellOut
    no_fsp: FspEffectCellOut


class FspEffectOut(Doc):
    """Эффект достижений ФСП на приглашения: группы, дисциплины, разряды, результаты, уровни, направления."""

    groups: list[FspEffectRowOut]
    disciplines: list[FspEffectRowOut]
    ranks: list[FspEffectRowOut]
    results: list[FspEffectRowOut]
    levels: list[FspEffectRowOut]
    by_direction: list[FspEffectDirectionOut]
    base_invite_rate: float | None = Field(default=None, description="Доля приглашённых среди кандидатов без достижений ФСП")


class FunnelStepOut(Doc):
    key: str
    title: str
    count: int | None = None
    conversion: float | None = Field(default=None, description="Доля от предыдущего шага")


class CabinetFunnelOut(Doc):
    """Воронка от кандидата с категорией до принятого приглашения: все, с ФСП, без ФСП, участники кубков."""

    all: list[FunnelStepOut]
    fsp: list[FunnelStepOut]
    no_fsp: list[FunnelStepOut]
    cups: list[FunnelStepOut]
    note: str


class SalaryCategoryOut(Doc):
    category_id: str
    title: str
    direction: str
    grade: str
    offers: int | None = None
    suppressed: bool = Field(description="Группа мала: цифры скрыты")
    reason: str | None = None
    market_from: int | None = None
    market_to: int | None = None
    market_median: int | None = None
    market_source: str | None = None
    accepted_mid_median: int | None = None
    declined_mid_median: int | None = None


class SalaryDirectionOut(Doc):
    direction: str
    title: str
    offers: int | None = None
    suppressed: bool
    reason: str | None = None


class CabinetSalariesOut(Doc):
    """Зарплатные вилки предложений по категориям и направлениям; группы меньше порога скрыты."""

    categories: list[SalaryCategoryOut]
    directions: list[SalaryDirectionOut]
    rules: Obj = Field(description="Пороги скрытия: min_offers, min_candidates, min_companies")


class CabinetReportOut(Doc):
    """Полный отчёт кабинета ФСП за период: те же разделы, что и отдельные запросы, и методология. Только агрегаты."""

    generated_at: str
    k: int
    period_days: int | None
    overview: FspOverviewOut
    demand: CabinetDemandOut
    fsp_effect: FspEffectOut
    salaries: CabinetSalariesOut
    funnel: CabinetFunnelOut
    cups: list[CabinetCupOut]
    methodology: list[str]


# ---------------------------------------------------------------- живой зал жюри (мини-тест гостей по QR)


class LivePushConfigOut(Doc):
    enabled: bool
    vapid_public_key: str | None


class LiveDirectionOut(Doc):
    id: str
    title: str
    need: str = Field(description="Название потребности, под которую подбирают гостя этого направления")


class LiveRoomPublicOut(Doc):
    """Зал по коду из QR: открыт ли, направления, правило приглашения."""

    code: str
    company: str
    open: bool
    items: int = Field(description="Сколько заданий в мини-тесте")
    rule: str
    push: LivePushConfigOut
    directions: list[LiveDirectionOut]


class LiveRoomOut(Doc):
    """Зал песочницы жюри: код, ссылка и QR для экрана."""

    code: str
    url: str
    qr_svg: str = Field(description="Путь к QR-коду в SVG")
    qr_png: str = Field(description="Путь к QR-коду в PNG")
    rule: str
    company: str
    items: int
    push: LivePushConfigOut


class LiveGuestOut(Doc):
    """Состояние гостя: для его телефона (своё задание, доказательства) или для большого экрана (без задания, с номером)."""

    number: int
    label: str
    ref: str = Field(description="Обезличенный номер кандидата")
    direction: str
    direction_title: str | None
    stage: str = Field(description="testing, finished, selected, invited, accepted или declined")
    answered: int
    total: int
    created_at: str | None
    finished_at: str | None
    result: Obj | None = Field(description="Итог: theta, se, grade, category_id, category_title, skills, preliminary…")
    selection: Obj | None = Field(description="Место в подборке: need_title, rank, total, score, reasons, components, top (для экрана)")
    invite: Obj | None = Field(description="Приглашение: должность, вилка, push, отправлено, просмотрено; для телефона — компания и индекс доверия")
    invite_failed: bool
    id: str | None = Field(default=None, description="Идентификатор гостя (только для большого экрана)")
    item: Obj | None = Field(default=None, description="Текущее задание (только для телефона гостя, пока идёт тест)")


class LiveGuestStartOut(Doc):
    token: str = Field(description="Токен гостя: передаётся в заголовке X-Guest-Token")
    guest: LiveGuestOut


class LivePushSubscribedOut(Doc):
    subscribed: bool
    devices: int


class LiveCountersOut(Doc):
    joined: int
    testing: int
    finished: int
    with_category: int
    selected: int
    invited: int
    accepted: int
    declined: int
    push_delivered: int


class LiveEventOut(Doc):
    at: str
    kind: str
    guest: int
    label: str
    ref: str
    text: str


class LiveRoomFeedOut(Doc):
    """Лента зала для большого экрана. `changed: false` — ничего не изменилось, остальных полей нет."""

    changed: bool
    rev: int
    now: str
    code: str | None = None
    url: str | None = None
    qr_svg: str | None = None
    qr_png: str | None = None
    rule: str | None = None
    company: str | None = None
    items: int | None = None
    push: LivePushConfigOut | None = None
    guests: list[LiveGuestOut] | None = None
    events: list[LiveEventOut] | None = None
    counters: LiveCountersOut | None = None
    next_reveal_at: str | None = Field(default=None, description="Когда на экране появится следующий результат")


class LiveRoomClearedOut(Doc):
    deleted: int = Field(description="Сколько гостей удалено")


class JuryResetOut(Doc):
    """Сброс песочницы жюри: пересозданные персонажи и вход под выбранной ролью (токен — обычный JWT демо-учётки)."""

    ok: bool
    candidate: Obj
    candidate_nofsp: Obj
    candidate_junior: Obj
    candidate_new: Obj
    employer: Obj
    expert: Obj
    scenario: str
    seconds: float
    deleted_users: int
    access_token: str
    token_type: str
    expires_in: int
    user: UserBriefOut
    persona: str
    landing: str
    shared: bool


class JurySandboxDeletedOut(Doc):
    ok: bool
    scenario: str | None
    deleted_users: int
    seconds: float


# ---------------------------------------------------------------- экспертиза: очередь оценки и панель


class ExpertQueueItemOut(Doc):
    token: str
    part: int
    format: str
    position: int
    stem: str
    code: str | None = None
    code_language: str | None = None
    step_prompt: str | None = None
    rubric: Obj
    answer: str
    skills: list[str]
    status: str
    method: str | None
    score: float | None
    expert: Obj | None
    llm: Obj | None
    session_id: str
    session_status: str
    candidate_ref: str
    direction: str
    claimed_grade: str
    at: str | None


class ExpertQueueOut(Doc):
    """Очередь развёрнутых ответов на оценку по рубрике (ответы без ФИО)."""

    mode: str = Field(description="pending, llm или reviewed")
    counts: Obj = Field(description="Сколько ответов в каждой очереди: pending, llm, reviewed")
    items: list[ExpertQueueItemOut]


class ExpertReviewOut(Doc):
    review: Obj = Field(description="Принятая оценка: баллы по критериям, итог, эксперт, время")
    recomputed: bool = Field(description="Сессия завершена, оценка применена — результат пересчитан")
    theta: float | None = Field(default=None, description="Только при пересчёте")
    se: float | None = None
    confirmed: bool | None = None
    confirmed_before: bool | None = None
    pending_left: int | None = None
    message: str | None = None


class ExpertAgreementOut(Doc):
    """Согласие оценок языковой модели и экспертов на ответах, которые оценили оба."""

    n: int
    mae: float | None = Field(default=None, description="Средняя абсолютная разница баллов")
    within_025: float | None = Field(default=None, description="Доля пар, где баллы различаются не более чем на 0,25")


class ExpertProgressBlockOut(Doc):
    total: int
    done: int
    minutes_left: int


class ExpertPanelMeOut(Doc):
    """Эксперт панели: код, прогресс по блокам A, B, C. Не в панели — только `in_panel: false`."""

    in_panel: bool
    code: str | None = None
    name: str | None = None
    is_demo: bool | None = None
    pack: str | None = None
    instructions_ack_at: str | None = None
    progress: dict[str, ExpertProgressBlockOut] | None = None


class ExpertPanelItemsOut(Doc):
    kind: str = Field(description="A, B или C")
    items: list[Obj] = Field(description="Объекты назначения вслепую (id, n, group, содержимое) и сохранённая оценка label")
    progress: ExpertProgressBlockOut


class ExpertLabelSavedOut(Doc):
    saved: bool
    item_id: str
    value: Obj
    progress: ExpertProgressBlockOut


class ExpertInviteOut(Doc):
    """Приглашение эксперта. Токен показывается один раз — в базе только хеш."""

    code: str
    slot: str
    team_size: int
    created: bool
    token: str = Field(description="Одноразовый секрет персональной ссылки")
    url: str
    assigned: dict[str, int] = Field(description="Сколько объектов назначено в блоках A, B, C")


class ExpertEnterOut(Doc):
    """Вход эксперта по ссылке: токен доступа. Если подключён второй фактор — вместо токена промежуточный токен и методы."""

    access_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    code: str | None = Field(default=None, description="Код эксперта в панели")
    landing: str | None = None
    pending_token: str | None = Field(default=None, description="Только при втором факторе: токен для POST /api/auth/2fa/verify")
    setup_required: bool | None = None
    methods: list[str] | None = None
    email: str | None = None
    role: str | None = None


class ExpertPanelStatusRowOut(Doc):
    code: str
    active: bool
    started: bool
    source: str = Field(description="people или model")
    source_model: str | None
    role: str | None
    progress: dict[str, Obj] = Field(description="По блокам A, B, C: done, total")
    uniform: list[str] = Field(description="Блоки, где все оценки одинаковы")
    last_seen_at: str | None


class ExpertPanelStatusOut(Doc):
    panel: list[ExpertPanelStatusRowOut]


# Таблица подключения: «МЕТОД /путь» → тип ответа.
TYPES: dict[str, Any] = {
    "GET /api/validation/report": ValidationReportOut,
    "GET /api/validation/matching-bench": ValidationMatchingBenchOut,
    "GET /api/validation/path-retest": ValidationPathRetestOut,
    "GET /api/validation/junior-stability": ValidationJuniorStabilityOut,
    "GET /api/validation/grader-check": ValidationGraderCheckOut,
    "GET /api/validation/llm-models": ValidationLlmModelsOut,
    "GET /api/validation/fsp-rating": ValidationFspRatingOut,
    "GET /api/validation/test-length": ValidationTestLengthOut,
    "GET /api/validation/attempts-repeat": ValidationAttemptsRepeatOut,
    "GET /api/validation/criteria": ValidationCriteriaOut,
    "POST /api/validation/self-check": ValidationSelfCheckOut,
    "POST /api/validation/attacks/{attack_id}": ValidationAttackOut,
    "GET /api/validation/closed-set/template/{format}": ClosedSetTemplateOut,
    "POST /api/validation/closed-set/evaluate": ClosedSetResultOut,
    "GET /api/fsp-cabinet/cups": list[CabinetCupOut],
    "GET /api/fsp-cabinet/demand": CabinetDemandOut,
    "GET /api/fsp-cabinet/fsp-effect": FspEffectOut,
    "GET /api/fsp-cabinet/funnel": CabinetFunnelOut,
    "GET /api/fsp-cabinet/salaries": CabinetSalariesOut,
    "GET /api/fsp-cabinet/report": CabinetReportOut,
    "GET /api/jury/live/j/{code}": LiveRoomPublicOut,
    "POST /api/jury/live/j/{code}/start": LiveGuestStartOut,
    "GET /api/jury/live/j/{code}/me": LiveGuestOut,
    "POST /api/jury/live/j/{code}/answer": LiveGuestOut,
    "POST /api/jury/live/j/{code}/respond": LiveGuestOut,
    "POST /api/jury/live/j/{code}/push": LivePushSubscribedOut,
    "POST /api/jury/live/room": LiveRoomOut,
    "GET /api/jury/live/room/feed": LiveRoomFeedOut,
    "POST /api/jury/live/room/clear": LiveRoomClearedOut,
    "POST /api/jury/reset": JuryResetOut,
    "DELETE /api/jury/sandbox": JurySandboxDeletedOut,
    "GET /api/expert/queue": ExpertQueueOut,
    "POST /api/expert/review": ExpertReviewOut,
    "GET /api/expert/agreement": ExpertAgreementOut,
    "POST /api/expert-panel/enter": ExpertEnterOut,
    "GET /api/expert-panel/me": ExpertPanelMeOut,
    "POST /api/expert-panel/ack": ExpertPanelMeOut,
    "GET /api/expert-panel/items/{kind}": ExpertPanelItemsOut,
    "POST /api/expert-panel/labels": ExpertLabelSavedOut,
    "POST /api/expert-panel/invites": ExpertInviteOut,
    "GET /api/expert-panel/status": ExpertPanelStatusOut,
}
