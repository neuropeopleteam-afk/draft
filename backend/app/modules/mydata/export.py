"""Выгрузка «Мои данные»: всё, что платформа хранит о кандидате, одним JSON-файлом (152-ФЗ, ст. 14).

Принципы:

* только данные самого кандидата. Чужого в файле нет: ни почт и имён работодателей, ни других кандидатов, ни их
  ref. Название компании — есть (оно в приглашении, которое видит кандидат); имя и почта сотрудника компании — нет;
* то, что скрыто от работодателя (телефон, Telegram, скрытый минимум зарплаты), кандидат видит — оно его;
* из теста — только ответы кандидата и итог. Текстов заданий, вариантов, ключей и проверочных разборов нет: это
  банк заданий оператора (иначе выгрузка стала бы способом его скопировать), а достоверность — в том виде, как её
  видит сам кандидат (Р27: уровень и общая причина, без названий сигналов и порогов);
* секреты не выгружаются (хеш пароля, секрет второго фактора, коды, ключи push-подписок): для них — число и даты;
* всё, что связано с учётной записью, но не описано отдельным разделом (появится в схеме позже), попадает в раздел
  ``other`` с той же очисткой секретов — выгрузка не отстаёт от схемы БД (см. ``erase.owned_tables``).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.legal import CONSENT_VERSION, OPERATOR
from app.modules.mydata import erase, interest
from app.modules.auth.models import Consent, User
from app.modules.profiles.models import CandidateProfile

FORMAT = "vstrechny.my-data/1"
SECRET_COL = re.compile(r"(secret|token|_hash$|^hash|password|^p256dh$|^auth$|signature|^endpoint$|nonce|verifier|^ticket|api_key|private)", re.I)
# Разделы, для которых выгрузка устроена особо (в «other» не дублируются)
SECTION_TABLES = {
    "candidate_facts", "candidate_specializations", "candidate_resumes", "survey_responses", "survey_stack_tags",
    "test_sessions", "test_session_items", "test_answers", "grade_history", "proctor_sessions", "proctor_events",
    "consents", "fsp_passports", "fsp_achievements", "cup_entries", "assignment_attempts", "push_subscriptions",
    "user_two_factor", "user_two_factor_recovery_codes", "email_verifications", "oidc_login_states",
    "candidate_interest_events", "jury_live_guests",
}


def _j(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _j(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_j(x) for x in v]
    return v


def _row(obj, *, only: tuple[str, ...] | None = None, skip: tuple[str, ...] = ()) -> dict:
    """Колонки записи → словарь JSON. Секретоподобные колонки пропускаются всегда."""
    cols = [c.name for c in obj.__table__.columns]
    return {k: _j(getattr(obj, k)) for k in (only or cols) if k not in skip and not SECRET_COL.search(k)}


def _rows(db: Session, model, cond, order=None, **kw) -> list[dict]:
    q = select(model).where(cond)
    if order is not None:
        q = q.order_by(order)
    return [_row(r, **kw) for r in db.scalars(q).all()]


# ------------------------------------------------------------------ разделы

def _account(db: Session, user: User) -> dict:
    from app.modules.auth import twofa

    return {"email": user.email, "role": user.role.value, "created_at": _j(user.created_at),
            "email_verified_at": _j(user.email_verified_at), "last_login_at": _j(user.last_login_at),
            "login_by_fsp_id": bool(user.fsp_subject), "two_factor_enabled": twofa.enabled(db, user),
            "demo_account": bool(user.is_demo)}


def _tests(db: Session, uid: uuid.UUID) -> dict:
    from app.modules.assessment.integrity import candidate_view
    from app.modules.assessment.models import GradeHistory, TestAnswer, TestSession, TestSessionItem

    sessions = []
    for ts in db.scalars(select(TestSession).where(TestSession.user_id == uid).order_by(TestSession.created_at)).all():
        outcome = ((ts.result or {}).get("outcome") or {})
        er = (ts.result or {}).get("engine_result") or {}
        answers = db.execute(
            select(TestSessionItem.position, TestAnswer).join(TestAnswer, TestAnswer.item_id == TestSessionItem.id)
            .where(TestAnswer.session_id == ts.id).order_by(TestSessionItem.position)).all()
        rows_ = [{"position": pos, "answer": _j(a.answer), "is_correct": a.is_correct, "score": a.score,
                  "time_spent_ms": a.time_spent_ms, "answered_at": _j(a.answered_at)} for pos, a in answers]
        if not rows_:  # учебный движок без банка хранит ответы в состоянии попытки: выбранный вариант и время
            st = (ts.result or {}).get("state") or {}
            ids = st.get("item_ids") or []
            rows_ = [{"position": ids.index(k) + 1 if k in ids else None, "answer": _j(v.get("choice")),
                      "is_correct": v.get("ok"), "score": None, "time_spent_ms": v.get("ms"), "answered_at": None}
                     for k, v in (st.get("answers") or {}).items()]
            rows_.sort(key=lambda r: r["position"] or 0)
        sessions.append({
            **_row(ts, only=("id", "direction_id", "claimed_grade_id", "status", "started_at", "deadline_at",
                             "finished_at", "score", "theta", "theta_se", "result_grade_id", "is_sandbox", "created_at")),
            "outcome": {k: _j(outcome.get(k)) for k in (
                "changed", "grade", "theta", "se", "claimed_grade", "point_grade", "confirmed", "upgrade_available",
                "answered", "correct", "provisional", "category_id", "category_status", "mode", "message",
                "locked_until") if k in outcome},
            # достоверность — как её видит кандидат (Р27); подробности работодателю в выгрузку не входят
            "integrity": candidate_view((er.get("details") or {}).get("integrity")),
            "answers": rows_,
        })
    history = _rows(db, GradeHistory, GradeHistory.user_id == uid, GradeHistory.created_at, skip=("id", "user_id"))
    return {"sessions": sessions, "grade_history": history,
            "note": "Тексты заданий, варианты ответов, ключи и проверочные разборы не выгружаются: это банк заданий "
                    "оператора. Ваши ответы и итог — в файле."}


def _camera(db: Session, uid: uuid.UUID) -> dict:
    from app.modules.proctor.models import ProctorEvent, ProctorSession

    out = []
    for ps in db.scalars(select(ProctorSession).where(ProctorSession.user_id == uid).order_by(ProctorSession.created_at)).all():
        events = _rows(db, ProctorEvent, ProctorEvent.proctor_id == ps.id, ProctorEvent.position,
                       skip=("id", "proctor_id"))
        out.append({**_row(ps, skip=("id", "user_id", "consent_id", "session_id")), "events": events})
    return {"sessions": out,
            "note": "Кадры, признаки лица и звук не хранятся и не передаются: анализ идёт на вашем устройстве, "
                    "на сервер уходят только события «нет лица», «два лица», «камера закрыта» и время наблюдения."}


def _consents(db: Session, uid: uuid.UUID) -> list[dict]:
    return [{"kind": c.kind.value, "document_version": c.document_version, "granted_at": _j(c.granted_at),
             "revoked_at": _j(c.revoked_at)} for c in db.scalars(
        select(Consent).where(Consent.user_id == uid).order_by(Consent.granted_at)).all()]


def _employer_side(db: Session, uid: uuid.UUID) -> dict:
    """Приглашения, зонды, встречные, жалобы, переписка, отклики: в виде, как их видит кандидат; кому открыты контакты."""
    from app.integrations.vacancies.models import Vacancy, VacancyApplication
    from app.modules.contact.models import ContactMessage, InvitationCounter
    from app.modules.invitations.models import Invitation, InvitationComplaint, InvitationEvent, Probe
    from app.modules.profiles.models import Company
    from app.core.enums import InvitationStatus

    def company(cid) -> dict | None:
        c = db.get(Company, cid)
        return {"name": c.name, "industry": c.industry, "website": c.website, "city": c.city} if c else None

    invs, opened = [], []
    for i in db.scalars(select(Invitation).where(Invitation.candidate_user_id == uid).order_by(Invitation.created_at)).all():
        events = db.scalars(select(InvitationEvent).where(InvitationEvent.invitation_id == i.id)
                            .order_by(InvitationEvent.created_at)).all()
        counters = db.scalars(select(InvitationCounter).where(InvitationCounter.invitation_id == i.id)
                              .order_by(InvitationCounter.created_at)).all()
        comp = db.scalar(select(InvitationComplaint).where(InvitationComplaint.invitation_id == i.id))
        msgs = db.scalars(select(ContactMessage).where(ContactMessage.invitation_id == i.id)
                          .order_by(ContactMessage.created_at)).all()
        is_open = i.status == InvitationStatus.accepted and i.contacts_revealed_at is not None
        item = {
            "id": str(i.id), "company": company(i.company_id), "position_title": i.position_title,
            "offer_description": i.offer_description, "salary_from": i.salary_from, "salary_to": i.salary_to,
            "salary_basis": i.salary_basis, "employment_terms": _j(i.employment_terms), "evidence": _j(i.evidence),
            "status": i.status.value, "created_at": _j(i.created_at), "viewed_at": _j(i.viewed_at),
            "responded_at": _j(i.responded_at), "decline_reason": i.decline_reason,
            # способ связи работодателя — только после принятия приглашения, как и в кабинете
            "employer_contact_method": i.contact_method if i.status == InvitationStatus.accepted else None,
            "contacts_open_to_employer": is_open, "contacts_revealed_at": _j(i.contacts_revealed_at),
            "contacts_revoked_at": _j(i.contacts_revoked_at),
            "history": [{"from": _j(e.from_status), "to": _j(e.to_status), "kind": e.kind, "note": e.note,
                         "at": _j(e.created_at)} for e in events],
            "counters": [{"salary_from": c.salary_from, "salary_to": c.salary_to, "salary_basis": c.salary_basis,
                          "offer_from": c.offer_from, "offer_to": c.offer_to, "comment": c.comment, "status": c.status,
                          "employer_note": c.employer_note, "created_at": _j(c.created_at),
                          "decided_at": _j(c.decided_at)} for c in counters],
            "complaint": ({"reason": comp.reason, "comment": comp.comment, "created_at": _j(comp.created_at)}
                          if comp else None),
            "messages": [{"from": "я" if m.sender_side == "candidate" else "работодатель", "body": m.body,
                          "mode": m.mode, "at": _j(m.created_at)} for m in msgs],
        }
        invs.append(item)
        if is_open:
            opened.append({"company": item["company"], "invitation_id": item["id"], "since": item["contacts_revealed_at"],
                           "what": "телефон, Telegram и почта из профиля — по принятому приглашению"})
    probes = [{"id": str(p.id), "company": company(p.company_id), "title": p.title, "task_text": p.task_text,
               "answer_mode": p.answer_mode, "salary_from": p.salary_from, "salary_to": p.salary_to,
               "salary_basis": p.salary_basis, "status": _j(p.status), "answer": _j(p.answer), "review": _j(p.review),
               "events": _j(p.events), "created_at": _j(p.created_at), "deadline_at": _j(p.deadline_at),
               "submitted_at": _j(p.submitted_at)}
              for p in db.scalars(select(Probe).where(Probe.candidate_user_id == uid).order_by(Probe.created_at)).all()]
    apps = []
    for a in db.scalars(select(VacancyApplication).where(VacancyApplication.candidate_user_id == uid)
                        .order_by(VacancyApplication.created_at)).all():
        v = db.get(Vacancy, a.vacancy_id)
        msgs = db.scalars(select(ContactMessage).where(ContactMessage.application_id == a.id)
                          .order_by(ContactMessage.created_at)).all()
        apps.append({"id": str(a.id), "vacancy_title": v.title if v else None, "company": company(v.company_id) if v else None,
                     "cover_letter": a.cover_letter, "status": a.status, "events": _j(a.events),
                     "employer_note": a.employer_note if a.status in ("accepted", "rejected") else None,
                     "created_at": _j(a.created_at), "viewed_at": _j(a.viewed_at), "responded_at": _j(a.responded_at),
                     "messages": [{"from": "я" if m.sender_side == "candidate" else "работодатель", "body": m.body,
                                   "at": _j(m.created_at)} for m in msgs]})
    return {"invitations": invs, "probes": probes, "applications": apps, "contacts_open_to": opened}


def _other(db: Session, uid: uuid.UUID, covered: set[str]) -> dict:
    """Остальные таблицы с данными учётной записи — построчно, без секретоподобных колонок."""
    out = {}
    for name, (t, cond) in erase.owned_tables(uid).items():
        if name in covered:
            continue
        rows = db.execute(select(t).where(cond)).mappings().all()
        out[name] = [{k: _j(v) for k, v in r.items() if not SECRET_COL.search(k)} for r in rows]
    return out


def build(db: Session, user: User) -> dict:
    uid = user.id
    from app.modules.assessment.models import SurveyResponse, SurveyStackTag
    from app.modules.fsp.models import FspAchievement, FspPassport
    from app.modules.profiles.models import CandidateFact, CandidateResume, CandidateSpecialization
    from app.cup.models import CupEntry
    from app.integrations.push.models import PushSubscription
    from app.passport.models import GradePassport

    profile = db.get(CandidateProfile, uid)
    surveys = []
    for s in db.scalars(select(SurveyResponse).where(SurveyResponse.user_id == uid).order_by(SurveyResponse.created_at)).all():
        tags = db.execute(select(SurveyStackTag.stack_tag_id, SurveyStackTag.self_level)
                          .where(SurveyStackTag.survey_id == s.id)).all()
        surveys.append({**_row(s, skip=("id", "user_id")), "stack": [{"tag": t, "level": lv} for t, lv in tags]})
    passports = []
    for fp in db.scalars(select(FspPassport).where(FspPassport.user_id == uid)).all():
        passports.append({**_row(fp, skip=("id", "user_id", "raw")),
                          "achievements": _rows(db, FspAchievement, FspAchievement.passport_id == fp.id,
                                                skip=("id", "passport_id"))})
    pushes = db.execute(select(PushSubscription.user_agent, PushSubscription.created_at, PushSubscription.last_success_at)
                        .where(PushSubscription.user_id == uid)).all()
    grade_passports = [{"id": g.id, "category_id": g.category_id, "grade_status": g.grade_status, "issued_at": _j(g.issued_at),
                        "valid_until": _j(g.valid_until), "revoked_at": _j(g.revoked_at), "revoke_reason": g.revoke_reason}
                       for g in db.scalars(select(GradePassport).where(GradePassport.user_id == uid)
                                           .order_by(GradePassport.issued_at)).all()]
    covered = set(SECTION_TABLES)
    data = {
        "format": FORMAT,
        "generated_at": utcnow().isoformat(),
        "about": {
            "operator": {"name": OPERATOR["short_name"], "email": OPERATOR["email"]},
            "consent_document_version": CONSENT_VERSION,
            "what_is_here": "Все данные вашей учётной записи, которые платформа хранит на дату выгрузки.",
            "not_included": [
                "Данные других людей: другие кандидаты, имена и почты сотрудников работодателей.",
                "Банк заданий теста (тексты, варианты, ключи) — собственность оператора; только ваши ответы и итоги.",
                "Секреты: пароль, секрет второго фактора, коды и ключи подписок — они хранятся в виде, который "
                "нельзя прочитать, и выгрузке не принадлежат.",
                "Кадры и звук с камеры — они не хранятся: анализ идёт на вашем устройстве.",
            ],
        },
        "account": _account(db, user),
        "profile": _row(profile, skip=("deleted_at",)) if profile else None,
        "specializations": _rows(db, CandidateSpecialization, CandidateSpecialization.user_id == uid,
                                 skip=("user_id",)),
        "survey": surveys,
        "facts": _rows(db, CandidateFact, CandidateFact.user_id == uid, CandidateFact.created_at, skip=("id", "user_id")),
        "resumes": _rows(db, CandidateResume, CandidateResume.user_id == uid, CandidateResume.created_at,
                         skip=("id", "user_id")),
        "tests": _tests(db, uid),
        "camera": _camera(db, uid),
        "consents": _consents(db, uid),
        **_employer_side(db, uid),
        "cups": _rows(db, CupEntry, CupEntry.candidate_user_id == uid, skip=("id", "candidate_user_id", "grading", "tasks", "cup_id", "invitation_id")),
        "fsp_passport": passports,
        "grade_passports": grade_passports,
        "push_subscriptions": [{"user_agent": ua, "created_at": _j(c), "last_success_at": _j(ls)} for ua, c, ls in pushes],
        "interest": interest.summary(db, uid),
    }
    # раздел заданий работодателей — отдельной таблицей, чтобы не потерять при обходе «прочего»
    from app.modules.assignments.models import AssignmentAttempt

    data["assignments"] = _rows(db, AssignmentAttempt, AssignmentAttempt.candidate_user_id == uid,
                                skip=("id", "candidate_user_id", "tasks"))
    covered |= {"assignment_attempts"}
    data["other"] = _other(db, uid, covered)
    return data
