"""Модели ответов для OpenAPI (Я3), часть «работа с найдом»: кубки, задания, найм, подписки, взаимный подбор.

ТОЛЬКО ДОКУМЕНТАЦИЯ — как и app/core/api_models.py: в декораторах нет `response_model`, поведение API не меняется. Формы взяты
из кода сборки ответов (cup/router.py `cup_out`, assignments/service.py `attempt_brief`, hiring/service.py `state_out`,
subs/service.py `sub_out`, mutual/service.py) и сверены с реальными ответами (tests/test_openapi_models.py).
Поле обязательно, если есть в каждом ответе; значение может быть null — тогда `| None`. Блоки, меняющиеся от сценария
к сценарию, описаны как `dict`; их состав — в примере ответа. `extra="allow"`: перечень полей не исчерпывающий.
Таблица подключения — `TYPES` в конце файла: «МЕТОД /путь» → тип (её сливает api_models.RESPONSE_TYPES).
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.api_models import SelectionOut
from app.core.api_models_base import Doc, Obj

# ---------------------------------------------------------------- кубки работодателя


class CupCompanyOut(Doc):
    id: str
    name: str
    industry: str | None
    city: str | None


class CupRubricItemOut(Doc):
    id: str
    title: str
    weight: float | int = Field(description="Вес критерия в оценке работодателя")


class CupOut(Doc):
    """Кубок работодателя: соревнование в одной категории, результат — запись в паспорте ФСП (мероприятие платформы)."""

    id: str
    title: str
    description: str
    category_id: str = Field(description="Категория «направление.грейд», например backend.middle")
    category_title: str
    direction: str
    grade: str
    mode: str = Field(description="Способ оценки: auto — автопроверка заданий банка, rubric — оценка работодателем по рубрике, …")
    mode_title: str
    phase: str = Field(description="Фаза по времени: upcoming (ещё не началась), active, closed (приём решений завершён), finished")
    status: str = Field(description="Статус кубка: active, finished или cancelled")
    starts_at: str | None
    ends_at: str | None
    time_limit_min: int = Field(description="Время на решение у участника, минут")
    n_tasks: int = Field(description="Число заданий в автопроверяемом кубке")
    salary_from: int
    salary_to: int
    salary_basis: str = Field(description="gross — до вычета налога, net — на руки")
    salary_basis_title: str
    invite_top_n: int = Field(description="Сколько лучших участников получат приглашение по итогам")
    min_score_pct: int = Field(description="Минимальный балл (%) для приглашения")
    position_title: str = Field(description="Позиция, на которую приглашают по итогам")
    offer_description: str
    contact_method: str
    rubric: list[CupRubricItemOut] | None = Field(description="Рубрика оценки (только mode = rubric)")
    company: CupCompanyOut | None
    participants: int
    submitted: int = Field(description="Сдали решение (в том числе уже оценённые)")
    to_review: int = Field(description="Ждут оценки работодателя")
    summary: Obj = Field(description="Итоги после завершения: best_pct, joined, placed, invited, invite_top_n, early, expired, finalized_at; до завершения — пустой объект")
    finalized_at: str | None
    is_demo: bool


class CupLeaderRowOut(Doc):
    """Строка таблицы результатов: участник под псевдонимом («Участник 01»), без имён."""

    alias: str
    position: int | None = Field(description="Место; у несдавших — null")
    status: str = Field(description="joined, in_progress, submitted, scored, expired")
    score_pct: int | None
    time_spent_s: int | None
    me: bool = Field(description="Это строка текущего пользователя")
    invited: bool = Field(description="Участнику отправлено приглашение по итогам кубка")
    entry_id: str | None = Field(default=None, description="Только в ответах работодателю")
    invite_note: str | None = Field(default=None, description="Только в ответах работодателю: пометка к приглашению")
    candidate_ref: str | None = Field(default=None, description="Только работодателю и только после приглашения: обезличенный номер кандидата")
    invitation_status: str | None = Field(default=None, description="Только работодателю: статус приглашения")
    full_name: str | None = Field(default=None, description="Только работодателю и только после принятия приглашения кандидатом")


class CupSolutionOut(Doc):
    """Решение для оценки работодателем — вслепую: псевдоним, текст без персональных данных, ссылки скрыты."""

    entry_id: str
    alias: str
    status: str
    submitted_at: str | None
    time_spent_s: int | None
    score_pct: int | None
    score_method: str | None = Field(description="auto, llm или employer")
    text: str | None = Field(description="Текст ответа с вымаранными персональными данными")
    has_link: bool = Field(description="В ответе была ссылка (сама ссылка работодателю не показывается)")
    redacted: list[str] = Field(description="Что вымарано из текста")
    llm: Obj | None = Field(description="Предварительная оценка языковой моделью: status, score, criteria, comment, model")
    employer: Obj | None = Field(description="Оценка работодателя, если уже поставлена")
    auto: Obj | None = Field(description="Результат автопроверки: correct, total (только mode = auto)")


class CupEmployerOut(CupOut):
    """Кубок в ответах работодателю: плюс текст задания, таблица результатов и решения (в ответах на список и создание их нет)."""

    task_text: str | None = Field(description="Текст задания (mode = rubric)")
    leaderboard: list[CupLeaderRowOut] | None = Field(default=None, description="Таблица результатов (карточка кубка и завершение)")
    solutions: list[CupSolutionOut] | None = Field(default=None, description="Решения для оценки (карточка кубка и завершение)")


class CupEntryOut(Doc):
    """Участие текущего кандидата в кубке."""

    id: str
    alias: str
    status: str
    started_at: str | None
    deadline_at: str | None
    submitted_at: str | None
    time_spent_s: int | None
    score_pct: int | None
    score_method: str | None
    place: int | None
    task_text: str | None
    tasks: list[Obj] = Field(description="Задания с вариантами ответа (после старта); верные ответы раскрываются, когда кубок завершён")
    answer: Obj | None = Field(description="Отправленный ответ: text, link")
    auto: Obj | None = Field(description="Результат автопроверки")
    invitation_id: str | None
    invitation_status: str | None
    invite_note: str | None
    passport_status: str | None = Field(description="Запись в паспорт ФСП: written, pending, …")


class CupCandidateOut(CupOut):
    """Кубок в ответах кандидату: плюс его участие и условия вступления."""

    my_entry: CupEntryOut | None
    below_my_minimum: bool = Field(description="Верх вилки ниже вашего минимума зарплаты (сам минимум не раскрывается)")
    can_join: bool
    profile_visible: bool = Field(description="Ваш профиль виден работодателям")
    leaderboard: list[CupLeaderRowOut]


class CupCandidateItemOut(CupOut):
    my_status: str | None = Field(description="Статус моего участия или null")
    my_place: int | None
    below_my_minimum: bool


class CandidateCupsOut(Doc):
    category_id: str | None
    category_title: str | None
    items: list[CupCandidateItemOut]


class CupPassportRowOut(Doc):
    """Место кандидата в кубке — запись «мероприятие платформы» в паспорте ФСП."""

    cup_id: str
    title: str
    company: str | None
    category_title: str
    date: str
    place: int
    of: int = Field(description="Из скольких участников с местом")
    score_pct: int | None
    result_title: str
    invited: bool
    level: str = Field(description="Уровень доказательства записи: T1")
    event_level: str = Field(description="Уровень мероприятия: platform")
    passport_status: str | None


class CupOptionsOut(Doc):
    category_id: str
    category_title: str
    market: Obj = Field(description="Вилка рынка по категории: from, to, median")
    candidates: int = Field(description="Видимых работодателям кандидатов в категории")
    auto_tasks_available: int = Field(description="Сколько заданий банка доступно для автопроверяемого кубка")
    modes: dict[str, str] = Field(description="Способы оценки: код → название")
    default_rubric: list[Obj] = Field(description="Рубрика по умолчанию: id, title, weight")


# ---------------------------------------------------------------- задания работодателя и лента кандидата


class AssignmentFamilyOut(Doc):
    title: str
    format: str = Field(description="Формат задания банка: predict_output, find_bug, …")
    language: str | None
    difficulty: float
    tags: list[str]
    tag_titles: list[str]


class AssignmentCoverageOut(Doc):
    covered: list[str] = Field(description="Навыки стека, под которые нашлись задания банка")
    missing: list[str] = Field(description="Навыки стека без заданий в банке")
    missing_titles: list[str]


class AssignmentStackItemOut(Doc):
    tag: str
    title: str


class AssignmentCompanyOut(Doc):
    id: str
    name: str


class AssignmentOut(Doc):
    """Задание работодателя: открытое, к вакансии или зонд; результат — факт T1 в паспорте кандидата."""

    id: str
    mode: str = Field(description="open — открытое задание, vacancy — к вакансии, probe — зонд")
    title: str
    description: str
    status: str = Field(description="active или closed")
    direction_id: str
    grade_id: str
    category_title: str
    stack: list[AssignmentStackItemOut]
    families: list[AssignmentFamilyOut]
    n_tasks: int
    time_limit_min: int
    coverage: AssignmentCoverageOut
    salary_from: int | None
    salary_to: int | None
    need_id: str | None
    vacancy_id: str | None
    is_demo: bool
    created_at: str
    company: AssignmentCompanyOut | None
    rubric: Obj | None = Field(description="Рубрика: criteria (критерии с баллами) и max")
    approach_prompt: str | None = Field(description="Просьба описать подход, если оценка идёт и по рубрике")
    attempts_total: int | None = Field(default=None, description="Всего попыток (в ответах работодателю)")
    attempts_by_status: dict[str, int] | None = Field(default=None, description="Попытки по статусам: offered, in_progress, scored, expired, …")
    to_review: int | None = Field(default=None, description="Ждут оценки работодателя")
    sent: int | None = Field(default=None, description="Сколько предложений выдано (ответ на «разослать»)")


class AssignmentPreviewOut(Doc):
    """Предпросмотр задания до создания: подобранные задания банка и покрытие стека."""

    stack: list[str]
    direction: str
    grade: str
    title: str | None
    salary_from: int | None
    salary_to: int | None
    need_id: str | None
    vacancy_id: str | None
    category_title: str
    stack_titles: list[str]
    families: list[AssignmentFamilyOut]
    n_tasks: int
    coverage: AssignmentCoverageOut
    time_limit_min: int
    rubric: Obj = Field(description="Рубрика с просьбой описать подход: criteria, max")
    rubric_auto: Obj = Field(description="Рубрика только с автоматической частью")
    approach_prompt: str


class AssignmentAttemptOut(Doc):
    """Попытка выполнить задание (краткая запись, общая для кандидата и работодателя)."""

    attempt_id: str
    assignment_id: str
    title: str | None
    status: str = Field(description="offered, in_progress, scored, declined, expired")
    status_title: str
    source: str = Field(description="Откуда задание: feed (лента), invitation, application, …")
    score: float | None
    score_pct: int | None
    correct: float | int | None
    total: int | None
    time_spent_s: int | None
    submitted_at: str | None
    offered_at: str | None
    skills: list[Obj] = Field(description="Навыки по заданию: tag, title, correct, total, …")
    why: Obj | None = Field(description="Почему предложено (для ленты): текст и сигналы")
    review_status: str | None = Field(description="Оценка работодателя: pending, reviewed, …")
    review_title: str
    final_points: float | int | None
    reviewed_at: str | None
    remind_at: str | None
    remind_count: int | None
    rubric: Obj | None = Field(default=None, description="Рубрика с баллами (только после проверки)")


class AssignmentEmployerAttemptOut(AssignmentAttemptOut):
    candidate_ref: str | None = Field(description="Обезличенный номер кандидата")
    candidate_category: str | None
    approach_text: str | None = Field(description="Описание подхода, если запрошено (только после проверки)")
    review_remind_at: str | None
    review_remind_count: int | None


class AssignmentDetailOut(AssignmentOut):
    attempts: list[AssignmentEmployerAttemptOut]


class AssignmentFeedItemOut(AssignmentAttemptOut):
    assignment: AssignmentOut


class AssignmentCandidateAttemptOut(AssignmentAttemptOut):
    """Задание кандидата с описанием, вариантами (после старта) и результатом."""

    assignment: AssignmentOut
    started_at: str | None
    deadline_at: str | None
    grace_s: int = Field(description="Допуск на отправку после дедлайна, секунд")
    approach_text: str | None
    tasks: list[Obj] | None = Field(description="Задания с вариантами (в процессе и после проверки); верные ответы — только после проверки")
    application_id: str | None = Field(default=None, description="Отклик, к которому привязано задание")


class FeedScheduleOut(Doc):
    """Расписание ленты «Задания для вас»."""

    frequency_days: int = Field(description="Выбранная частота, дней (0 — выключено)")
    effective_days: int = Field(description="Фактическая частота с учётом паузы, дней")
    options: list[int]
    paused: bool
    backoff: bool = Field(description="Частота снижена из-за пропущенных заданий")
    pending: bool = Field(description="Есть непройденное предложение")
    due: bool
    blocked: str | None = Field(description="Причина, по которой новое предложение не выдаётся: pending, limit, …")
    last_offer_at: str | None
    next_at: str | None
    limit: int = Field(description="Не более предложений за окно window_days")
    used: int
    window_days: int
    remind_days: int
    ttl_days: int


class SkillFreshnessOut(Doc):
    tag: str
    title: str
    at: str | None
    date: str | None
    confirmed: bool
    correct: float | int | None
    total: int | None
    score: float | None


class FreshnessOut(Doc):
    """Свежесть подтверждений навыков: сколько навыков подтверждено недавно, сколько устаревает."""

    n: int
    fresh: int
    aging: int
    stale: int
    weak: int
    fresh_days: int
    stale_days: int
    share_fresh: float
    level: str
    title: str
    text: str
    last_confirmed_at: str | None
    skills: list[SkillFreshnessOut]


class CandidateAssignmentsOut(Doc):
    items: list[AssignmentFeedItemOut]
    feed_days: int
    new_offer: str | None = Field(description="Идентификатор попытки, предложенной прямо сейчас")
    has_category: bool
    schedule: FeedScheduleOut
    freshness: FreshnessOut | None
    demo: bool


class DemoNextWeekOut(Doc):
    expired: int
    reminded: int
    review_reminded: int
    offered: str | None


# ---------------------------------------------------------------- найм: интервью, оффер, итог


class InterviewOut(Doc):
    id: str
    round: int
    title: str | None
    status: str = Field(description="proposed — предложены слоты, scheduled — время выбрано, done, cancelled")
    slots: list[Obj] = Field(description="Предложенные слоты: starts_at, duration_min, format, place")
    chosen_slot: Any
    starts_at: str | None
    starts_text: str | None = Field(description="Время начала по Москве, готовая строка")
    duration_min: int | None
    format: str | None
    format_title: str | None
    place: str | None
    note: str | None
    candidate_note: str | None
    reschedules: int
    reschedules_left: int
    result_note: str | None
    done_at: str | None
    created_at: str


class OfferOut(Doc):
    id: str
    status: str = Field(description="sent, accepted, declined, withdrawn, expired")
    salary: int
    salary_basis: str
    salary_basis_title: str
    start_date: str
    respond_until: str
    respond_until_text: str
    comment: str | None
    decline_reason: str | None
    counters: list[Obj] = Field(description="Встречные предложения кандидата и ответы работодателя")
    counter: Obj | None = Field(description="Встречное предложение, ожидающее ответа")
    counters_left: int
    created_at: str
    responded_at: str | None


class OutcomeOut(Doc):
    outcome: str = Field(description="hired, rejected или declined")
    title: str
    note: str | None
    start_date: str | None
    at: str


class HiringRulesOut(Doc):
    slots_max: int
    reschedule_max: int
    counter_max: int
    counter_max_up: float
    offer_max_up: float
    respond_max_days: int
    demo_done_anytime: bool = Field(description="В демо-компании интервью можно отметить проведённым в любой момент")


class HiringEmployerCanOut(Doc):
    propose: bool
    done: bool
    cancel: bool
    offer: bool
    withdraw_offer: bool
    hired: bool
    rejected: bool
    declined: bool


class HiringCandidateCanOut(Doc):
    choose: bool
    reschedule: bool
    answer_offer: bool


class HiringStateBase(Doc):
    invitation_id: str
    stage: str = Field(description="Этап найма: invited, interview, offer, hired, …")
    stage_title: str
    open: bool = Field(description="Контакты раскрыты, итог не зафиксирован")
    paused: bool = Field(description="Контакты отозваны кандидатом — найм приостановлен")
    interview: InterviewOut | None = Field(description="Текущее интервью")
    interviews: list[InterviewOut]
    offer: OfferOut | None = Field(description="Текущий оффер")
    offers: list[OfferOut]
    outcome: OutcomeOut | None
    salary_from: int | None
    salary_to: int | None
    salary_basis: str
    rules: HiringRulesOut


class HiringEmployerStateOut(HiringStateBase):
    """Состояние найма для работодателя (в том числе ответ на каждое действие: предложить слоты, оффер, итог)."""

    presets: Obj | None = Field(description="Готовые значения форм: slots (три слота), offer (вилка, выход, срок ответа)")
    can: HiringEmployerCanOut
    ats: list[Obj] = Field(description="Выгрузки в ATS по этому приглашению")


class HiringCandidateStateOut(HiringStateBase):
    """Состояние найма для кандидата (и ответ на каждое его действие: выбрать слот, ответить на оффер)."""

    can: HiringCandidateCanOut


class HiringTodoOut(Doc):
    items: list[Obj] = Field(description="Что сделать по найму: приглашение, этап, действие")
    total: int


# ---------------------------------------------------------------- подписки на подбор и тики


class SubscriptionFrequencyOut(Doc):
    id: str
    title: str


class SubscriptionOut(Doc):
    """Подписка на новых подходящих кандидатов по потребности."""

    need_id: str
    need_status: str
    top_n: int = Field(description="Сколько верхних мест подборки отслеживается")
    frequencies: list[SubscriptionFrequencyOut]
    exists: bool
    enabled: bool
    frequency: str
    frequency_title: str | None = Field(default=None, description="Есть, когда подписка создана")
    new_count: int
    new: list[Obj] = Field(description="Новые в верхних местах: обезличенная строка подборки + rank, score, entered_at")
    new_refs: list[str]
    in_top: int
    computed_at: str | None
    baseline_at: str | None


class SubscriptionItemOut(Doc):
    need_id: str
    enabled: bool
    frequency: str
    new_count: int
    computed_at: str | None


class SubscriptionsOut(Doc):
    items: list[SubscriptionItemOut]
    new_total: int


class SubscriptionNewVersionOut(Doc):
    version: int
    parent_version: int


class SubsFastForwardOut(Doc):
    days: int
    created: Obj = Field(description="Сколько записей смоделировано: inv_expiring, inv_expired, inv_unanswered, app_stale")
    why: str


class SubsSimulateOut(Doc):
    candidate_ref: str
    category_id: str
    need_id: str
    need_title: str
    confirmed: bool
    auto_subscribed: bool
    entered_top: bool
    rank: int | None
    score: float | None
    top_n: int
    notification: Obj | None
    tick: Obj = Field(description="Что сделал фоновый пересчёт: recomputed, entered, notified, cached, digest, dispatch")


# ---------------------------------------------------------------- взаимный подбор, сравнение, что-если, ссылки руководителю


class MutualFactorOut(Doc):
    key: str = Field(description="format, location, salary, stack, tasks или readiness")
    title: str
    status: str = Field(description="ok, bad, unknown (кандидат не указал) или partial")
    text: str
    weight: float
    in_line: bool | None = Field(default=None)


class MutualFitOut(Doc):
    """Индикатор «предложение подходит кандидату» — вторая сторона подбора; в скор не входит."""

    algorithm: str
    level: str = Field(description="high, medium, low или unknown")
    title: str
    line: str = Field(description="Строка объяснения для интерфейса")
    score: float
    known_weight: float = Field(description="Доля веса факторов, по которым у кандидата есть данные")
    decline_risk: bool = Field(description="Кандидат, вероятно, откажет")
    factors: list[MutualFactorOut]


class OfferCheckOut(MutualFitOut):
    hint: str
    decline_reason: str | None = Field(None, description="FIX7 В1: почему «Вероятно, откажет» — salary | location | format; "
                                                         "null — вето нет")
    salary_status: str
    checks_left: int | None = Field(description="Сколько проверок вилки осталось за сутки; null — лимит исчерпан")


class SelectionMutualOut(Doc):
    version: int
    algorithm: str
    weights: dict[str, float]
    levels: dict[str, str]
    items: dict[str, MutualFitOut] = Field(description="Индикатор по обезличенному номеру кандидата")
    mutual_order: list[str] = Field(description="Номера кандидатов в порядке «подходит обеим сторонам»")
    counts: dict[str, int]
    feedback: dict[str, Obj] = Field(description="Отзывы работодателя по номерам кандидатов")
    reactions: dict[str, list[Obj]] = Field(description="Отметки руководителей по ссылкам")
    tasks_detected: list[str] = Field(description="Задачи, найденные в тексте потребности")
    note: str


class FeedbackOut(Doc):
    ref: str
    version: int
    verdict: str = Field(description="fit или unfit")
    verdict_title: str
    reason: str | None = Field(description="Причина «не подходит»: skill, grade, format, salary, other")
    reason_title: str | None
    comment: str | None
    updated_at: str


class ShareReactionOut(Doc):
    ref: str
    verdict: str
    verdict_title: str
    comment: str | None
    author: str | None
    updated_at: str
    share_label: str | None
    share_version: int | None


class ShareOut(Doc):
    """Ссылка для нанимающего руководителя: только чтение, без персональных данных."""

    id: str
    version: int
    label: str | None
    status: str = Field(description="active, revoked или expired")
    created_at: str
    expires_at: str
    revoked_at: str | None
    views: int
    last_viewed_at: str | None
    reactions: list[ShareReactionOut]
    token: str | None = Field(default=None, description="Токен ссылки — только в ответе на создание, потом не показывается")
    path: str | None = Field(default=None, description="Путь /share/<токен> — только в ответе на создание")


class PublicShareOut(Doc):
    company: str | None
    need_title: str
    requirements: Obj
    version: int
    created_at: str
    label: str | None
    expires_at: str
    hidden: int = Field(description="Скрыто кандидатов, которые закрыли профиль от работодателей")
    candidates: list[Obj] = Field(description="Обезличенные карточки: ref, rank, score, grade_status, card, reasons, fit")
    reactions: dict[str, ShareReactionOut]
    note: str


class CandidateWhyOut(Doc):
    need: Obj | None = Field(description="Потребность: title, category")
    place: Obj | None = Field(description="Место в подборке: version, rank, total, score")
    matched: list[Obj] = Field(description="Требования с уровнем доказанности: requirement, level, status, text")
    counts: Obj
    to_confirm: list[str] = Field(description="Обязательные навыки, которые ещё надо подтвердить")
    offer: MutualFitOut


class CandidatePrefsOut(Doc):
    preferences: Obj | None = Field(description="offers_status, interest_tags, interest_tasks, salary_signal, updated_at")
    survey_stack: list[str]
    options: Obj = Field(description="Допустимые значения: offers (готовность), tasks (задачи) — код → название")
    note: str


class CompareCandidateOut(Doc):
    ref: str
    score: float
    grade: str | None
    category: Obj | None
    status: Obj
    components: Obj = Field(description="Вклад составляющих скора (0…1): test, fsp, probe, stack_required, stack_desired; grade_status — подпись статуса")


class CompareOut(Doc):
    """Сравнение кандидатов подборки: составляющие скора и «почему выше»."""

    need: Obj
    candidates: list[CompareCandidateOut]
    rows: list[Obj] = Field(description="Строки таблицы: group, key, title, hint")
    why: list[Obj] = Field(description="Разбор пар: higher, lower, diff, summary, text, pro")
    levels: dict[str, str] = Field(description="Уровни доказательства: код (T0, T1, T2, none) → пояснение")
    weights: dict[str, float]
    selection_total: int


class WhatIfOut(Doc):
    """Что изменится в подборке, если ослабить требование."""

    cached: bool
    shown: bool = Field(description="Показывать ли блок (в большой выдаче не нужен)")
    criteria: list[str]
    strict: int = Field(description="Сколько кандидатов подходит под все требования")
    strict_apply: Obj | None = Field(description="Фильтры и требования для применения «только полностью подходящие»")
    confirmed_in_categories: int
    provisional_full: int
    threshold: int
    cuts: list[Obj] = Field(description="Что отбрасывает выдачу: key, kind, title, cut")
    options: list[Obj] = Field(description="Варианты ослабления: action, title, gain, result, apply")
    ms: float
    salary: Obj | None


# Таблица подключения: «МЕТОД /путь» → тип ответа.
TYPES: dict[str, Any] = {
    "GET /api/employer/cups": list[CupEmployerOut],
    "POST /api/employer/cups": CupEmployerOut,
    "GET /api/employer/cups/options": CupOptionsOut,
    "GET /api/employer/cups/{cup_id}": CupEmployerOut,
    "POST /api/employer/cups/{cup_id}/cancel": CupEmployerOut,
    "POST /api/employer/cups/{cup_id}/entries/{entry_id}/score": CupEmployerOut,
    "POST /api/employer/cups/{cup_id}/finish": CupEmployerOut,
    "GET /api/candidate/cups": CandidateCupsOut,
    "GET /api/candidate/cups/passport": list[CupPassportRowOut],
    "GET /api/candidate/cups/{cup_id}": CupCandidateOut,
    "POST /api/candidate/cups/{cup_id}/join": CupCandidateOut,
    "POST /api/candidate/cups/{cup_id}/leave": CupCandidateOut,
    "POST /api/candidate/cups/{cup_id}/start": CupCandidateOut,
    "POST /api/candidate/cups/{cup_id}/submit": CupCandidateOut,
    "GET /api/employer/assignments": list[AssignmentOut],
    "POST /api/employer/assignments": AssignmentOut,
    "POST /api/employer/assignments/preview": AssignmentPreviewOut,
    "GET /api/employer/assignments/{aid}": AssignmentDetailOut,
    "POST /api/employer/assignments/{aid}/attempts/{atid}/review": AssignmentDetailOut,
    "POST /api/employer/assignments/{aid}/close": AssignmentOut,
    "POST /api/employer/assignments/{aid}/send": AssignmentDetailOut,
    "GET /api/candidate/assignments": CandidateAssignmentsOut,
    "POST /api/candidate/assignments/demo/next-week": DemoNextWeekOut,
    "PUT /api/candidate/assignments/prefs": FeedScheduleOut,
    "GET /api/candidate/assignments/{atid}": AssignmentCandidateAttemptOut,
    "POST /api/candidate/assignments/{atid}/decline": AssignmentCandidateAttemptOut,
    "POST /api/candidate/assignments/{atid}/start": AssignmentCandidateAttemptOut,
    "POST /api/candidate/assignments/{atid}/submit": AssignmentCandidateAttemptOut,
    "GET /api/employer/invitations/{inv_id}/hiring": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/interviews": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/interviews/{iid}/cancel": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/interviews/{iid}/done": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/offer": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/offer/counter/accept": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/offer/counter/decline": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/offer/withdraw": HiringEmployerStateOut,
    "POST /api/employer/invitations/{inv_id}/outcome": HiringEmployerStateOut,
    "GET /api/candidate/invitations/{inv_id}/hiring": HiringCandidateStateOut,
    "POST /api/candidate/invitations/{inv_id}/interviews/{iid}/choose": HiringCandidateStateOut,
    "POST /api/candidate/invitations/{inv_id}/interviews/{iid}/reschedule": HiringCandidateStateOut,
    "POST /api/candidate/invitations/{inv_id}/offer/accept": HiringCandidateStateOut,
    "POST /api/candidate/invitations/{inv_id}/offer/counter": HiringCandidateStateOut,
    "POST /api/candidate/invitations/{inv_id}/offer/decline": HiringCandidateStateOut,
    "GET /api/hiring/todo": HiringTodoOut,
    "GET /api/employer/needs/{need_id}/subscription": SubscriptionOut,
    "PUT /api/employer/needs/{need_id}/subscription": SubscriptionOut,
    "POST /api/employer/needs/{need_id}/subscription/check": SubscriptionOut,
    "POST /api/employer/needs/{need_id}/subscription/new-version": SubscriptionNewVersionOut,
    "POST /api/employer/needs/{need_id}/subscription/seen": SubscriptionOut,
    "GET /api/employer/subscriptions": SubscriptionsOut,
    "POST /api/jury/subs/fast-forward": SubsFastForwardOut,
    "POST /api/jury/subs/simulate": SubsSimulateOut,
    "POST /api/employer/mutual/offer-check": OfferCheckOut,
    "GET /api/employer/needs/{need_id}/selections/{version}/mutual": SelectionMutualOut,
    "PUT /api/employer/needs/{need_id}/feedback": FeedbackOut,
    "GET /api/employer/needs/{need_id}/shares": list[ShareOut],
    "POST /api/employer/needs/{need_id}/shares": ShareOut,
    "POST /api/employer/needs/{need_id}/shares/{share_id}/revoke": ShareOut,
    "GET /api/share/{token}": PublicShareOut,
    "POST /api/share/{token}/reactions": ShareReactionOut,
    "GET /api/candidate/invitations/{inv_id}/why": CandidateWhyOut,
    "GET /api/candidate/preferences": CandidatePrefsOut,
    "PUT /api/candidate/preferences": CandidatePrefsOut,
    "GET /api/employer/needs/{need_id}/compare": CompareOut,
    "GET /api/employer/needs/{need_id}/selections/{version}/what-if": WhatIfOut,
    "POST /api/employer/needs/{need_id}/selections/{version}/refine": SelectionOut,
}
