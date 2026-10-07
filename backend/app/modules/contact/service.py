"""Переписка, встречное предложение и отзыв доступа к контактам: правила (покрыты tests/test_contact.py).

Переписка
* Тред — приглашение или отклик на вакансию. Доступ — только двум сторонам: кандидату-адресату и работодателям
  компании; остальным — 404 (как будто треда нет).
* До принятия приглашения (и после отзыва доступа к контактам) — режим «вопрос — ответ» (qa): кандидат обезличен,
  контакты в тексте обеих сторон маскируются при сохранении, не больше QA_MAX_IN_ROW сообщений подряд без ответа
  и не больше QA_MAX_PER_SIDE сообщений одной стороны, до QA_MAX_LEN символов.
* После принятия и по отклику (кандидат сам раскрыл контакты компании) — обычный чат (chat), до CHAT_MAX_LEN.
* Закрытое приглашение (отклонено, отозвано, истекло, есть жалоба) и отозванный или отклонённый отклик —
  только чтение.
* От спама: не больше RATE_10MIN сообщений за 10 минут и RATE_DAY за сутки от одного пользователя по всем тредам
  (счёт по БД — одинаково при нескольких воркерах), повтор того же текста подряд — 409.
* Непрочитанные — сообщения другой стороны без read_at; открытие треда отмечает их прочитанными.

Встречное предложение
* Кандидат отвечает на открытое приглашение своей вилкой: ширина ≤ 1,5 (как у всех вилок), выше предложенной
  хотя бы одной границей, «от» — не выше COUNTER_MAX_UP × «до» приглашения (в одном основании НДФЛ).
  Одно ожидающее и не больше COUNTER_MAX встречных на приглашение.
* Работодатель принимает → вилка приглашения заменяется встречной (исходная — в истории), приглашение принято,
  контакты открыты: кандидат согласился на это, отправляя встречное. Отклоняет → приглашение остаётся открытым
  с исходной вилкой, кандидат может принять, отклонить или предложить ещё раз (в пределах лимита).

Отзыв доступа
* Кандидат после принятия может отозвать доступ к контактам: работодатель снова видит обезличенную карточку
  (контакты, PDF, ATS — закрыты), статус «доступ отозван». Вернуть доступ может только кандидат.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import uuid

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.enums import InvitationStatus, UserRole
from app.core.errors import api_error
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.auth.models import User
from app.modules.contact.masking import mask_contacts
from app.modules.contact.models import ContactMessage, InvitationCounter
from app.modules.contact.salary import basis_title, convert
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation, InvitationComplaint, InvitationEvent
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile

QA_MAX_IN_ROW = 2
QA_MAX_PER_SIDE = 10
QA_MAX_LEN = 1000
CHAT_MAX_LEN = 4000
RATE_10MIN = 20
RATE_DAY = 200
COUNTER_MAX = 2
COUNTER_MAX_UP = 1.5
OPEN = (InvitationStatus.sent, InvitationStatus.viewed)
KINDS = ("invitation", "application")


def rub(v: int) -> str:
    return f"{v:,}".replace(",", "\u00a0") + "\u00a0₽"


def rng(a: int, b: int, basis: str | None = None) -> str:
    return f"{rub(a)} – {rub(b)}" + (f" {basis_title(basis)}" if basis else "")


# ------------------------------------------------------------------ треды и доступ

@dataclass
class Thread:
    kind: str  # invitation | application
    id: uuid.UUID
    side: str  # candidate | employer — сторона текущего пользователя
    candidate_user_id: uuid.UUID
    company: Company
    title: str
    invitation: Invitation | None = None
    application: VacancyApplication | None = None
    vacancy: Vacancy | None = None

    @property
    def counterpart_side(self) -> str:
        return "employer" if self.side == "candidate" else "candidate"


def _company_of(db: Session, user: User) -> Company | None:
    ep = db.get(EmployerProfile, user.id)
    return db.get(Company, ep.company_id) if ep and ep.company_id else None


def resolve(db: Session, user: User, kind: str, tid: uuid.UUID) -> Thread:
    """Тред для текущего пользователя или 404 — и для чужих, и для несуществующих."""
    nf = api_error(404, "thread_not_found", "Переписка не найдена")
    if kind not in KINDS or user.role not in (UserRole.candidate, UserRole.employer):
        raise nf
    comp = _company_of(db, user) if user.role == UserRole.employer else None
    if kind == "invitation":
        i = db.get(Invitation, tid)
        if i is None:
            raise nf
        if user.role == UserRole.candidate and i.candidate_user_id == user.id:
            side = "candidate"
        elif comp is not None and i.company_id == comp.id:
            side = "employer"
        else:
            raise nf
        return Thread("invitation", i.id, side, i.candidate_user_id, db.get(Company, i.company_id),
                      i.position_title, invitation=i)
    a = db.get(VacancyApplication, tid)
    v = db.get(Vacancy, a.vacancy_id) if a else None
    if a is None or v is None:
        raise nf
    if user.role == UserRole.candidate and a.candidate_user_id == user.id:
        side = "candidate"
    elif comp is not None and v.company_id == comp.id:
        side = "employer"
    else:
        raise nf
    return Thread("application", a.id, side, a.candidate_user_id, db.get(Company, v.company_id), v.title,
                  application=a, vacancy=v)


def _complained(db: Session, inv: Invitation) -> bool:
    return db.scalar(select(InvitationComplaint.id).where(InvitationComplaint.invitation_id == inv.id)) is not None


def thread_state(db: Session, t: Thread) -> dict:
    """mode (qa | chat), можно ли писать и почему нет."""
    if t.invitation is not None:
        i = t.invitation
        mode = "chat" if i.status == InvitationStatus.accepted and i.contacts_revealed_at else "qa"
        closed = None
        if i.status in (InvitationStatus.declined, InvitationStatus.withdrawn, InvitationStatus.expired):
            closed = {"declined": "Приглашение отклонено — переписка только для чтения",
                      "withdrawn": "Работодатель отозвал приглашение — переписка только для чтения",
                      "expired": "Срок приглашения истёк — переписка только для чтения"}[i.status.value]
        elif _complained(db, i):
            closed = "Кандидат пожаловался на приглашение — переписка только для чтения"
        return {"mode": mode, "closed": closed, "revoked": bool(i.contacts_revoked_at)}
    a = t.application
    closed = {"withdrawn": "Кандидат отозвал отклик — переписка только для чтения",
              "rejected": "Работодатель отказал по отклику — переписка только для чтения"}.get(a.status)
    return {"mode": "chat", "closed": closed, "revoked": False}


def _thread_filter(t: Thread):
    return (ContactMessage.invitation_id == t.id) if t.kind == "invitation" else (ContactMessage.application_id == t.id)


def messages_of(db: Session, t: Thread) -> list[ContactMessage]:
    return list(db.scalars(select(ContactMessage).where(_thread_filter(t)).order_by(ContactMessage.created_at)).all())


def message_out(m: ContactMessage, side: str) -> dict:
    return {"id": str(m.id), "side": m.sender_side, "mine": m.sender_side == side, "body": m.body, "mode": m.mode,
            "masked": m.masked, "at": m.created_at.isoformat(),
            "read_at": m.read_at.isoformat() if m.read_at else None}


def mark_read(db: Session, t: Thread) -> int:
    now = utcnow()
    rows = db.scalars(select(ContactMessage).where(_thread_filter(t), ContactMessage.sender_side == t.counterpart_side,
                                                   ContactMessage.read_at.is_(None))).all()
    for m in rows:
        m.read_at = now
    if rows:
        db.commit()
    return len(rows)


def limits(db: Session, t: Thread, msgs: list[ContactMessage] | None = None) -> dict:
    """Что ещё можно отправить в режиме qa (для подсказки в интерфейсе)."""
    st = thread_state(db, t)
    msgs = messages_of(db, t) if msgs is None else msgs
    mine = [m for m in msgs if m.sender_side == t.side]
    in_row = 0
    for m in reversed(msgs):
        if m.sender_side != t.side:
            break
        in_row += 1
    out = {"mode": st["mode"], "max_len": QA_MAX_LEN if st["mode"] == "qa" else CHAT_MAX_LEN,
           "can_write": st["closed"] is None, "reason": st["closed"], "revoked": st["revoked"]}
    if st["mode"] == "qa" and out["can_write"]:
        out["left"] = max(0, QA_MAX_PER_SIDE - len(mine))
        out["in_row"] = in_row
        if len(mine) >= QA_MAX_PER_SIDE:
            out.update(can_write=False, reason=f"До принятия приглашения — не больше {QA_MAX_PER_SIDE} сообщений "
                                               "с каждой стороны. Остальное — после принятия")
        elif in_row >= QA_MAX_IN_ROW:
            out.update(can_write=False, reason="До принятия приглашения — формат «вопрос — ответ»: дождитесь "
                                               "ответа, прежде чем писать снова")
    return out


def send(db: Session, user: User, t: Thread, body: str) -> ContactMessage:
    text = (body or "").strip()
    if not text:
        raise api_error(422, "message_empty", "Напишите сообщение")
    lim = limits(db, t)
    if not lim["can_write"]:
        raise api_error(409, "thread_closed" if thread_state(db, t)["closed"] else "qa_limit", lim["reason"])
    if len(text) > lim["max_len"]:
        raise api_error(422, "message_too_long", f"Сообщение длиннее {lim['max_len']} символов")
    now = utcnow()
    sent_10 = db.scalar(select(func.count()).select_from(ContactMessage).where(
        ContactMessage.sender_user_id == user.id, ContactMessage.created_at > now - timedelta(minutes=10)))
    sent_day = db.scalar(select(func.count()).select_from(ContactMessage).where(
        ContactMessage.sender_user_id == user.id, ContactMessage.created_at > now - timedelta(days=1)))
    if sent_10 >= RATE_10MIN or sent_day >= RATE_DAY:
        raise api_error(429, "messages_rate", "Слишком много сообщений подряд — попробуйте через несколько минут")
    masked = 0
    if lim["mode"] == "qa":
        text, masked = mask_contacts(text)
    last_mine = db.scalar(select(ContactMessage).where(_thread_filter(t), ContactMessage.sender_side == t.side)
                          .order_by(ContactMessage.created_at.desc()).limit(1))
    if last_mine is not None and last_mine.body.strip().lower() == text.lower() \
            and as_aware(last_mine.created_at) > now - timedelta(minutes=10):
        raise api_error(409, "message_duplicate", "Такое сообщение вы только что отправили")
    m = ContactMessage(invitation_id=t.id if t.kind == "invitation" else None,
                       application_id=t.id if t.kind == "application" else None, sender_user_id=user.id,
                       sender_side=t.side, mode=lim["mode"], body=text, masked=masked)
    db.add(m)
    db.commit()
    return m


def unread_before(db: Session, t: Thread, m: ContactMessage) -> int:
    """Сколько непрочитанных сообщений этой стороны было до m (письмо — только на первое непрочитанное)."""
    return db.scalar(select(func.count()).select_from(ContactMessage).where(
        _thread_filter(t), ContactMessage.sender_side == m.sender_side, ContactMessage.read_at.is_(None),
        ContactMessage.id != m.id))


def recipients(db: Session, t: Thread) -> list[User]:
    """Кому уведомление о сообщении: кандидату — ему; работодателю — автору приглашения или вакансии
    (если его нет — всем работодателям компании)."""
    if t.side == "employer":
        u = db.get(User, t.candidate_user_id)
        return [u] if u else []
    owner = t.invitation.employer_user_id if t.invitation is not None else t.vacancy.created_by
    if owner and db.get(User, owner):
        return [db.get(User, owner)]
    ids = db.scalars(select(EmployerProfile.user_id).where(EmployerProfile.company_id == t.company.id)).all()
    return [u for u in (db.get(User, x) for x in ids) if u]


def counterpart_title(db: Session, t: Thread, for_side: str) -> str:
    """Как сторона for_side видит собеседника: кандидату — компания; работодателю — обезличенный «Кандидат C-…»,
    а имя — только пока контакты открыты (отклик на вакансию; принятое приглашение без отзыва доступа)."""
    if for_side == "candidate":
        return t.company.name if t.company else "Компания"
    p = db.get(CandidateProfile, t.candidate_user_id)
    if p is None:
        return "Кандидат"
    st = thread_state(db, t)
    if st["mode"] == "chat" and not st["revoked"] and p.full_name:
        return p.full_name
    return f"Кандидат {p.public_ref}"


def unread_counts(db: Session, user: User) -> dict:
    """Непрочитанные сообщения по всем тредам пользователя."""
    inv_q, app_q = _thread_ids(db, user)
    if inv_q is None:
        return {"total": 0, "invitations": 0, "applications": 0}
    other = "employer" if user.role == UserRole.candidate else "candidate"
    n_inv = db.scalar(select(func.count()).select_from(ContactMessage).where(
        ContactMessage.invitation_id.in_(inv_q), ContactMessage.sender_side == other, ContactMessage.read_at.is_(None)))
    n_app = db.scalar(select(func.count()).select_from(ContactMessage).where(
        ContactMessage.application_id.in_(app_q), ContactMessage.sender_side == other,
        ContactMessage.read_at.is_(None)))
    return {"total": n_inv + n_app, "invitations": n_inv, "applications": n_app}


def _thread_ids(db: Session, user: User):
    if user.role == UserRole.candidate:
        return (select(Invitation.id).where(Invitation.candidate_user_id == user.id,
                                            Invitation.status != InvitationStatus.withdrawn),
                select(VacancyApplication.id).where(VacancyApplication.candidate_user_id == user.id))
    comp = _company_of(db, user) if user.role == UserRole.employer else None
    if comp is None:
        return None, None
    return (select(Invitation.id).where(Invitation.company_id == comp.id),
            select(VacancyApplication.id).join(Vacancy, Vacancy.id == VacancyApplication.vacancy_id)
            .where(Vacancy.company_id == comp.id))


def threads(db: Session, user: User) -> list[dict]:
    """Все треды пользователя с сообщениями или открытые для переписки, по последней активности."""
    inv_q, app_q = _thread_ids(db, user)
    if inv_q is None:
        return []
    side = "candidate" if user.role == UserRole.candidate else "employer"
    out = []
    for kind, ids in (("invitation", db.scalars(inv_q).all()), ("application", db.scalars(app_q).all())):
        if not ids:
            continue
        col = ContactMessage.invitation_id if kind == "invitation" else ContactMessage.application_id
        stats = {r[0]: r for r in db.execute(
            select(col, func.count(), func.max(ContactMessage.created_at),
                   func.sum(case((and_(ContactMessage.sender_side != side, ContactMessage.read_at.is_(None)), 1),
                                 else_=0)))
            .where(col.in_(ids)).group_by(col)).all()}
        for tid in ids:
            t = resolve(db, user, kind, tid)
            st = thread_state(db, t)
            s = stats.get(tid)
            if s is None and st["closed"]:
                continue  # закрытый тред без сообщений не показываем
            last = db.scalar(select(ContactMessage).where(col == tid).order_by(ContactMessage.created_at.desc())
                             .limit(1)) if s else None
            status = (t.invitation.status.value if t.invitation is not None else t.application.status)
            created = (t.invitation.created_at if t.invitation is not None else t.application.created_at)
            out.append({
                "kind": kind, "id": str(tid), "title": t.title, "counterpart": counterpart_title(db, t, side),
                "status": status, "mode": st["mode"], "closed": st["closed"], "revoked": st["revoked"],
                "messages": s[1] if s else 0, "unread": int(s[3] or 0) if s else 0,
                "last": message_out(last, side) if last else None,
                "activity_at": as_aware(s[2] if s else created).isoformat(),
            })
    out.sort(key=lambda x: x["activity_at"], reverse=True)
    return out


def thread_out(db: Session, t: Thread) -> dict:
    msgs = messages_of(db, t)
    lim = limits(db, t, msgs)
    out = {"kind": t.kind, "id": str(t.id), "title": t.title, "side": t.side,
           "counterpart": counterpart_title(db, t, t.side), "company": t.company.name if t.company else None,
           "messages": [message_out(m, t.side) for m in msgs], **lim,
           "rules": {"qa_max_in_row": QA_MAX_IN_ROW, "qa_max_per_side": QA_MAX_PER_SIDE}}
    if t.invitation is not None:
        out["status"] = t.invitation.status.value
    else:
        out["status"] = t.application.status
    return out


def thread_summary(db: Session, inv: Invitation, side: str) -> dict:
    """Короткая сводка переписки для карточки приглашения."""
    return _summary(db, ContactMessage.invitation_id == inv.id, side)


def application_thread_summary(db: Session, app_id: uuid.UUID, side: str) -> dict:
    """То же для отклика на вакансию (integrations.vacancies.router._app_out)."""
    return _summary(db, ContactMessage.application_id == app_id, side)


def _summary(db: Session, cond, side: str) -> dict:
    msgs = db.scalars(select(ContactMessage).where(cond)).all()
    other = "employer" if side == "candidate" else "candidate"
    return {"total": len(msgs), "unread": sum(1 for m in msgs if m.sender_side == other and m.read_at is None)}


# ------------------------------------------------------------------ встречное предложение

def _log(db: Session, inv: Invitation, kind: str, actor: uuid.UUID | None, note: str | None = None) -> None:
    db.add(InvitationEvent(invitation_id=inv.id, from_status=inv.status, to_status=inv.status, actor_user_id=actor,
                           note=note, kind=kind))


def pending_counter(db: Session, inv: Invitation) -> InvitationCounter | None:
    return db.scalar(select(InvitationCounter).where(InvitationCounter.invitation_id == inv.id,
                                                     InvitationCounter.status == "pending").limit(1))


def counters_of(db: Session, inv: Invitation) -> list[InvitationCounter]:
    return list(db.scalars(select(InvitationCounter).where(InvitationCounter.invitation_id == inv.id)
                           .order_by(InvitationCounter.created_at)).all())


def counter_out(c: InvitationCounter) -> dict:
    return {"id": str(c.id), "status": c.status, "salary_from": c.salary_from, "salary_to": c.salary_to,
            "salary_basis": c.salary_basis, "salary_basis_title": basis_title(c.salary_basis),
            "offer_from": c.offer_from, "offer_to": c.offer_to, "comment": c.comment,
            "employer_note": c.employer_note, "created_at": c.created_at.isoformat(),
            "decided_at": c.decided_at.isoformat() if c.decided_at else None}


def create_counter(db: Session, inv: Invitation, actor: uuid.UUID, salary_from: int, salary_to: int, basis: str,
                   comment: str | None) -> InvitationCounter:
    if inv.status not in OPEN:
        raise api_error(409, "invitation_closed", "На это приглашение уже нельзя ответить")
    if pending_counter(db, inv) is not None:
        raise api_error(409, "counter_pending", "Встречное предложение уже отправлено — дождитесь ответа работодателя")
    if len(counters_of(db, inv)) >= COUNTER_MAX:
        raise api_error(409, "counter_limit", f"Встречных предложений на одно приглашение — не больше {COUNTER_MAX}")
    inv_svc.check_salary(salary_from, salary_to)  # ширина ≤ 1,5 — то же правило, что у приглашений
    ib = inv.salary_basis or "gross"
    lo, hi = convert(salary_from, basis, ib), convert(salary_to, basis, ib)
    if lo <= inv.salary_from and hi <= inv.salary_to:
        raise api_error(422, "counter_not_higher",
                        "Встречная вилка не выше предложенной — если она вас устраивает, просто примите приглашение")
    cap = int(COUNTER_MAX_UP * inv.salary_to)
    if lo > cap:
        cap_b = convert(cap, ib, basis) // 1000 * 1000
        raise api_error(422, "counter_too_far",
                        f"Встречное «от» — не выше {rub(cap_b)} {basis_title(basis)} (1,5 × «до» приглашения): "
                        "иначе это уже другое предложение")
    if inv.viewed_at is None:
        inv.viewed_at = utcnow()
        inv_svc._event(db, inv, InvitationStatus.viewed, actor)
    c = InvitationCounter(invitation_id=inv.id, candidate_user_id=inv.candidate_user_id, salary_from=salary_from,
                          salary_to=salary_to, salary_basis=basis, offer_from=inv.salary_from, offer_to=inv.salary_to,
                          comment=(comment or "").strip() or None, status="pending")
    db.add(c)
    _log(db, inv, "counter_sent", actor, rng(salary_from, salary_to, basis) + (f" · {c.comment}" if c.comment else ""))
    db.commit()
    return c


def accept_counter(db: Session, inv: Invitation, actor: uuid.UUID, note: str | None) -> InvitationCounter:
    c = pending_counter(db, inv)
    if c is None:
        raise api_error(409, "counter_not_pending", "Нет встречного предложения, ожидающего ответа")
    if inv.status not in OPEN:
        raise api_error(409, "invitation_closed", "Приглашение уже закрыто")
    now = utcnow()
    c.status, c.decided_by, c.decided_at, c.employer_note = "accepted", actor, now, (note or "").strip() or None
    _log(db, inv, "counter_accepted", actor,
         f"Было {rng(c.offer_from, c.offer_to, inv.salary_basis)}, стало {rng(c.salary_from, c.salary_to, c.salary_basis)}")
    inv.salary_from, inv.salary_to, inv.salary_basis = c.salary_from, c.salary_to, c.salary_basis
    inv.responded_at = now
    inv.contacts_revealed_at = now
    inv.contacts_revoked_at = None
    inv_svc._event(db, inv, InvitationStatus.accepted, actor, "Принято на условиях встречного предложения кандидата")
    db.commit()
    return c


def decline_counter(db: Session, inv: Invitation, actor: uuid.UUID, note: str | None) -> InvitationCounter:
    c = pending_counter(db, inv)
    if c is None:
        raise api_error(409, "counter_not_pending", "Нет встречного предложения, ожидающего ответа")
    c.status, c.decided_by, c.decided_at, c.employer_note = "declined", actor, utcnow(), (note or "").strip() or None
    _log(db, inv, "counter_declined", actor, c.employer_note)
    db.commit()
    return c


def close_pending_counter(db: Session, inv: Invitation, actor: uuid.UUID | None) -> None:
    """Кандидат принял исходную вилку или отклонил приглашение, работодатель отозвал — ожидающее встречное
    закрывается (без commit: вызывающий коммитит вместе со сменой статуса)."""
    c = pending_counter(db, inv)
    if c is not None:
        c.status, c.decided_at = "withdrawn", utcnow()
        _log(db, inv, "counter_withdrawn", actor)


# ------------------------------------------------------------------ отзыв доступа к контактам

def revoke_contacts(db: Session, inv: Invitation, actor: uuid.UUID) -> Invitation:
    if inv.status != InvitationStatus.accepted:
        raise api_error(409, "not_accepted", "Отозвать доступ можно только по принятому приглашению")
    if inv.contacts_revealed_at is None:
        raise api_error(409, "already_revoked", "Доступ к контактам уже отозван")
    inv.contacts_revealed_at = None
    inv.contacts_revoked_at = utcnow()
    _log(db, inv, "contacts_revoked", actor)
    db.commit()
    return inv


def restore_contacts(db: Session, inv: Invitation, actor: uuid.UUID) -> Invitation:
    if inv.status != InvitationStatus.accepted or inv.contacts_revoked_at is None:
        raise api_error(409, "not_revoked", "Доступ к контактам не отзывался")
    inv.contacts_revealed_at = utcnow()
    inv.contacts_revoked_at = None
    _log(db, inv, "contacts_restored", actor)
    db.commit()
    return inv


def invitation_extras(db: Session, inv: Invitation, side: str) -> dict:
    """Поля для карточки приглашения (invitations.router._inv_out): основание суммы, встречные, доступ, переписка."""
    cs = counters_of(db, inv)
    pend = next((c for c in cs if c.status == "pending"), None)
    out = {"salary_basis": inv.salary_basis or "gross", "salary_basis_title": basis_title(inv.salary_basis),
           "counter": counter_out(pend) if pend else None, "counters": [counter_out(c) for c in cs],
           "counters_left": max(0, COUNTER_MAX - len(cs)),
           "contacts_revoked": inv.contacts_revoked_at is not None,
           "contacts_revoked_at": inv.contacts_revoked_at.isoformat() if inv.contacts_revoked_at else None,
           "thread": thread_summary(db, inv, side)}
    return out
