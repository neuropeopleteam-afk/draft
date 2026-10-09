"""Зонды и приглашения: правила, статусы с историей, раскрытие контактов, доказательства.

Правила (покрыты тестами):
* вилка «от–до» в рублях обязательна и для зонда, и для приглашения (0 < from ≤ to ≤ 1,5 × from);
* одно приглашение кандидату от одного работодателя (компании) за 30 дней → иначе 409 invitation_cooldown;
* контакты кандидата видны работодателю только после принятия приглашения его компании;
* работодатель видит рыночный диапазон категории, минимум кандидата — никогда.
"""
from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource, InvitationStatus, ProbeStatus
from app.core.errors import api_error
from app.core.fmt import theta_se
from app.modules.auth.models import User
from app.modules.catalog.seed_data import STACK, category_title
from app.modules.invitations.models import Invitation, InvitationComplaint, InvitationEvent, Probe
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.facts import achievement_text, fmt_count, load_bundles, refresh_rating, skill_confirmed, skill_evidence_text
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company

INVITATION_COOLDOWN_DAYS = 30
# Ширина вилки: «до» не больше чем в 1,5 раза выше «от» (200–300 тыс. можно, 100–300 тыс. — нет)
SALARY_MAX_RATIO = 1.5


def profile_by_ref(db: Session, ref: str) -> CandidateProfile:
    """Кандидат по обезличенному ref для работодателя: карточка, PDF, сравнение, зонд, приглашение, паспорт, задания.

    Видимость та же, что у поиска и подборок: профиль открыт, учётка активна, есть категория (основного или
    дополнительного направления, в том числе «предварительно») или опрос пройден без подтверждённого грейда (статус
    «не подтверждён» показывается в карточке, зонд и приглашение доступны), и кандидат виден в песочнице текущего
    запроса (jury_scope.visible: кандидат чужой песочницы жюри — и для другой песочницы, и для общего демо, и для
    настоящего работодателя не существует). Иначе прямая ссылка по ref обходила бы фильтр списков. Все причины — один
    и тот же 404, чтобы по ответу нельзя было узнать о существовании кандидата.
    """
    from app.modules.jury import scope as jury_scope
    from app.modules.profiles.models import CandidateSpecialization

    row = db.execute(select(CandidateProfile, User.email, User.is_active).join(User, User.id == CandidateProfile.user_id)
                     .where(CandidateProfile.public_ref == ref)).first()
    p, email, active = row if row else (None, None, False)
    has_category = p and (p.current_category_id or db.scalar(select(CandidateSpecialization.category_id).where(
        CandidateSpecialization.user_id == p.user_id, CandidateSpecialization.category_id.is_not(None),
        CandidateSpecialization.status.in_(["confirmed", "provisional"])).limit(1)))
    if (p is None or not active or not p.visible_to_employers or not (has_category or p.onboarding_completed_at)
            or not jury_scope.visible(email)):
        raise api_error(404, "candidate_not_found", "Кандидат не найден или скрыл профиль")
    return p


def check_salary(salary_from: int | None, salary_to: int | None) -> None:
    if not salary_from or not salary_to or salary_from <= 0 or salary_to <= 0:
        raise api_error(422, "salary_range_required", "Укажите вилку зарплаты «от» и «до» в рублях")
    if salary_from > salary_to:
        raise api_error(422, "salary_range_invalid", "Нижняя граница вилки больше верхней")
    if salary_to > SALARY_MAX_RATIO * salary_from:
        top = int(salary_from * SALARY_MAX_RATIO) // 1000 * 1000
        rub = (lambda v: f"{v:,}".replace(",", "\u00a0") + "\u00a0₽")
        raise api_error(422, "salary_range_too_wide",
                        f"Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от». При «от» "
                        f"{rub(salary_from)} укажите «до» не выше {rub(top)} — так кандидат понимает, "
                        f"что ему предлагают")


def cooldown_until(db: Session, company_id: uuid.UUID, candidate_id: uuid.UUID):
    """Дата, с которой компания снова может пригласить кандидата, или None, если можно сейчас."""
    since = utcnow() - timedelta(days=INVITATION_COOLDOWN_DAYS)
    last = db.scalar(select(Invitation).where(
        Invitation.company_id == company_id, Invitation.candidate_user_id == candidate_id,
        Invitation.created_at > since,
    ).order_by(Invitation.created_at.desc()).limit(1))
    return as_aware(last.created_at) + timedelta(days=INVITATION_COOLDOWN_DAYS) if last else None


