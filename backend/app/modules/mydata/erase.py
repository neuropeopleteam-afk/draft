"""Удаление учётной записи кандидата (152-ФЗ): что стирается сразу, что обезличивается и почему.

Принцип: личность стирается полностью и сразу, а записи, которые ведёт работодатель, остаются без привязки к человеку.

**Стирается сразу** (строки удаляются из БД, без «мягкого» удаления): профиль и контакты, скрытый минимум зарплаты,
опрос, факты и навыки, резюме, все попытки теста и ответы, события камеры, согласия, паспорт ФСП и достижения,
записи в кубках, ответы на задания, подписки на push, второй фактор и коды входа, события интереса, связи с ATS,
вся переписка по приглашениям и откликам (в ней могут быть имя и контакты, которые написал работодатель).
Состав определяется по схеме БД: любая таблица, связанная с учётной записью каскадом, удаляется, даже если её
добавили позже (``owned_tables``), — удаление не зависит от ручного списка.

**Обезличивается** (строки остаются, привязка к человеку и его тексты стираются):

* приглашения, зонды, отклики на вакансии, встречные предложения и жалобы — это записи работодателя о том, что он
  предлагал и в каких условиях; от них зависят его история, правило «одно приглашение за 30 дней» и индекс доверия
  компании. Стираются тексты кандидата: ответ на зонд, причина отказа, сопроводительное письмо, комментарии,
  приложенные факты о кандидате;
* профиль-«надгробие»: остаётся строка с обезличенным ``public_ref`` (C-XXXXXX) и меткой ``deleted_at`` — без имени,
  контактов, категории и настроек. На него ссылаются записи работодателя; имя и почта восстановить по нему нельзя;
* учётная запись: почта заменяется на ``deleted-…@deleted.invalid``, пароль и ФСП ID удаляются, вход невозможен,
  выданные токены отозваны; прежняя почта освобождается для новой регистрации;
* подписанный паспорт грейда остаётся в реестре как отозванный («учётная запись удалена»): кто его получил, сможет
  проверить, что он больше не действует; ссылка на учётную запись обнуляется;
* обезличенные снимки подборок у работодателей (``selection_versions``): без имени и контактов; связь ref → человек
  уничтожена вместе с профилем;
* отзыв опроса удобства (SUS): оценка остаётся без привязки, свободный комментарий стирается.

**Не в нашей власти**: данные, которые работодатель уже получил после того, как вы приняли приглашение (контакты) —
они у него по вашему согласию; копии в его ATS; резервные копии БД перезаписываются по кругу (срок — в docs/MY_DATA.md).

В журнал уничтожения (``account_deletion_log``) пишутся дата, роль и число записей по категориям — без идентификаторов.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import secrets
import uuid

from sqlalchemy import Table, and_, delete, false, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import utcnow
from app.core.enums import UserRole, WorkFormat
from app.core.errors import api_error
from app.core.security import hash_password, verify_password
from app.models import metadata
from app.modules.auth.models import User
from app.modules.mydata.models import AccountDeletionLog
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger("mydata.erase")

# Не удаляются построчно: учётка и профиль превращаются в обезличенную запись; профиль работодателя — не кандидата.
SPECIAL = {"users", "candidate_profiles", "employer_profiles"}
# Двусторонние записи работодателя — обезличиваются (тексты кандидата стираются), строки остаются.
KEEP = {"probes", "invitations", "invitation_complaints", "invitation_counters", "vacancy_applications",
        "invitation_events"}
# Таблицы, которые чистятся отдельными правилами ниже (SET NULL / переписка)
HANDLED = {"contact_messages", "grade_passports", "sus_responses"}

# Понятные названия категорий для кандидата (по таблицам); остальное — «Прочие данные учётной записи»
LABELS: dict[str, str] = {
    "candidate_facts": "Факты и навыки профиля",
    "candidate_specializations": "Специализации и категории",
    "candidate_resumes": "Резюме (текст без ФИО и контактов)",
    "survey_responses": "Ответы опроса", "survey_stack_tags": "Ответы опроса",
    "test_sessions": "Попытки теста", "test_session_items": "Задания, выданные в попытках теста", "test_answers": "Ответы на задания теста",
    "grade_history": "История грейда",
    "proctor_sessions": "События камеры (без кадров)", "proctor_events": "События камеры (без кадров)",
    "consents": "Согласия",
    "email_verifications": "Коды подтверждения почты",
    "user_two_factor": "Второй фактор входа", "user_two_factor_recovery_codes": "Второй фактор входа",
    "fsp_passports": "Паспорт ФСП и достижения", "fsp_achievements": "Паспорт ФСП и достижения",
    "push_subscriptions": "Подписки на уведомления",
    "oidc_login_states": "Служебные записи входа через ФСП ID",
    "cup_entries": "Участие в кубках работодателей",
    "assignment_attempts": "Решения заданий работодателей",
    "ats_links": "Связи с ATS работодателей", "ats_deliveries": "Журнал передачи в ATS",
    "ats_stage_events": "Журнал этапов из ATS",
    "candidate_interest_events": "События интереса (просмотры и подборки)",
    "jury_live_guests": "Гостевой вход живой демонстрации",
    "contact_messages": "Переписка по приглашениям и откликам",
}
OTHER_LABEL = "Прочие данные учётной записи"


# ------------------------------------------------------------------ состав по схеме БД

def _roots(t: Table, uid: uuid.UUID):
    conds = []
    for fk in t.foreign_keys:
        ref = fk.column
        if fk.ondelete == "CASCADE" and ref.table.name in ("users", "candidate_profiles") and ref.name in ("id", "user_id"):
            conds.append(t.c[fk.parent.name] == uid)
    return conds


def owned_tables(uid: uuid.UUID) -> dict[str, tuple[Table, object]]:
    """Таблицы с данными учётной записи кандидата и условие выбора строк. Корень — внешний ключ на users/candidate_profiles
    с каскадным удалением; затем — все таблицы, связанные каскадом с уже найденными (ответы → попытки → пользователь).
    Двусторонние записи (KEEP), учётка и профиль в состав не входят."""
    tables = {t.name: t for t in metadata.sorted_tables}
    memo: dict[str, object | None] = {}

    def cond(name: str):
        if name in memo:
            return memo[name]
        memo[name] = None  # защита от циклов
        t = tables[name]
        parts = [] if name in SPECIAL or name in KEEP or name in HANDLED else _roots(t, uid)
        if name not in SPECIAL and name not in KEEP and name not in HANDLED:
            for fk in t.foreign_keys:
                ref = fk.column
                pname = ref.table.name
                if fk.ondelete == "CASCADE" and pname not in ("users", "candidate_profiles") and pname not in SPECIAL \
                        and pname != name and len(ref.table.primary_key.columns) == 1:
                    pc = cond(pname)
                    if pc is not None:
                        parts.append(t.c[fk.parent.name].in_(select(ref).where(pc)))
        memo[name] = or_(*parts) if parts else None
        return memo[name]

    out: dict[str, tuple[Table, object]] = {}
    for t in metadata.sorted_tables:
        c = cond(t.name)
        if c is not None:
            out[t.name] = (t, c)
    return out


def _label(table: str) -> str:
    return LABELS.get(table, OTHER_LABEL)


def _group(counts: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for table, n in counts.items():
        if n:
            # таблицы-приложения (items, events, tags) входят в категорию родителя — число строк верхнего уровня
            key = _label(table)
            out[key] = max(out.get(key, 0), n) if key != OTHER_LABEL else out.get(key, 0) + n
    return out


# ------------------------------------------------------------------ предпросмотр

def _bilateral_counts(db: Session, uid: uuid.UUID) -> dict[str, int]:
    from app.integrations.vacancies.models import VacancyApplication
    from app.modules.invitations.models import Invitation, InvitationComplaint, Probe
    from app.modules.contact.models import InvitationCounter

    def n(model):
        return db.scalar(select(func.count()).select_from(model).where(model.candidate_user_id == uid)) or 0

    return {"Приглашения работодателей": n(Invitation), "Зонды (короткие задачи)": n(Probe),
            "Отклики на вакансии": n(VacancyApplication), "Встречные предложения": n(InvitationCounter),
            "Жалобы на приглашения": n(InvitationComplaint)}


def preview(db: Session, user: User) -> dict:
    """Что будет удалено и обезличено — числа до подтверждения."""
    uid = user.id
    deleted = _group({name: db.scalar(select(func.count()).select_from(t).where(c)) or 0
                      for name, (t, c) in owned_tables(uid).items()})
    from app.modules.contact.models import ContactMessage
    from app.modules.invitations.models import Invitation
    from app.integrations.vacancies.models import VacancyApplication

    msgs = db.scalar(select(func.count()).select_from(ContactMessage).where(or_(
        ContactMessage.invitation_id.in_(select(Invitation.id).where(Invitation.candidate_user_id == uid)),
        ContactMessage.application_id.in_(select(VacancyApplication.id).where(VacancyApplication.candidate_user_id == uid)),
    ))) or 0
    if msgs:
        deleted[_label("contact_messages")] = msgs
    deleted["Профиль, контакты и скрытый минимум зарплаты"] = 1
    anonymized = {k: v for k, v in _bilateral_counts(db, uid).items() if v}
    return {"deleted": dict(sorted(deleted.items())), "anonymized": anonymized}


# ------------------------------------------------------------------ подтверждение

def uses_password(user: User) -> bool:
    """Пароль нужен тем, кто его знает; демо-учётки (вход в один клик) и вход через ФСП ID подтверждают почтой."""
    return not (user.is_demo or user.fsp_subject)


def confirm(db: Session, user: User, *, password: str | None, email: str | None, phrase: str | None,
            code: str | None) -> None:
    """Подтверждение: фраза «УДАЛИТЬ» + пароль (или своя почта для демо и ФСП ID) + код второго фактора, если он включён."""
    if (phrase or "").strip().upper() != "УДАЛИТЬ":
        raise api_error(422, "confirm_phrase", "Введите слово УДАЛИТЬ — так мы убеждаемся, что вы не нажали случайно")
    if uses_password(user):
        if not password or not verify_password(user.password_hash, password):
            raise api_error(403, "wrong_password", "Пароль не подошёл")
    elif (email or "").strip().lower() != user.email.lower():
        raise api_error(403, "wrong_email", "Введите свою почту, чтобы подтвердить удаление")
    from app.modules.auth import twofa

    if twofa.enabled(db, user):
        if not code:
            raise api_error(403, "second_factor_required", "Введите код из приложения-аутентификатора или резервный код")
        twofa.verify_second_factor(db, user, code)


# ------------------------------------------------------------------ удаление

@dataclass
class Result:
    deleted: dict[str, int]
    anonymized: dict[str, int]
    notify_email: str | None


def _scrub_events(rows, *, by: str) -> int:
    n = 0
    for r in rows:
        changed = False
        evs = [dict(e) for e in (r.events or [])]
        for e in evs:
            if e.get("by") == by and e.get("note"):
                e["note"] = None
                changed = True
        if changed:
            r.events = evs
            flag_modified(r, "events")
            n += 1
    return n


def _anonymize_bilateral(db: Session, uid: uuid.UUID) -> dict[str, int]:
    from app.integrations.vacancies.models import VacancyApplication
    from app.modules.contact.models import InvitationCounter
    from app.modules.invitations.models import Invitation, InvitationComplaint, InvitationEvent, Probe

    out: dict[str, int] = {}
    inv_ids = select(Invitation.id).where(Invitation.candidate_user_id == uid)
    app_ids = select(VacancyApplication.id).where(VacancyApplication.candidate_user_id == uid)
    now = utcnow()
    invs = db.scalars(select(Invitation).where(Invitation.candidate_user_id == uid)).all()
    for i in invs:
        i.evidence, i.decline_reason = [], None
        if i.contacts_revealed_at is not None:  # контакты закрыты: у работодателя не должно «светиться» обезличенное
            i.contacts_revealed_at, i.contacts_revoked_at = None, now
    out["Приглашения работодателей"] = len(invs)
    db.execute(update(InvitationEvent).where(InvitationEvent.invitation_id.in_(inv_ids),
                                             InvitationEvent.actor_user_id == uid).values(note=None))
    probes = db.scalars(select(Probe).where(Probe.candidate_user_id == uid)).all()
    for p in probes:
        p.answer = None
    _scrub_events(probes, by="candidate")
    out["Зонды (короткие задачи)"] = len(probes)
    apps = db.scalars(select(VacancyApplication).where(VacancyApplication.candidate_user_id == uid)).all()
    for a in apps:
        a.cover_letter = None
        if a.status in ("sent", "viewed", "accepted"):  # отклик снят: кандидата больше нет
            a.status = "withdrawn"
            a.events = [*(a.events or []), {"status": "withdrawn", "at": now.isoformat(), "by": "candidate", "note": None}]
            flag_modified(a, "events")
    _scrub_events(apps, by="candidate")
    out["Отклики на вакансии"] = len(apps)
    out["Встречные предложения"] = db.execute(
        update(InvitationCounter).where(InvitationCounter.candidate_user_id == uid).values(comment=None)).rowcount
    out["Жалобы на приглашения"] = db.execute(
        update(InvitationComplaint).where(InvitationComplaint.candidate_user_id == uid).values(comment=None)).rowcount
    return {k: v for k, v in out.items() if v}


def _delete_messages(db: Session, uid: uuid.UUID) -> int:
    from app.integrations.vacancies.models import VacancyApplication
    from app.modules.contact.models import ContactMessage
    from app.modules.invitations.models import Invitation

    return db.execute(delete(ContactMessage).where(or_(
        ContactMessage.invitation_id.in_(select(Invitation.id).where(Invitation.candidate_user_id == uid)),
        ContactMessage.application_id.in_(select(VacancyApplication.id).where(VacancyApplication.candidate_user_id == uid)),
    ))).rowcount


def erase(db: Session, user: User, *, reason: str = "user_request") -> Result:
    """Выполняет удаление в одной транзакции. Подтверждение (confirm) — на вызывающей стороне."""
    if user.role != UserRole.candidate:
        raise api_error(403, "forbidden", "Удаление данных через кабинет доступно кандидату; работодатель — по обращению к оператору")
    uid, email, demo = user.id, user.email, bool(user.is_demo)
    counts: dict[str, int] = {}
    # 1. переписка (в обеих сторонах) — до обезличивания приглашений, пока видны связи
    counts["contact_messages"] = _delete_messages(db, uid)
    # 2. двусторонние записи работодателя — обезличиваем
    anonymized = _anonymize_bilateral(db, uid)
    # 3. паспорт грейда: отзыв и обнуление ссылки на учётку
    from app.passport import service as passport
    from app.passport.models import GradePassport

    revoked = passport.revoke_user(db, uid, "account_deleted")
    detached = db.execute(update(GradePassport).where(GradePassport.user_id == uid).values(user_id=None)).rowcount
    if detached:
        anonymized["Паспорт грейда (остаётся в реестре как отозванный)"] = detached
    # 4. отзыв опроса удобства: оценка остаётся, привязка и комментарий — нет
    from app.integrations.sus.models import SusResponse

    sus = db.execute(update(SusResponse).where(SusResponse.user_id == uid).values(user_id=None, comment=None)).rowcount
    if sus:
        anonymized["Оценка удобства (SUS) — без привязки и комментария"] = sus
    # 5. всё остальное по схеме БД — от листьев к корню
    owned = owned_tables(uid)
    for t in reversed(metadata.sorted_tables):
        if t.name in owned:
            tt, cond = owned[t.name]
            counts[t.name] = db.execute(delete(tt).where(cond)).rowcount or 0
    # 6. счётчик песочницы жюри хранится по почте демо-учётки — у живых кандидатов его нет
    if not demo:
        from app.modules.assessment.models import SandboxTestStart

        db.execute(delete(SandboxTestStart).where(SandboxTestStart.user_id == uid))
    # 7. профиль — «надгробие» без личных данных; учётка — без почты, пароля и входа
    p = db.get(CandidateProfile, uid)
    if p is not None:
        p.full_name = p.phone = p.telegram = p.city = p.headline = p.about = None
        p.experience_years = p.salary_min_hidden = p.rating_score = p.fsp_id_claimed = None
        p.current_direction_id = p.current_grade_id = p.current_category_id = None
        p.grade_locked_until = p.onboarding_completed_at = p.parental_consent_at = None
        p.grade_provisional = p.visible_to_employers = p.relocation = p.jury_mode = p.parental_consent = False
        p.onboarding_completed_at = None
        p.privacy, p.roles = {}, []
        p.work_format, p.age_group = WorkFormat.any, "18+"
        p.deleted_at = utcnow()
    user.email = (f"deleted-{secrets.token_hex(8)}@deleted.invalid" if not demo
                  else _demo_tombstone(email))
    user.password_hash = "!deleted"  # не разбирается ни одним алгоритмом: вход невозможен
    user.is_active = False
    user.is_email_verified = False
    user.email_verified_at = user.last_login_at = None
    user.fsp_subject = None
    user.token_version = (user.token_version or 0) + 1  # выданные токены перестают действовать
    deleted = _group(counts)
    if counts.get("contact_messages"):
        deleted[_label("contact_messages")] = counts["contact_messages"]
    deleted["Профиль, контакты и скрытый минимум зарплаты"] = 1
    anonymized["Учётная запись (почта, пароль, вход) — обезличена"] = 1
    db.add(AccountDeletionLog(role="candidate", is_demo=demo, reason=reason,
                              details={"deleted": deleted, "anonymized": anonymized, "passports_revoked": revoked}))
    db.commit()
    log.info("Учётная запись кандидата удалена: удалено %d категорий, обезличено %d", len(deleted), len(anonymized))
    return Result(dict(sorted(deleted.items())), anonymized, None if demo else email)


def _demo_tombstone(email: str) -> str:
    """Демо-учётка песочницы: почта сохраняет «+sid@домен» — сброс или удаление песочницы найдёт и уберёт её."""
    local, _, domain = email.partition("@")
    return f"deleted-{secrets.token_hex(4)}.{local}@{domain}"
