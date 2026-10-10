"""Модели ответов для документации OpenAPI (Я3): описание формы ответов ключевых методов, где обработчик возвращает dict.

ТОЛЬКО ДОКУМЕНТАЦИЯ. Модели не используются при выполнении запросов (в декораторах нет `response_model`), поведение API
не меняется. Подключение — таблица `RESPONSE_TYPES` ниже: «МЕТОД /путь» → тип; `api_docs.enrich` подставляет схему в успешный
ответ операции. Так модели лежат в одном месте и не создают конфликтов в роутерах.

Правила: поле обязательно, если оно есть в каждом ответе (значение может быть null — тогда `| None`); вложенные блоки, которые
меняются от сценария к сценарию (доказательства, разбор требований, карточки в выдаче), описаны как `dict` — их полный
состав смотрите в примере ответа. `extra="allow"`: перечень полей не исчерпывающий, клиент не должен падать на новых.
Соответствие моделей реальным ответам проверяет tests/test_openapi_models.py (типы полей — по примерам из api_examples.json).
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.api_models_base import Doc, Obj


# ---------------------------------------------------------------- система

class OperatorOut(Doc):
    full_name: str = Field(description="Полное наименование оператора персональных данных")
    short_name: str
    inn: str
    kpp: str
    ogrn: str
    legal_address: str
    actual_address: str
    email: str = Field(description="Почта для обращений по персональным данным")
    director: str
    storage: str = Field(description="Где хранятся данные (юрисдикция, площадка)")


class MetaOut(Doc):
    """Сведения о платформе: версия, оператор данных, режимы стенда и правила, общие для интерфейса."""

    product_name: str = Field(description="Название продукта")
    version: str = Field(description="Версия сборки")
    operator: OperatorOut
    jury_mode_available: bool = Field(description="Включён ли режим жюри (песочницы с демо-ролями)")
    demo_sandbox: bool = Field(description="Работает ли стенд на демо-данных")
    proctor_camera: bool = Field(description="Доступен ли контроль честности по камере")
    llm: Obj = Field(description="Состояние языковой модели: настроена ли, цепочка провайдеров, последний вызов")
    assessment_engine: str = Field(description="Движок оценки (адаптивный тест)")
    rules: Obj = Field(description="Правила платформы в днях: grade_change_interval_days, retake_same_grade_days, "
                                   "invitation_cooldown_days")
    catalog: Obj = Field(description="Видимые направления каталога: directions — все видимые (5 базовых и направления "
                                     "расширения с проверенным банком), ext — видимые направления расширения, "
                                     "ext_enabled — включён ли CATALOG_EXT_ENABLED")


# ---------------------------------------------------------------- карточка кандидата

class GradeStatusOut(Doc):
    status: str = Field(description="confirmed — подтверждён тестом, provisional — предварительно, unconfirmed — не подтверждён")
    title: str = Field(description="Подпись статуса для интерфейса")
    tier: int = Field(description="Ярус в выдаче: 0 — подтверждён или предварительно, 1 — не подтверждён")
    grade: str | None = Field(description="Грейд: junior, middle, senior")
    grade_title: str | None
    direction: str | None
    claimed_grade: str | None = Field(description="Заявленный кандидатом грейд, если тест ещё не подтвердил")
    claimed_direction: str | None
    claimed_category_id: str | None
    claimed_title: str | None
    attempt: Any = Field(description="Сведения о последней неподтверждённой попытке, если была")
    p_pct: int | float | None = Field(description="Вероятность заявленного грейда по тесту, %")
    text: str = Field(description="Пояснение статуса человеческим языком")


class CategoryRefOut(Doc):
    id: str = Field(description="Идентификатор категории «направление.грейд», например backend.middle")
    title: str
    provisional: bool = Field(description="Категория предварительная (Junior без подтверждения)")
    preliminary: bool


class CandidateCardOut(Doc):
    """Карточка кандидата, как её видит сам кандидат: категория, подтверждённые навыки, ФСП, свежесть подтверждений."""

    ref: str = Field(description="Обезличенный идентификатор кандидата в выдаче (C-XXXXXX)")
    category: CategoryRefOut | None
    status: GradeStatusOut
    claimed: Any
    direction: str | None
    direction_title: str | None
    grade: str | None
    grade_title: str | None
    provisional: bool | None
    confirmed_by: str | None = Field(description="Чем подтверждён грейд (test, fsp, …)")
    rating_score: float | None = Field(description="Рейтинг внутри категории, 0…1")
    specializations: list[Obj] = Field(description="Все категории кандидата; одна — основная (is_primary)")
    rank_in_category: int | None
    category_size: int | None
    test: Obj | None = Field(description="Итог последнего теста: уровень, theta, se, верных ответов, честность")
    skills_confirmed: list[Obj] = Field(description="Подтверждённые навыки с уровнем доказательства T0–T2")
    probes: list[Obj] = Field(description="Зонды (задания работодателей), которые кандидат выполнил")
    fsp: Obj = Field(description="Связка с ФСП: linked, level (T2), source, strength, achievements")
    stack_declared: list[Obj] = Field(description="Заявленный стек (уровень T0)")
    roles: list[str]
    soft_skills: list[str]
    experience_years: float | None
    work_format: str | None = Field(description="office, hybrid, remote, any")
    city: str | None
    relocation: bool | None
    market_range: Obj | None = Field(description="Вилка рынка по категории: from, to, median")
    is_demo: bool | None
    employment_safety: Obj = Field(description="Ограничения для несовершеннолетних: допустимые форматы, согласие родителей")
    freshness: Obj = Field(description="Свежесть подтверждений навыков: доли свежих/стареющих/устаревших")
    directions: dict[str, str] | None = Field(default=None, description="Справочник направлений: код → название (только в карточке кандидата)")


class EmployerCandidateCardOut(CandidateCardOut):
    """Карточка кандидата для работодателя: то же + возможность пригласить и история контактов с этим кандидатом."""

    can_invite: bool
    invite_available_at: str | None = Field(description="Когда можно пригласить снова (пауза между приглашениями)")
    invitation_cooldown_days: int
    my_invitations: list[Obj] = Field(description="Приглашения этой компании этому кандидату")
    my_probes: list[Obj] = Field(description="Зонды этой компании этому кандидату")
    contacts: Obj | None = Field(description="Контакты — только после принятия приглашения, иначе null")
    contacts_note: str
    contacts_revoked: bool


class CandidateSearchOut(Doc):
    """Поиск кандидатов в общем пуле: карточки и счётчики по статусу подтверждения."""

    total: int
    items: list[Obj] = Field(description="Короткие карточки кандидатов (как в выдаче подбора)")
    provisional: int
    unconfirmed: int
    confirmed: int


# ---------------------------------------------------------------- оценка (тест)

class AssessmentStatusOut(Doc):
    """Состояние оценки кандидата: текущая категория, ограничения повтора, незавершённая сессия, история."""

    onboarding_completed: bool
    survey_direction: str | None
    claimed_grade: str | None
    current: Obj | None = Field(description="Текущая категория: direction, grade, category_id, rating_score, rank, market_range")
    specializations: list[Obj]
    selected_direction: str | None
    locked_until: str | None = Field(description="До какой даты закрыта смена грейда (ISO 8601)")
    lock_active: bool
    can_retest_now: bool
    jury_mode: bool
    jury_mode_available: bool
    jury_mode_allowed: bool
    sandbox_active: bool
    sandbox_starts: Obj = Field(description="Лимит запусков в режиме жюри: limit, used, left, next_at")
    grade_change_interval_days: int
    retake_same_grade_days: int
    retake_locks: Obj
    express_available: bool
    express: Obj = Field(description="Параметры экспресс-теста: min_items, max_items, by_grade")
    active_session_id: str | None
    active_grade: str | None
    active_mode: str | None
    provisional: bool | None
    grade_status: GradeStatusOut
    confirmed_by: str | None
    engine: str
    sessions: list[Obj] = Field(description="Последние сессии теста")
    grade_history: list[Obj]
    surveys: list[Obj]


class AssessmentResultOut(Doc):
    """Итог теста: оценка способности, грейд, вероятности по уровням и пояснение."""

    session_id: str
    grade: str | None = Field(description="Присвоенный грейд: junior, middle, senior (или none)")
    point_grade: str | None
    claimed_grade: str | None
    confirmed: bool = Field(description="Подтверждён ли заявленный грейд")
    provisional: bool
    changed: bool
    status_changed: bool
    grade_changed: bool
    upgrade_available: bool
    theta: float = Field(description="Оценка способности (шкала IRT)")
    se: float = Field(description="Стандартная ошибка оценки")
    probabilities: dict[str, float] = Field(description="Вероятность каждого уровня: none, intern, junior, middle, senior")
    p_claimed: float | None
    correct: int
    answered: int
    message: str
    explanation: str = Field(description="Объяснение результата человеческим языком")
    direction: str
    current_grade: str | None
    category_id: str | None
    is_primary: bool
    category_status: str | None
    category_provisional: bool
    provisional_reason: str | None
    engine: str
    mode: str = Field(description="Режим теста: full, express, …")
    locked_until: str | None
    accept_lower_available: bool
    accept_lower_grade: str | None
    accept_lower_p: float | None
    accepted_lower: bool | None
    retake_lower: Any
    retake_same_grade_days: int
    sandbox: bool
    details: Obj = Field(description="Причина остановки, число зачтённых заданий, время, ручная проверка")
    integrity: Obj = Field(description="Честность прохождения: level, title, camera, reasons")
    second_opinions: Obj = Field(description="Повторные проверки ответов: pending, revised, disputed, lost")


class AttemptsOut(Doc):
    direction: str
    direction_title: str
    attempts: list[Obj] = Field(description="Попытки теста по направлению")
    comparison: Obj | None = Field(description="Сравнение первой и второй попыток: first, second, overlap, delta, changes")
    sandbox: bool
    retake_grade: str | None
    can_retake_now: bool
    retake_reason: str | None
    note: str


# ---------------------------------------------------------------- потребности и подбор

class NeedVersionOut(Doc):
    version: int = Field(description="Номер версии подбора")
    parent_version: int | None = Field(description="От какой версии получена (уточнение, «похожие»)")
    created_at: str
    filters: Obj
    total: int = Field(description="Сколько кандидатов в версии")


class NeedRequirementsOut(Doc):
    direction: str | None
    grade: str | None
    stack_required: list[Obj] = Field(description="Обязательный стек: name, level, … (разбор текста потребности)")
    stack_desired: list[Obj]
    experience_years_min: float | None
    work_format: str | None
    work_formats: list[str] | None
    city: str | None
    salary_from: int | None
    salary_to: int | None
    salary_net: bool | None = Field(description="true — вилка на руки, false — до вычета НДФЛ")
    method: str | None = Field(default=None, description="Как разобран текст: rules (правила) или llm")
    evidence: Obj | None = Field(default=None, description="Откуда взято каждое требование: фрагмент текста, уверенность")
    review: Obj | None = None
    excluded: list[Any] | None = None
    llm: Obj | None = Field(default=None, description="Использовалась ли языковая модель и почему нет")
    unknown_terms: list[str] | None = Field(default=None, description="Термины, которые не удалось сопоставить со справочником")
    salary_note: str | None = None
    bias: list[Obj] | None = Field(default=None, description="Предупреждения о возможной дискриминации в формулировках")
    suggested_text: str | None = None


class NeedOut(Doc):
    """Потребность работодателя: исходный текст, разобранные требования и версии подбора."""

    id: str
    title: str
    raw_text: str = Field(description="Исходный текст потребности")
    requirements: NeedRequirementsOut
    status: str = Field(description="draft, active, closed")
    created_at: str
    versions: list[NeedVersionOut]


class NeedFileOut(Doc):
    text: str = Field(description="Текст, извлечённый из файла")
    filename: str
    kind: str
    kind_title: str
    pages: int | None
    chars: int


class SelectionOut(Doc):
    """Подбор кандидатов под потребность: условия, веса, категории и ранжированные результаты с причинами."""

    version: int
    parent_version: int | None
    created_at: str
    filters: Obj
    requirements: NeedRequirementsOut
    algorithm: str = Field(description="Версия алгоритма подбора, например match-v1.1")
    conditions: Obj = Field(description="Применённые условия (формат работы, город, вилка) и сколько скрыто ими")
    must_first: bool = Field(description="Обязательные требования учитываются раньше желательных")
    weights: dict[str, float] = Field(description="Веса компонентов оценки: test, stack_required, stack_desired, fsp, probe")
    levels: dict[str, str] = Field(description="Уровни доказательства: T2 — реестр ФСП, T1 — тест или зонд, T0 — заявлено")
    provisional_penalty: float
    categories: list[Obj] = Field(description="Категории в выдаче: id, title, count, relation, market_range")
    total: int
    results: list[Obj] = Field(description="Кандидаты по убыванию score: ref, rank, score, components, reasons, must, card")
    confirmed_matched: int
    provisional_matched: int
    unconfirmed_matched: int


class EmployerCategoryOut(Doc):
    id: str
    title: str
    direction: str
    grade: str
    count: int = Field(description="Кандидатов в категории")
    provisional: int
    unconfirmed: int
    market_range: Obj


# ---------------------------------------------------------------- приглашения и зонды

class InvitationOut(Doc):
    """Приглашение работодателя кандидату: условия, статус, история и контакты (после принятия)."""

    id: str
    position_title: str
    offer_description: str
    employment_terms: Obj = Field(description="format, reduced_time, employer_acknowledged")
    salary_from: int | None
    salary_to: int | None
    salary_basis: str = Field(description="gross или net")
    salary_basis_title: str
    contact_method: str
    evidence: list[Obj] = Field(description="Чем подтверждён кандидат для этой позиции (T0–T2)")
    status: str = Field(description="sent, viewed, accepted, declined, withdrawn, expired")
    decline_reason: str | None
    created_at: str
    viewed_at: str | None
    responded_at: str | None
    history: list[Obj] = Field(description="Смены статусов: at, by, status, note")
    company: Obj = Field(description="name, industry, website, city")
    complaint: Obj | None
    ats_stage: str | None
    counter: Obj | None = Field(description="Текущее встречное предложение кандидата")
    counters: list[Obj]
    counters_left: int
    contacts_revoked: bool
    contacts_revoked_at: str | None
    thread: Obj = Field(description="Переписка: total, unread")
    hiring: Obj | None = Field(description="Этап найма после принятия: stage, title, line, todo")


class EmployerInvitationOut(InvitationOut):
    candidate_ref: str
    candidate_category: str | None
    candidate_deleted: bool
    contacts: Obj | None = Field(description="Контакты кандидата — только после принятия и пока не отозваны")
    ats_transfers: list[Obj]


class CandidateInvitationOut(InvitationOut):
    below_my_minimum: bool = Field(description="Вилка ниже минимума, указанного кандидатом")


class ProbeOut(Doc):
    """Зонд — короткое задание работодателя кандидату."""

    id: str
    title: str
    task_text: str
    answer_mode: str
    salary_from: int | None
    salary_to: int | None
    time_limit_min: int | None
    status: str = Field(description="sent, viewed, submitted, reviewed, declined, expired")
    events: list[Obj]
    answer: Obj | None
    review: Obj | None
    created_at: str
    deadline_at: str | None


class ProbeCreateOut(Doc):
    created: list[Obj] = Field(description="Созданные зонды")
    skipped: list[Obj] = Field(description="Кандидаты, которым зонд не отправлен, и причина")


# ---------------------------------------------------------------- профиль и данные кандидата

class OnboardingOut(Doc):
    completed: bool
    answers: Obj = Field(description="Ответы опроса: направление, стек, опыт, формат работы, город, приватность")
    options: Obj = Field(description="Варианты ответов для формы")
    consent_publication_text: Obj = Field(description="Текст согласия на публикацию профиля и оператор")


class OnboardingSavedOut(Doc):
    saved: bool
    survey_id: str
    suggested_grade: str | None
    visible_to_employers: bool


class ConsentOut(Doc):
    kind: str = Field(description="processing, publication, contacts, …")
    version: str
    granted_at: str
    revoked_at: str | None


class ResumeOut(Doc):
    id: str
    filename: str
    pages: int | None
    method: str = Field(description="Как извлечён текст")
    pii_summary: Obj = Field(description="Сколько персональных данных найдено и обезличено")
    extracted: Obj = Field(description="Извлечённые факты: стек, роли, опыт, подсказки по направлению и грейду")
    text_preview: str
    created_at: str
    evidence_level: str
    kind: str


class MyDataOut(Doc):
    stored: list[Obj] = Field(description="Что хранится о пользователе")
    interest: Obj = Field(description="Сколько работодателей смотрели профиль, подборок, зондов")
    consents: list[Obj]
    contacts_open_to: list[Any] = Field(description="Кому открыты контакты")
    delete: Obj = Field(description="Условия удаления учётной записи")
    retention: list[Obj] = Field(description="Сроки хранения")
    backups: str
    not_in_our_power: list[str] = Field(description="Что платформа удалить не может (копии у третьих лиц)")
    operator: Obj
    consent_version: str


class PassportStateOut(Doc):
    """Цифровой паспорт навыков: действующий документ с подписью, право на выпуск и история выпусков."""

    active: Obj | None = Field(description="Действующий паспорт: passport, document, signature, status, keys, verify_url")
    eligible: bool = Field(description="Может ли пользователь выпустить паспорт")
    opted_out: bool
    history: list[Obj]


# ---------------------------------------------------------------- жюри, уведомления, кабинет ФСП

class UserBriefOut(Doc):
    id: str
    email: str
    role: str
    is_email_verified: bool
    created_at: str


class JuryLoginOut(Doc):
    """Вход жюри в демо-песочницу под выбранной ролью. Токен — обычный JWT демо-учётки."""

    access_token: str
    token_type: str = Field(description="bearer")
    expires_in: int = Field(description="Срок жизни токена, секунд")
    user: UserBriefOut
    persona: str = Field(description="candidate, employer, expert, fsp, …")
    landing: str = Field(description="Куда направить пользователя в интерфейсе")
    scenario: str | None = Field(description="Идентификатор песочницы; передайте его при входе под другой ролью в ту же песочницу")
    shared: bool
    created: bool


class JuryStatusOut(Doc):
    available: bool = Field(description="Включён ли режим жюри")
    personas: list[Obj] = Field(description="Доступные роли и сценарии")
    reset_cooldown_s: int
    sandboxes: bool


class NotificationsOut(Doc):
    items: list[Obj]
    unread: int
    prefs: Obj = Field(description="push_enabled, email_enabled, reminders_enabled")
    quiet: Obj = Field(description="Тихие часы: from, to (часы суток)")


class FspOverviewOut(Doc):
    """Обзор для кабинета ФСП. Значения в группах меньше порога k скрываются (null), чтобы нельзя было узнать отдельного человека."""

    candidates: int | None
    candidates_fsp: int | None
    fsp_share: float | None
    companies_active: int | None
    needs: int | None
    invitations: int | None
    invited_candidates: int | None
    accepted_candidates: int | None
    acceptance_rate: float | None
    answered_rate: float | None
    cups: int | None
    cup_participants: int | None
    k: int = Field(description="Порог скрытия малых групп")
    period_days: int | None
    demo_share: float | None


class ValidationHeadlineOut(Doc):
    items: list[Obj] = Field(description="Ключевые показатели валидации: название, значение, порог, статус")
    missing: bool
    how_to_read: str


# ---------------------------------------------------------------- вакансии и отклики

class VacancyOut(Doc):
    """Вакансия: условия, вилка, компания; для кандидата — ещё свой отклик и индекс доверия работодателя."""

    id: str
    title: str
    category_id: str | None = Field(description="Категория «направление.грейд», если вакансия к ней привязана")
    category_title: str | None
    description: str
    stack: list[Obj] = Field(description="Стек вакансии: технология и уровень")
    salary_from: int | None
    salary_to: int | None
    salary_basis: str = Field(description="gross или net")
    salary_basis_title: str
    work_format: str | None = Field(description="office, hybrid, remote, any")
    city: str | None
    status: str = Field(description="Статус публикации вакансии")
    published_at: str | None
    updated_at: str | None
    is_demo: bool
    source: str | None = Field(description="Источник импорта, если вакансия загружена из внешней системы")
    source_title: str | None
    external_id: str | None
    external_url: str | None
    imported_at: str | None
    edited_after_import: bool | None
    company: Obj = Field(description="Компания: name, industry, website, city")
    market_range: Obj | None = Field(description="Вилка рынка по категории: from, to, median")
    assignment: Obj | None = Field(description="Задание к вакансии, если работодатель его добавил")
    my_application: Obj | None = Field(default=None, description="Отклик текущего кандидата (только в ответах кандидату)")
    trust: Obj | None = Field(default=None, description="Индекс доверия работодателя (только в ответах кандидату)")
    applications: Obj | None = Field(default=None, description="Счётчики откликов (только в ответах работодателю)")


class VacancyListOut(Doc):
    items: list[VacancyOut]
    my_category_id: str | None = Field(description="Категория кандидата — по ней вакансии подсвечиваются как «подходящие»")


class ApplicationOut(Doc):
    """Отклик кандидата на вакансию. Работодателю дополнительно приходят карточка кандидата и контакты (после ответа)."""

    id: str
    vacancy_id: str
    vacancy_title: str
    status: str = Field(description="Машинный статус отклика, например sent")
    status_title: str = Field(description="Подпись статуса по-русски")
    events: list[Obj] = Field(description="История статусов")
    cover_letter: str | None
    created_at: str
    viewed_at: str | None
    responded_at: str | None
    salary_from: int | None
    salary_to: int | None
    salary_basis: str
    salary_basis_title: str
    thread: Obj = Field(description="Переписка: total, unread")
    ats_stage: str | None
    employer_note: str | None
    assignment: Obj | None
    company: Obj | None = Field(default=None, description="Компания (в ответах кандидату)")
    card: Obj | None = Field(default=None, description="Обезличенная карточка кандидата (в ответах работодателю)")
    contacts: Obj | None = Field(default=None, description="Контакты кандидата (в ответах работодателю, когда доступны)")


# ---------------------------------------------------------------- переписка

class ThreadBriefOut(Doc):
    kind: str = Field(description="Предмет переписки: invitation (приглашение) или application (отклик)")
    id: str
    title: str
    counterpart: str = Field(description="Собеседник (для работодателя — обезличенный кандидат)")
    status: str
    mode: str = Field(description="qa — вопросы до принятия, chat — после")
    closed: str | None
    revoked: bool = Field(description="Доступ к контактам отозван")
    messages: int
    unread: int
    last: Obj | None = Field(description="Последнее сообщение")
    activity_at: str | None


class ThreadOut(Doc):
    kind: str
    id: str
    title: str
    side: str = Field(description="Сторона текущего пользователя: candidate или employer")
    counterpart: str
    company: str
    messages: list[Obj]
    mode: str
    max_len: int = Field(description="Максимальная длина сообщения")
    can_write: bool
    reason: str | None = Field(description="Почему писать нельзя, если can_write = false")
    revoked: bool
    rules: Obj
    status: str


class UnreadOut(Doc):
    total: int
    invitations: int
    applications: int


class NotificationPrefsOut(Doc):
    push_enabled: bool
    email_enabled: bool
    reminders_enabled: bool


# Таблица подключения: «МЕТОД /путь» → тип ответа (успешный код определяется по операции).
RESPONSE_TYPES: dict[str, Any] = {
    "GET /api/meta": MetaOut,
    "GET /api/me/card": CandidateCardOut,
    "GET /api/employer/candidates/{ref}": EmployerCandidateCardOut,
    "GET /api/employer/candidates": CandidateSearchOut,
    "GET /api/assessment/status": AssessmentStatusOut,
    "POST /api/assessment/sessions/{session_id}/finish": AssessmentResultOut,
    "GET /api/assessment/sessions/{session_id}/result": AssessmentResultOut,
    "GET /api/assessment/attempts": AttemptsOut,
    "GET /api/employer/needs": list[NeedOut],
    "POST /api/employer/needs": NeedOut,
    "GET /api/employer/needs/{need_id}": NeedOut,
    "PATCH /api/employer/needs/{need_id}": NeedOut,
    "POST /api/employer/needs/parse": NeedRequirementsOut,
    "POST /api/employer/needs/file": NeedFileOut,
    "POST /api/employer/needs/{need_id}/selections": SelectionOut,
    "GET /api/employer/needs/{need_id}/selections/{version}": SelectionOut,
    "POST /api/employer/needs/{need_id}/selections/{version}/similar": SelectionOut,
    "GET /api/employer/categories": list[EmployerCategoryOut],
    "POST /api/employer/invitations": EmployerInvitationOut,
    "GET /api/employer/invitations": list[EmployerInvitationOut],
    "GET /api/candidate/invitations": list[CandidateInvitationOut],
    "GET /api/candidate/invitations/{inv_id}": CandidateInvitationOut,
    "POST /api/candidate/invitations/{inv_id}/accept": CandidateInvitationOut,
    "POST /api/candidate/invitations/{inv_id}/complaint": CandidateInvitationOut,
    "POST /api/candidate/invitations/{inv_id}/contacts/revoke": CandidateInvitationOut,
    "POST /api/employer/probes": ProbeCreateOut,
    "GET /api/employer/probes": list[ProbeOut],
    "GET /api/candidate/probes": list[ProbeOut],
    "GET /api/candidate/probes/{probe_id}": ProbeOut,
    "POST /api/candidate/probes/{probe_id}/answer": ProbeOut,
    "POST /api/employer/probes/{probe_id}/review": ProbeOut,
    "GET /api/me/onboarding": OnboardingOut,
    "PUT /api/me/onboarding": OnboardingSavedOut,
    "GET /api/me/consents": list[ConsentOut],
    "GET /api/me/resume": ResumeOut,
    "GET /api/me/data": MyDataOut,
    "GET /api/me/passport": PassportStateOut,
    "POST /api/me/passport/reissue": PassportStateOut,
    "POST /api/me/passport/revoke": PassportStateOut,
    "POST /api/jury/login": JuryLoginOut,
    "GET /api/jury/status": JuryStatusOut,
    "GET /api/notifications": NotificationsOut,
    "GET /api/fsp-cabinet/overview": FspOverviewOut,
    "GET /api/validation/headline": ValidationHeadlineOut,
    "GET /api/vacancies": VacancyListOut,
    "GET /api/vacancies/{vid}": VacancyOut,
    "GET /api/employer/vacancies": list[VacancyOut],
    "POST /api/employer/vacancies": VacancyOut,
    "PATCH /api/employer/vacancies/{vid}": VacancyOut,
    "POST /api/employer/vacancies/{vid}/close": VacancyOut,
    "POST /api/employer/vacancies/{vid}/publish": VacancyOut,
    "GET /api/candidate/applications": list[ApplicationOut],
    "POST /api/candidate/applications/{app_id}/withdraw": ApplicationOut,
    "GET /api/employer/vacancies/{vid}/applications": list[ApplicationOut],
    "POST /api/employer/applications/{app_id}/status": ApplicationOut,
    "POST /api/employer/applications/{app_id}/view": ApplicationOut,
    "GET /api/messages/threads": list[ThreadBriefOut],
    "GET /api/messages/{kind}/{tid}": ThreadOut,
    "GET /api/messages/unread": UnreadOut,
    "GET /api/notifications/prefs": NotificationPrefsOut,
    "PUT /api/notifications/prefs": NotificationPrefsOut,
}


# Модули с остальными моделями: у каждого своя таблица TYPES того же вида.
MODULES = ("api_models_work", "api_models_integrations", "api_models_candidate", "api_models_platform")


def all_types() -> dict[str, Any]:
    """Одна таблица «МЕТОД /путь» → тип ответа: RESPONSE_TYPES (ключевые методы) и TYPES модулей api_models_*.py."""
    import importlib

    out = dict(RESPONSE_TYPES)
    for name in MODULES:
        extra = importlib.import_module(f"app.core.{name}").TYPES
        dup = sorted(set(out) & set(extra))
        if dup:
            raise RuntimeError(f"операция описана в двух таблицах моделей: {dup}")
        out.update(extra)
    return out