def contacts_revealed(db: Session, company_id: uuid.UUID, candidate_id: uuid.UUID) -> Invitation | None:
    return db.scalar(select(Invitation).where(
        Invitation.company_id == company_id, Invitation.candidate_user_id == candidate_id,
        Invitation.status == InvitationStatus.accepted, Invitation.contacts_revealed_at.is_not(None),
    ).limit(1))


def candidate_contacts(db: Session, candidate_id: uuid.UUID) -> dict:
    p = db.get(CandidateProfile, candidate_id)
    u = db.get(User, candidate_id)
    if p.deleted_at is not None:  # кандидат удалил учётную запись («Мои данные»): контактов больше нет
        return {"full_name": None, "email": None, "phone": None, "telegram": None}
    return {"full_name": p.full_name, "email": u.email, "phone": p.phone, "telegram": p.telegram}


def build_evidence(db: Session, candidate_id: uuid.UUID, company_id: uuid.UUID, need: EmployerNeed | None) -> list[dict]:
    """Подтверждённые факты (T1/T2), прикладываемые к приглашению автоматически."""
    b = load_bundles(db, [candidate_id], direction=(need.requirements or {}).get("direction") if need else None)[candidate_id]
    ev = []
    if b.test:
        t = b.test.value
        what = ("Экспресс-категория {} (предварительно) по мини-тесту" if t.get("mini") else "Категория {} подтверждена тестом")
        ev.append({"level": "T1", "kind": "test",
                   "text": f"{what.format(category_title(b.category_id))}: {t.get('correct')} из "
                           f"{t.get('answered')} верно, θ = {theta_se(t.get('theta', 0), t.get('se', 0))}"})
    wanted = []
    if need:
        r = need.requirements or {}
        wanted = [i["tag"] for i in (r.get("stack_required") or []) + (r.get("stack_desired") or [])]
    for tag, f in b.skills_t1.items():
        if skill_confirmed(f) and (not wanted or tag in wanted):
            ev.append({"level": "T1", "kind": "skill",
                       "text": f"{STACK.get(tag, (tag,))[0]}: {skill_evidence_text(f).lower()}"})  # тест и задания (И7)
    for a in b.achievements[:3]:
        if a.verified:
            ev.append({"level": "T2", "kind": "fsp", "text": achievement_text(a)})
    for pr in db.scalars(select(Probe).where(Probe.company_id == company_id, Probe.candidate_user_id == candidate_id,
                                            Probe.status == ProbeStatus.reviewed)).all():
        ev.append({"level": "T1", "kind": "probe", "text": f"Зонд «{pr.title}»: {(pr.review or {}).get('verdict_title', 'оценён')}"})
    for f in b.probes_t1:  # задания работодателя с автопроверкой (И7)
        if (f.value or {}).get("origin") == "assignment":
            ev.append({"level": "T1", "kind": "assignment", "text": f"{f.title}: {f.value.get('verdict')}"})
    return ev


def _event(db: Session, inv: Invitation, to: InvitationStatus, actor: uuid.UUID | None, note: str | None = None):
    db.add(InvitationEvent(invitation_id=inv.id, from_status=inv.status if inv.id else None, to_status=to,
                           actor_user_id=actor, note=note))
    inv.status = to


def create_invitation(db: Session, employer: User, company: Company, candidate: CandidateProfile, *,
                      position_title: str, offer_description: str, salary_from: int, salary_to: int,
                      contact_method: str, need_id: uuid.UUID | None, probe_id: uuid.UUID | None,
                      employment_terms: dict | None = None, salary_basis: str = "gross") -> Invitation:
    from app.modules.fsp.youth import check_offer

    terms = employment_terms or {"format": "employment", "reduced_time": False, "employer_acknowledged": False}
    check_offer(candidate, terms)
    check_salary(salary_from, salary_to)
    until = cooldown_until(db, company.id, candidate.user_id)
    if until:
        raise api_error(409, "invitation_cooldown",
                        f"Этому кандидату ваша компания уже отправляла приглашение. Следующее — с {until:%d.%m.%Y}")
    need = db.get(EmployerNeed, need_id) if need_id else None
    if need is not None and need.company_id != company.id:
        need = None
    inv = Invitation(company_id=company.id, employer_user_id=employer.id, candidate_user_id=candidate.user_id,
                     need_id=need.id if need else None, probe_id=probe_id, position_title=position_title,
                     offer_description=offer_description, salary_from=salary_from, salary_to=salary_to,
                     contact_method=contact_method, employment_terms=terms, salary_basis=salary_basis,
                     evidence=build_evidence(db, candidate.user_id, company.id, need),
                     status=InvitationStatus.sent, expires_at=utcnow() + timedelta(days=INVITATION_COOLDOWN_DAYS))
    db.add(inv)
    db.flush()
    db.add(InvitationEvent(invitation_id=inv.id, from_status=None, to_status=InvitationStatus.sent,
                           actor_user_id=employer.id))
    db.commit()
    return inv


