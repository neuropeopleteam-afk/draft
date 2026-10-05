"""Перечисления предметной области (общие для модулей)."""
from enum import StrEnum


class UserRole(StrEnum):
    candidate = "candidate"
    employer = "employer"
    admin = "admin"
    expert = "expert"  # проверка развёрнутых ответов по рубрике (/api/expert/*); не admin


class VerificationPurpose(StrEnum):
    email_confirm = "email_confirm"
    password_reset = "password_reset"


class ConsentKind(StrEnum):
    processing = "processing"  # обработка ПДн (152-ФЗ)
    publication = "publication"  # показ обезличенного профиля работодателям


class EvidenceLevel(StrEnum):
    """Уровень доказанности факта о кандидате."""

    T0 = "T0"  # самоописание (анкета, резюме)
    T1 = "T1"  # подтверждено тестом или зондом на платформе
    T2 = "T2"  # подтверждено реестром (ФСП)


class FactSource(StrEnum):
    self_report = "self_report"
    resume = "resume"
    test = "test"
    probe = "probe"
    fsp_registry = "fsp_registry"


class BankDirection(StrEnum):
    common = "common"
    backend = "backend"
    frontend = "frontend"
    data_ml = "data_ml"
    qa = "qa"
    security = "security"


class TaskFormat(StrEnum):
    find_bug = "find_bug"
    predict_output = "predict_output"
    choose_fix = "choose_fix"
    open_book_3step = "open_book_3step"
    mcq_concept = "mcq_concept"
    open_answer = "open_answer"


class TestSessionStatus(StrEnum):
    created = "created"
    in_progress = "in_progress"
    finished = "finished"
    expired = "expired"
    aborted = "aborted"


class GradeChangeReason(StrEnum):
    initial = "initial"
    retest_up = "retest_up"
    retest_down = "retest_down"
    sandbox = "sandbox"
    admin = "admin"


class WorkFormat(StrEnum):
    office = "office"
    hybrid = "hybrid"
    remote = "remote"
    any = "any"


class NeedStatus(StrEnum):
    draft = "draft"
    active = "active"
    closed = "closed"


class ProbeStatus(StrEnum):
    sent = "sent"
    viewed = "viewed"
    submitted = "submitted"
    reviewed = "reviewed"
    declined = "declined"
    expired = "expired"


class InvitationStatus(StrEnum):
    sent = "sent"
    viewed = "viewed"
    accepted = "accepted"
    declined = "declined"
    withdrawn = "withdrawn"
    expired = "expired"


class FspLinkSource(StrEnum):
    demo = "demo"  # демо-данные хакатона (реестр ФСП недоступен)
    keycloak = "keycloak"  # вход через ФСП ID (OIDC)
    registry = "registry"  # синхронизация с реестром ФСП


class FspEventLevel(StrEnum):
    school = "school"
    regional = "regional"
    interregional = "interregional"
    national = "national"
    international = "international"
