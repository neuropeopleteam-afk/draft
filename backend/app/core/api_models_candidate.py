"""Модели ответов для OpenAPI (Я3), часть «кабинет кандидата и вспомогательные модули»: мои данные и согласия, резюме, камера (прокторинг),
исследование удобства, обратная связь после теста, двухфакторный вход, переписка, встречные предложения по приглашениям.

ТОЛЬКО ДОКУМЕНТАЦИЯ: в декораторах нет `response_model`, поведение API не меняется (см. app/core/api_models.py). Формы взяты из
кода обработчиков и сервисов (mydata/router.py, proctor/service.py `session_view`, study/service.py, auth/twofa*.py) и сверены
с реальными ответами (tests/test_openapi_models.py). Таблица подключения — `TYPES` в конце файла.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.api_models import (ApplicationOut, AssessmentResultOut, CandidateInvitationOut, EmployerInvitationOut,
                                 ProbeOut, ThreadOut)
from app.core.api_models_base import Doc, Obj

# ---------------------------------------------------------------- согласия, мои данные, профиль


class ConsentChangedOut(Doc):
    kind: str = Field(description="Вид согласия: personal_data, employer_visibility, camera, …")
    granted: bool
    version: str | None = Field(default=None, description="Версия текста, на которую дано согласие (при выдаче)")


class LegalOperatorOut(Doc):
    full_name: str
    short_name: str
    inn: str
    kpp: str
    ogrn: str
    legal_address: str
    actual_address: str
    email: str
    director: str
    storage: str


class LegalConsentTextOut(Doc):
    """Текст согласия в действующей версии и сведения об операторе."""

    kind: str
    version: str
    title: str
    text: str
    operator: LegalOperatorOut


class ContactsRevokeOut(Doc):
    revoked: int = Field(description="Сколько приглашений, по которым были открыты контакты, закрыто")
    contacts_open_to: list[Obj] = Field(description="Кому контакты остались открытыми (после отзыва — пусто)")


class DeletePreviewOut(Doc):
    """Что будет удалено, что обезличено и что платформа сделать не в силах — до подтверждения удаления."""

    deleted: dict[str, int] = Field(description="Что удаляется: название группы данных → число записей")
    anonymized: dict[str, int] = Field(description="Что остаётся без ваших данных (у работодателей): группа → число записей")
    contacts_open_to: list[Obj]
    confirm: Obj = Field(description="Что нужно для подтверждения: phrase, needs_password, needs_email, needs_code")
    not_in_our_power: list[str] = Field(description="Что платформа удалить не может (копии у работодателей, резервные копии)")
    backups: str


class DeleteResultOut(Doc):
    ok: bool
    deleted: dict[str, int]
    anonymized: dict[str, int]
    not_in_our_power: list[str]
    backups: str


class MyDataExportOut(Doc):
    """Выгрузка всех данных о пользователе (право на доступ к данным) — машиночитаемый JSON."""

    format: str
    generated_at: str
    about: Obj = Field(description="Что это за выгрузка: operator, what_is_here, not_included, consent_document_version")
    account: Obj = Field(description="Учётная запись: email, created_at, last_login_at, demo_account, вход через ФСП ID")
    profile: Obj = Field(description="Профиль: ФИО, телефон, город, опыт, мессенджер")
    consents: list[Obj]
    specializations: list[Obj]
    facts: list[Obj] = Field(description="Факты профиля с уровнем доказательства: key, title, value, source, evidence_level")
    survey: list[Obj]
    resumes: list[Obj] = Field(description="Резюме: текст без ФИО и контактов, извлечённые поля")
    tests: Obj = Field(description="Попытки теста и история грейда")
    camera: Obj = Field(description="События камеры — без кадров")


class InterestDayOut(Doc):
    date: str
    views: int
    selections: int


class InterestPeriodOut(Doc):
    employers_viewed: int
    selections: int
    probes: int


class MyInterestOut(Doc):
    """Интерес работодателей к вам за период: сколько компаний смотрели карточку, сколько раз попали в подборки."""

    period_days: int
    employers_viewed: int
    selections: int
    probes: int
    best_rank: int | None
    previous: InterestPeriodOut = Field(description="То же за предыдущий период")
    by_day: list[InterestDayOut]
    visible_to_employers: bool
    has_category: bool
    note: str
    demo: bool


class FspRatingOut(Doc):
    version: str
    strength: float = Field(description="Сила паспорта ФСП, 0…1")
    competitions: int
    best_result: str | None
    policy: str
    as_of: str | None


class FspStateOut(Doc):
    """Связка с ФСП: заявленный номер, достижения из реестра (T2) и рейтинг."""

    fsp_id_claimed: str | None
    linked: bool
    link_source: str | None = Field(description="Как связано: fsp_id (вход), manual (номер вручную), registry")
    achievements: list[Obj] = Field(description="Достижения: дисциплина, место, дата, разряд, подтверждено ли реестром")
    rating: FspRatingOut | None
    sport_rank: str | None
    synced_at: str | None
    registry: Obj | None = Field(description="Результат последней сверки с реестром")
    registry_warning: str | None
    identity_linked: bool = Field(description="Учётная запись связана с ФСП ID")
    registry_sync_available: bool
    keycloak_ready: bool
    note: str


class FspLinkOut(Doc):
    fsp_id_claimed: str
    status: str = Field(description="Результат привязки: linked, pending, …")
    message: str


class JuryModeOut(Doc):
    jury_mode: bool
    sandbox_starts: Obj = Field(description="Лимит запусков песочницы: limit, used, left, next_at")


class PrivacyOut(Doc):
    privacy: dict[str, bool] = Field(description="Что показывать работодателю: show_city, show_experience, show_work_format, show_roles, show_stack, show_soft_skills, show_fsp, show_attempts")


class ResumeUploadOut(Doc):
    """Результат загрузки резюме: текст без персональных данных, извлечённые поля, найденные персональные данные — только здесь."""

    id: str
    filename: str
    pages: int
    method: str = Field(description="Как извлечён текст: text-layer, docx, ocr")
    pii_summary: Obj
    pii_found: Obj = Field(description="Найденные ФИО, почта, телефон, мессенджер — только в этом ответе, в базе не сохраняются")
    extracted: Obj
    text_preview: str
    evidence_level: str
    kind: str


class ResumeAppliedOut(Doc):
    applied: bool


# ---------------------------------------------------------------- двухфакторный вход


class TwoFactorCheckOut(Doc):
    ok: bool
    method: str = Field(description="totp или recovery — чем подтверждено")


class TwoFactorDisabledOut(Doc):
    ok: bool
    enabled: bool


class TwoFactorUsersOut(Doc):
    items: list[Obj] = Field(description="Пользователи с подключённым или начатым вторым фактором")
    required_roles: list[str] = Field(description="Роли, для которых второй фактор обязателен")


class TwoFactorResetOut(Doc):
    ok: bool
    email: str
    role: str
    required: bool = Field(description="Следующий вход потребует подключить приложение заново")
    sessions_revoked: bool


# ---------------------------------------------------------------- камера (прокторинг)


class ProctorConsentTextOut(Doc):
    kind: str
    version: str
    title: str
    what: list[str]
    stored: list[str]
    how_long: str
    who_sees: list[str]
    effect: str
    revoke: str
    operator: str


class ProctorConsentOut(Doc):
    enabled: bool = Field(description="Контроль по камере включён на платформе")
    active: bool = Field(description="Согласие на камеру действует")
    version: str | None
    current_version: str
    granted_at: str | None
    text: ProctorConsentTextOut


class ProctorConsentRevokedOut(Doc):
    granted: bool
    kind: str
    stopped_sessions: int = Field(description="Сколько идущих тестов остановили наблюдение")


class ProctorSessionOut(Doc):
    """Наблюдение по камере в одном тесте: режим, окна наблюдения, события, итог. Кадры не сохраняются."""

    session_id: str
    status: str
    mode: str | None = Field(description="camera, declined, denied, unsupported или null — без камеры")
    camera_active: bool
    windows: list[Obj] = Field(description="Окна наблюдения: from, to, mid")
    resumes: int = Field(description="Сколько раз наблюдение возобновлялось")
    consent_version: str | None
    summary: Obj = Field(description="Итог, как его видит работодатель: mode, title, remarks, notes, points, totals")
    events: list[Obj] | None = Field(default=None, description="Свои события (только в карточке сеанса): position, kind, title, duration_s, faces, counted, at")
    items: list[Obj] | None = Field(default=None, description="Наблюдение по заданиям: position, observed_s, time_s, no_face_s, multi_face_s, off_s")


class ProctorMySessionOut(Doc):
    session_id: str
    direction: str
    claimed_grade: str
    status: str
    started_at: str | None
    mode: str | None
    events: int
    summary: Obj


class ProctorEventsOut(Doc):
    accepted: int
    events_total: int
    dropped: int


class ProctorStatsOut(Doc):
    """Обезличенный агрегат по камере для кабинета ФСП; группы меньше порога скрыты."""

    enabled: bool
    k_min: int
    period_days: int | None
    tests_finished: int
    camera_share: float
    camera_with_remarks: int
    camera_remarks_share: float
    observed_min_median: float | None
    modes: dict[str, int]
    remark_kinds: dict[str, int]
    without_record: int
    note: str


# ---------------------------------------------------------------- исследование удобства


class StudyStepOut(Doc):
    key: str
    title: str
    link: str
    done: bool
    skipped: bool
    at: str | None


class StudyStateOut(Doc):
    """Участие в исследовании удобства: новый, участник (on), отказавшийся (declined) или исключённый."""

    state: str = Field(description="new, on, declined или excluded")
    reason: str | None = Field(default=None, description="Почему исключён (automation, …)")
    role: str | None = Field(default=None)
    steps: list[StudyStepOut] | None = Field(default=None, description="Шаги сценария проверки")
    current: str | None = Field(default=None)
    path_done: bool | None = Field(default=None)
    answered: bool | None = Field(default=None)
    prompt: bool | None = Field(default=None, description="Предложить анкету сейчас (один раз)")
    survey_url: str | None = Field(default=None)


class StudySummaryOut(Doc):
    shown: bool = Field(description="Достаточно ответов, чтобы показывать сводку публично")
    min_n: int


class StudySurveyFormOut(Doc):
    role: str
    path_done: bool
    exposed: bool
    sus: Obj = Field(description="Вопросы SUS: items, scale")
    rel: Obj = Field(description="Оценка релевантности подборки: scale, threshold, selection")
    belief: Obj | None
    grade_fit: Obj | None
    tags: list[Obj] = Field(description="Что мешало: перечень меток")
    text_max: int
    answers: Obj | None = Field(description="Ранее данные ответы, если были")


class StudySubmitOut(Doc):
    ok: bool
    sus_score: float | None
    path_done: bool


class StudyOkOut(Doc):
    ok: bool


class StudyAdminReportOut(Doc):
    generated_at: str
    declined: int
    participants: list[Obj] = Field(description="Участники: роль, шаги сценария, ответы без привязки к личности")
    public: StudySummaryOut


# ---------------------------------------------------------------- обратная связь после теста, разбор потребности, переписка


class GradeHintOut(Doc):
    """Подсказка грейда по резюме и опросу — только совет, решает кандидат."""

    suggested: str | None
    confidence: str
    has_resume: bool
    method: str
    summary: str
    note: str
    signals: list[Obj] = Field(description="Сигналы: источник, грейд, пояснение")
    votes: dict[str, float | int]


class AssessmentFeedbackOut(Doc):
    """Обратная связь после теста: карта навыков, спрос работодателей, маршрут роста, дисциплины ФСП."""

    available: bool
    source: str | None
    session: Obj | None = Field(description="Тест, по которому построена обратная связь")
    skill_map: Obj = Field(description="Карта навыков по темам банка: summary, topics (без заданий и ключей)")
    demand: Obj = Field(description="Разрыв с требованиями активных потребностей и вакансий в категории")
    route: list[Obj] = Field(description="Маршрут роста: что подтвердить дальше")
    competitions: list[Obj] = Field(description="Рекомендованные дисциплины ФСП")
    fsp_calendar_url: str | None
    market_hh: Obj | None = Field(None, description="Я12б, при HH_ENABLED: «Что сейчас просит рынок» — частые навыки "
                                                     "категории по вакансиям hh.ru (агрегат, n, дата), статус каждого у "
                                                     "кандидата и ссылка на тест или короткое задание")


class EmployerAttemptsOut(Doc):
    """История попыток кандидата для работодателя — только если кандидат открыл её в приватности."""

    available: bool
    direction: str | None
    direction_title: str | None
    n_attempts: int | None = Field(default=None)
    attempts: list[Obj] | None = Field(default=None, description="Попытки: заявленный грейд, режим, время, точность оценки")
    comparison: Obj | None = Field(default=None, description="Сравнение первой и последней попытки: delta, changes, overlap")


class ParseJobOut(Doc):
    """Состояние фонового разбора потребности: словарный разбор готов сразу, языковая модель дополняет позже."""

    status: str = Field(description="pending, done или failed")
    llm: Obj = Field(description="Что сделала модель: used, reason, attempts")
    delta: list[Obj] = Field(description="Что модель изменила поверх словарного разбора")
    result: Obj | None = Field(default=None, description="Разбор потребности, когда задача завершена")


class MessagePostedOut(ThreadOut):
    sent: Obj = Field(description="Отправленное сообщение")


class NotificationsReadOut(Doc):
    read: int = Field(description="Сколько уведомлений отмечено прочитанными")


# Таблица подключения: «МЕТОД /путь» → тип ответа.
TYPES: dict[str, Any] = {
    "GET /api/legal/consents/{kind}": LegalConsentTextOut,
    "POST /api/me/consents/{kind}": ConsentChangedOut,
    "DELETE /api/me/consents/{kind}": ConsentChangedOut,
    "POST /api/me/data/contacts/revoke": ContactsRevokeOut,
    "GET /api/me/data/delete/preview": DeletePreviewOut,
    "POST /api/me/data/delete": DeleteResultOut,
    "GET /api/me/data/export": MyDataExportOut,
    "GET /api/me/interest": MyInterestOut,
    "GET /api/me/fsp": FspStateOut,
    "POST /api/me/fsp/registry-sync": FspStateOut,
    "POST /api/me/fsp/link": FspLinkOut,
    "PUT /api/me/jury-mode": JuryModeOut,
    "PUT /api/me/privacy": PrivacyOut,
    "POST /api/me/resume": ResumeUploadOut,
    "POST /api/me/resume/{resume_id}/apply": ResumeAppliedOut,
    "POST /api/auth/2fa/check": TwoFactorCheckOut,
    "POST /api/auth/2fa/disable": TwoFactorDisabledOut,
    "GET /api/admin/2fa/users": TwoFactorUsersOut,
    "POST /api/admin/2fa/reset": TwoFactorResetOut,
    "GET /api/proctor/consent": ProctorConsentOut,
    "POST /api/proctor/consent": ConsentChangedOut,
    "DELETE /api/proctor/consent": ProctorConsentRevokedOut,
    "GET /api/proctor/me/sessions": list[ProctorMySessionOut],
    "GET /api/proctor/sessions/{session_id}": ProctorSessionOut,
    "POST /api/proctor/sessions/{session_id}/start": ProctorSessionOut,
    "POST /api/proctor/sessions/{session_id}/stop": ProctorSessionOut,
    "POST /api/proctor/sessions/{session_id}/events": ProctorEventsOut,
    "GET /api/proctor/stats": ProctorStatsOut,
    "GET /api/study/me": StudyStateOut,
    "POST /api/study/enroll": StudyStateOut,
    "POST /api/study/decline": StudyStateOut,
    "GET /api/study/summary": StudySummaryOut,
    "GET /api/study/survey": StudySurveyFormOut,
    "POST /api/study/survey": StudySubmitOut,
    "POST /api/study/survey/shown": StudyOkOut,
    "GET /api/study/admin/report": StudyAdminReportOut,
    "GET /api/assessment/grade-hint": GradeHintOut,
    "GET /api/assessment/feedback": AssessmentFeedbackOut,
    "POST /api/assessment/sessions/{session_id}/accept-lower": AssessmentResultOut,
    "GET /api/employer/candidates/{ref}/attempts": EmployerAttemptsOut,
    "GET /api/employer/needs/parse/{job_id}": ParseJobOut,
    "POST /api/messages/{kind}/{tid}": MessagePostedOut,
    "POST /api/notifications/read": NotificationsReadOut,
    "POST /api/vacancies/{vid}/apply": ApplicationOut,
    "POST /api/candidate/probes/{probe_id}/decline": ProbeOut,
    "POST /api/candidate/invitations/{inv_id}/decline": CandidateInvitationOut,
    "POST /api/candidate/invitations/{inv_id}/counter": CandidateInvitationOut,
    "POST /api/candidate/invitations/{inv_id}/contacts/restore": CandidateInvitationOut,
    "POST /api/employer/invitations/{inv_id}/withdraw": EmployerInvitationOut,
    "POST /api/employer/invitations/{inv_id}/counter/accept": EmployerInvitationOut,
    "POST /api/employer/invitations/{inv_id}/counter/decline": EmployerInvitationOut,
}