def mark_viewed(db: Session, inv: Invitation, actor: uuid.UUID) -> None:
    if inv.status == InvitationStatus.sent:
        inv.viewed_at = utcnow()
        _event(db, inv, InvitationStatus.viewed, actor)
        db.commit()


def respond(db: Session, inv: Invitation, actor: uuid.UUID, accept: bool, reason: str | None) -> Invitation:
    if inv.status not in (InvitationStatus.sent, InvitationStatus.viewed):
        raise api_error(409, "invitation_closed", "На это приглашение уже нельзя ответить")
    now = utcnow()
    if inv.viewed_at is None:
        inv.viewed_at = now
        _event(db, inv, InvitationStatus.viewed, actor)
    inv.responded_at = now
    from app.modules.contact.service import close_pending_counter  # встречное закрывается ответом кандидата

    close_pending_counter(db, inv, actor)
    if accept:
        from app.modules.fsp.youth import check_offer

        check_offer(db.get(CandidateProfile, inv.candidate_user_id), inv.employment_terms or {})
        _event(db, inv, InvitationStatus.accepted, actor)
        inv.contacts_revealed_at = now
    else:
        inv.decline_reason = (reason or "").strip() or None
        _event(db, inv, InvitationStatus.declined, actor, inv.decline_reason)
    db.commit()
    return inv


COMPLAINT_REASONS = {
    "salary": "Нереальная вилка",
    "role": "Не та роль",
    "spam": "Спам или массовая рассылка",
    "other": "Другое",
}


def complaint_of(db: Session, inv: Invitation) -> InvitationComplaint | None:
    return db.scalar(select(InvitationComplaint).where(InvitationComplaint.invitation_id == inv.id))


def complaint_out(c: InvitationComplaint | None, *, with_comment: bool) -> dict | None:
    if c is None:
        return None
    out = {"reason": c.reason, "reason_title": COMPLAINT_REASONS.get(c.reason, c.reason), "at": c.created_at.isoformat()}
    if with_comment:
        out["comment"] = c.comment
    return out


def complain(db: Session, inv: Invitation, actor: uuid.UUID, reason: str, comment: str | None) -> InvitationComplaint:
    """Жалоба приглашённого кандидата; неотвеченное приглашение заодно отклоняется. Одна жалоба на приглашение."""
    if reason not in COMPLAINT_REASONS:
        raise api_error(422, "complaint_reason", "Неизвестная причина жалобы")
    if complaint_of(db, inv) is not None:
        raise api_error(409, "complaint_exists", "Жалоба на это приглашение уже отправлена")
    c = InvitationComplaint(invitation_id=inv.id, company_id=inv.company_id, candidate_user_id=inv.candidate_user_id,
                            reason=reason, comment=(comment or "").strip() or None)
    db.add(c)
    if inv.status in (InvitationStatus.sent, InvitationStatus.viewed):
        respond(db, inv, actor, False, f"Жалоба: {COMPLAINT_REASONS[reason].lower()}")
    else:
        db.commit()
    return c


def withdraw(db: Session, inv: Invitation, actor: uuid.UUID) -> Invitation:
    if inv.status not in (InvitationStatus.sent, InvitationStatus.viewed):
        raise api_error(409, "invitation_closed", "Отозвать можно только неотвеченное приглашение")
    from app.modules.contact.service import close_pending_counter

    close_pending_counter(db, inv, actor)
    _event(db, inv, InvitationStatus.withdrawn, actor)
    db.commit()
    return inv


def events_of(db: Session, inv: Invitation) -> list[dict]:
    rows = db.scalars(select(InvitationEvent).where(InvitationEvent.invitation_id == inv.id)
                      .order_by(InvitationEvent.created_at)).all()
    # kind — событие без смены статуса (встречное предложение, доступ к контактам): показывается как статус истории
    return [{"status": e.kind or e.to_status.value, "at": e.created_at.isoformat(), "note": e.note,
             "by": "candidate" if e.actor_user_id == inv.candidate_user_id else "employer"} for e in rows]


# ------------------------------------------------------------------ зонды

PROBE_VERDICTS = {"strong": ("Сильное решение", 1.0), "ok": ("Хорошее решение", 0.7), "weak": ("Слабое решение", 0.3)}


def probe_event(p: Probe, status: ProbeStatus, by: str, note: str | None = None) -> None:
    p.events = [*(p.events or []), {"status": status.value, "at": utcnow().isoformat(), "by": by, "note": note}]
    p.status = status
    flag_modified(p, "events")


def create_probe(db: Session, employer: User, company: Company, candidate: CandidateProfile, *, title: str,
                 task_text: str, answer_mode: str, salary_from: int, salary_to: int, time_limit_min: int,
                 need_id: uuid.UUID | None, salary_basis: str = "gross") -> Probe:
    check_salary(salary_from, salary_to)
    active = db.scalar(select(Probe).where(
        Probe.company_id == company.id, Probe.candidate_user_id == candidate.user_id,
        Probe.status.in_([ProbeStatus.sent, ProbeStatus.viewed])).limit(1))
    if active:
        raise api_error(409, "probe_active", "У кандидата уже есть ваш неотвеченный зонд")
    need = db.get(EmployerNeed, need_id) if need_id else None
    p = Probe(company_id=company.id, employer_user_id=employer.id, candidate_user_id=candidate.user_id,
              need_id=need.id if need and need.company_id == company.id else None, title=title, task_text=task_text,
              answer_mode=answer_mode, salary_from=salary_from, salary_to=salary_to, salary_basis=salary_basis,
              time_limit_s=time_limit_min * 60,
              deadline_at=utcnow() + timedelta(days=7), events=[])
    probe_event(p, ProbeStatus.sent, "employer")
    db.add(p)
    db.commit()
    return p


def submit_probe(db: Session, p: Probe, mode: str, text: str, link: str | None) -> Probe:
    if p.status not in (ProbeStatus.sent, ProbeStatus.viewed):
        raise api_error(409, "probe_closed", "На этот зонд уже нельзя ответить")
    if p.answer_mode != "any" and mode != p.answer_mode:
        raise api_error(422, "answer_mode_mismatch", "Работодатель просит другой формат ответа")
    p.answer = {"mode": mode, "text": text, "link": link}
    p.submitted_at = utcnow()
    probe_event(p, ProbeStatus.submitted, "candidate")
    db.commit()
    return p


def decline_probe(db: Session, p: Probe, reason: str | None) -> Probe:
    if p.status not in (ProbeStatus.sent, ProbeStatus.viewed):
        raise api_error(409, "probe_closed", "Зонд уже закрыт")
    probe_event(p, ProbeStatus.declined, "candidate", (reason or "").strip() or None)
    db.commit()
    return p


def review_probe(db: Session, p: Probe, verdict: str, comment: str | None) -> Probe:
    if p.status != ProbeStatus.submitted:
        raise api_error(409, "probe_not_submitted", "Оценить можно только присланный ответ")
    title, score = PROBE_VERDICTS[verdict]
    p.score = score
    p.review = {"verdict": verdict, "verdict_title": title, "comment": comment}
    probe_event(p, ProbeStatus.reviewed, "employer")
    need = db.get(EmployerNeed, p.need_id) if p.need_id else None
    profile = db.get(CandidateProfile, p.candidate_user_id)
    db.add(CandidateFact(user_id=p.candidate_user_id, kind="probe", key=str(p.id), title=p.title[:255],
                         value={"score": score, "verdict": title,
                                "direction": need.direction_id if need and need.direction_id else profile.current_direction_id},
                         evidence_level=EvidenceLevel.T1,
                         source=FactSource.probe, source_ref=f"probe:{p.id}"))
    db.flush()
    refresh_rating(db, p.candidate_user_id)
    # «Junior (предварительно)»: зонд с оценкой «хорошее решение» и выше подтверждает грейд (не смена грейда)
    from app.modules.assessment import provisional

    provisional.confirm_by_work(db, p.candidate_user_id, source="probe", ref=f"probe:{p.id}", ref_title=p.title,
                                score=float(score), direction=need.direction_id if need else None)
    db.commit()
    return p


def below_minimum(profile: CandidateProfile, salary_to: int, salary_basis: str | None = "gross") -> bool:
    """Видно только кандидату: верх вилки ниже его скрытого минимума. Минимум — на руки, поэтому вилка до вычета
    НДФЛ сравнивается после пересчёта (app.modules.contact.salary)."""
    from app.modules.contact.salary import to_net

    return bool(profile.salary_min_hidden and to_net(salary_to, salary_basis) < profile.salary_min_hidden)

