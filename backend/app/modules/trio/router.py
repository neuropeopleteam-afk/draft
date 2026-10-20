"""Трёхсторонняя связь (работодатель ↔ кандидат ↔ представитель ФСП): API.

Правила
* Канал — по одному приглашению. Создать может работодатель компании-отправителя или кандидат-адресат.
* Кандидат сам позвал ФСП — канал сразу активен. Позвал работодатель — канал «ждёт согласия кандидата»:
  до согласия представитель ФСП тред не видит, писать могут только кандидат и работодатель.
* Представитель ФСП — роль fsp_analyst (и admin): видит активные и закрытые каналы, пишет в активные.
  Кандидат для него и для работодателя обезличен (Кандидат C-…), пока приглашение не принято с раскрытием контактов;
  до этого контакты в тексте всех сторон маскируются при сохранении (как в переписке «вопрос — ответ»).
* Закрыть канал может любой участник — дальше только чтение. Лимит от спама — 20 сообщений за 10 минут.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, get_db, utcnow
from app.core.deps import get_current_user
from app.core.enums import InvitationStatus, UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.contact.masking import mask_contacts
from app.modules.invitations.models import Invitation
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.trio.models import TrioMessage, TrioThread

TAGS = [{"name": "trio", "description": "Трёхсторонняя связь по приглашению: работодатель ↔ кандидат ↔ представитель "
                                        "ФСП (согласие кандидата, маскировка контактов до принятия)"}]
router = APIRouter(prefix="/api/trio", tags=["trio"])
AUTH = {401: err("Не выполнен вход"), 404: err("Канал не найден или недоступен")}
MAX_LEN = 2000
RATE_10MIN = 20
TOPICS = {
    "general": "Общий вопрос",
    "fsp_check": "Подтвердить результаты ФСП",
    "offer": "Условия оффера и вилка",
    "dispute": "Спорная ситуация",
    "internship": "Стажировка и наставник от ФСП",
    "appeal": "Апелляция по заданию теста",
}
STATUS_TITLE = {"pending": "Ждёт согласия кандидата", "active": "Активен — пишут все трое", "closed": "Закрыт — только чтение"}
SIDE_TITLE = {"candidate": "Кандидат", "employer": "Работодатель", "fsp": "Представитель ФСП", "system": "Платформа"}
FSP_ROLES = (UserRole.fsp_analyst, UserRole.admin)


class CreateIn(BaseModel):
    invitation_id: uuid.UUID
    topic: Literal["general", "fsp_check", "offer", "dispute", "internship", "appeal"] = "general"
    body: str | None = Field(None, max_length=MAX_LEN, description="Первое сообщение (необязательно)")


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_LEN)


def _company_id(db: Session, user: User) -> uuid.UUID | None:
    ep = db.get(EmployerProfile, user.id)
    return ep.company_id if ep else None


def _side(db: Session, user: User, t: TrioThread) -> str | None:
    if user.role == UserRole.candidate and t.candidate_user_id == user.id:
        return "candidate"
    if user.role == UserRole.employer and _company_id(db, user) == t.company_id:
        return "employer"
    if user.role in FSP_ROLES and t.status != "pending":
        return "fsp"
    return None


def _open(inv: Invitation) -> bool:
    return bool(inv.status == InvitationStatus.accepted and inv.contacts_revealed_at and not inv.contacts_revoked_at)


def _candidate_title(db: Session, t: TrioThread, inv: Invitation | None) -> str:
    p = db.get(CandidateProfile, t.candidate_user_id)
    if p is None:
        return "Кандидат"
    if inv is not None and _open(inv) and p.full_name and not p.deleted_at:
        return p.full_name
    return f"Кандидат {p.public_ref}" if p.public_ref else "Кандидат"


def _trio_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.candidate, UserRole.employer, *FSP_ROLES):
        raise api_error(403, "forbidden", "Недостаточно прав")
    return user


def _party_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.candidate, UserRole.employer):
        raise api_error(403, "forbidden", "Только для кандидата или работодателя")
    return user


def _cand_user(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.candidate:
        raise api_error(403, "forbidden", "Согласие даёт только кандидат")
    return user


def _resolve(db: Session, user: User, tid: uuid.UUID) -> tuple[TrioThread, str]:
    t = db.get(TrioThread, tid)
    side = _side(db, user, t) if t else None
    if t is None or side is None:
        raise api_error(404, "trio_not_found", "Канал не найден")
    return t, side


def _resolve_dep(tid: uuid.UUID, user: User = Depends(_trio_user),
                 db: Session = Depends(get_db)) -> tuple[TrioThread, str, User]:
    t, side = _resolve(db, user, tid)
    return t, side, user


def _msg_out(m: TrioMessage, side: str) -> dict:
    return {"id": str(m.id), "side": m.sender_side, "side_title": SIDE_TITLE.get(m.sender_side, m.sender_side),
            "mine": m.sender_side == side, "body": m.body, "masked": m.masked, "at": as_aware(m.created_at).isoformat()}


def _thread_out(db: Session, t: TrioThread, side: str, full: bool = False) -> dict:
    inv = db.get(Invitation, t.invitation_id)
    comp = db.get(Company, t.company_id)
    msgs = list(db.scalars(select(TrioMessage).where(TrioMessage.thread_id == t.id).order_by(TrioMessage.created_at)).all())
    last = msgs[-1] if msgs else None
    can_write = t.status == "active" or (t.status == "pending" and side in ("candidate", "employer"))
    out = {
        "id": str(t.id), "invitation_id": str(t.invitation_id), "status": t.status, "status_title": STATUS_TITLE[t.status],
        "topic": t.topic, "topic_title": TOPICS.get(t.topic, t.topic), "side": side,
        "position": inv.position_title if inv else "", "company": comp.name if comp else "Компания",
        "candidate": _candidate_title(db, t, inv), "contacts_open": bool(inv and _open(inv)),
        "invitation_status": inv.status.value if inv else None,
        "participants": [
            {"side": "employer", "title": comp.name if comp else "Работодатель", "joined": True},
            {"side": "candidate", "title": _candidate_title(db, t, inv), "joined": True},
            {"side": "fsp", "title": "Представитель ФСП", "joined": t.status != "pending"},
        ],
        "created_by_side": t.created_by_side, "needs_my_consent": t.status == "pending" and side == "candidate",
        "can_write": can_write, "messages_count": len(msgs),
        "last": _msg_out(last, side) if last else None,
        "activity_at": as_aware(last.created_at if last else t.created_at).isoformat(),
    }
    if full:
        out["messages"] = [_msg_out(m, side) for m in msgs]
    return out


def _system(db: Session, t: TrioThread, text: str) -> None:
    db.add(TrioMessage(thread_id=t.id, sender_side="system", body=text))


def _post(db: Session, user: User, t: TrioThread, side: str, body: str) -> TrioMessage:
    text = (body or "").strip()
    if not text:
        raise api_error(422, "message_empty", "Напишите сообщение")
    if t.status == "closed":
        raise api_error(409, "trio_closed", "Канал закрыт — только чтение")
    if t.status == "pending" and side == "fsp":
        raise api_error(409, "trio_pending", "Кандидат ещё не согласился подключить ФСП")
    n = db.scalar(select(func.count()).select_from(TrioMessage).where(
        TrioMessage.sender_user_id == user.id, TrioMessage.created_at > utcnow() - timedelta(minutes=10)))
    if n >= RATE_10MIN:
        raise api_error(429, "messages_rate", "Слишком много сообщений подряд — попробуйте через несколько минут")
    inv = db.get(Invitation, t.invitation_id)
    masked = 0
    if not (inv and _open(inv)):
        text, masked = mask_contacts(text)
    m = TrioMessage(thread_id=t.id, sender_user_id=user.id, sender_side=side, body=text, masked=masked)
    db.add(m)
    db.commit()
    return m


def _notify(bg: BackgroundTasks, db: Session, t: TrioThread, from_side: str, body: str) -> None:
    try:
        from app.integrations.push.service import notify_user
    except Exception:  # noqa: BLE001 — push необязателен
        return
    targets: list[tuple[uuid.UUID, str]] = []
    if from_side != "candidate":
        targets.append((t.candidate_user_id, "/candidate/trio"))
    if from_side != "employer":
        inv = db.get(Invitation, t.invitation_id)
        if inv and inv.employer_user_id:
            targets.append((inv.employer_user_id, "/employer/trio"))
    if t.status == "active" and from_side != "fsp":
        for fsp_uid in db.scalars(select(User.id).where(User.role == UserRole.fsp_analyst, User.is_active.is_(True))).all():
            targets.append((fsp_uid, "/fsp/trio"))
    for uid, path in targets:
        bg.add_task(notify_user, uid, f"Трёхсторонний канал: {SIDE_TITLE.get(from_side, from_side)}", body[:160],
                    f"{path}?t={t.id}", f"trio-{t.id}")


@router.get("/unread", summary="Число трёхсторонних каналов, требующих внимания или согласия", responses=AUTH)
def unread(user: User = Depends(_trio_user), db: Session = Depends(get_db)) -> dict:
    q = select(TrioThread)
    if user.role == UserRole.candidate:
        q = q.where(TrioThread.candidate_user_id == user.id)
    elif user.role == UserRole.employer:
        cid = _company_id(db, user)
        if cid is None:
            return {"total": 0, "pending_consent": 0}
        q = q.where(TrioThread.company_id == cid)
    elif user.role in FSP_ROLES:
        q = q.where(TrioThread.status != "pending")
    else:
        return {"total": 0, "pending_consent": 0}
    total = 0
    pending_consent = 0
    for t in db.scalars(q).all():
        side = _side(db, user, t) or "fsp"
        if t.status == "pending" and side == "candidate":
            pending_consent += 1
            total += 1
            continue
        if t.status == "active":
            last = db.scalar(select(TrioMessage).where(
                TrioMessage.thread_id == t.id, TrioMessage.sender_side != "system"
            ).order_by(TrioMessage.created_at.desc()).limit(1))
            if last is not None and last.sender_side != side:
                total += 1
    return {"total": total, "pending_consent": pending_consent}


@router.get("/meta", summary="Темы канала и правила трёхсторонней связи")
def meta() -> dict:
    return {"topics": [{"id": k, "title": v} for k, v in TOPICS.items()], "max_len": MAX_LEN,
            "rules": ["Кандидат сам решает, подключать ли ФСП: канал от работодателя ждёт его согласия.",
                      "До принятия приглашения кандидат обезличен, контакты в тексте маскируются.",
                      "Представитель ФСП подтверждает результаты соревнований, помогает с условиями и спорами.",
                      "Любой участник может закрыть канал — дальше только чтение."]}


@router.get("/threads", summary="Мои трёхсторонние каналы", responses=AUTH)
def threads(user: User = Depends(_trio_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(TrioThread)
    if user.role == UserRole.candidate:
        q = q.where(TrioThread.candidate_user_id == user.id)
    elif user.role == UserRole.employer:
        cid = _company_id(db, user)
        if cid is None:
            return []
        q = q.where(TrioThread.company_id == cid)
    elif user.role in FSP_ROLES:
        q = q.where(TrioThread.status != "pending")
    else:
        return []
    rows = [_thread_out(db, t, _side(db, user, t) or "fsp") for t in db.scalars(q).all()]
    rows.sort(key=lambda r: r["activity_at"], reverse=True)
    return rows


@router.get("/eligible", summary="Приглашения, по которым можно открыть канал с ФСП", responses=AUTH)
def eligible(user: User = Depends(_party_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Invitation).where(Invitation.status.in_(
        (InvitationStatus.sent, InvitationStatus.viewed, InvitationStatus.accepted)))
    if user.role == UserRole.candidate:
        q = q.where(Invitation.candidate_user_id == user.id)
    elif user.role == UserRole.employer:
        cid = _company_id(db, user)
        if cid is None:
            return []
        q = q.where(Invitation.company_id == cid)
    else:
        return []
    taken = set(db.scalars(select(TrioThread.invitation_id)).all())
    out = []
    for i in db.scalars(q.order_by(Invitation.created_at.desc()).limit(50)).all():
        if i.id in taken:
            continue
        comp = db.get(Company, i.company_id)
        p = db.get(CandidateProfile, i.candidate_user_id)
        who = (comp.name if comp else "Компания") if user.role == UserRole.candidate else \
            (p.full_name if p and _open(i) and p.full_name else f"Кандидат {p.public_ref if p else ''}".strip())
        out.append({"invitation_id": str(i.id), "position": i.position_title, "counterpart": who,
                    "status": i.status.value})
    return out


@router.post("/threads", status_code=201, summary="Подключить представителя ФСП к приглашению",
             responses={**AUTH, 409: err("Канал по этому приглашению уже есть")})
def create(data: CreateIn, bg: BackgroundTasks, user: User = Depends(_party_user),
           db: Session = Depends(get_db)) -> dict:
    inv = db.get(Invitation, data.invitation_id)
    nf = api_error(404, "invitation_not_found", "Приглашение не найдено")
    if inv is None:
        raise nf
    if user.role == UserRole.candidate and inv.candidate_user_id == user.id:
        side = "candidate"
    elif user.role == UserRole.employer and _company_id(db, user) == inv.company_id:
        side = "employer"
    else:
        raise nf
    ex = db.scalar(select(TrioThread).where(TrioThread.invitation_id == inv.id))
    if ex is not None:
        return _thread_out(db, ex, side, full=True)
    now = utcnow()
    t = TrioThread(invitation_id=inv.id, company_id=inv.company_id, candidate_user_id=inv.candidate_user_id,
                   topic=data.topic, created_by_side=side, created_by=user.id,
                   status="active" if side == "candidate" else "pending", activated_at=now if side == "candidate" else None)
    db.add(t)
    db.flush()
    _system(db, t, "Кандидат подключил представителя ФСП к переписке." if side == "candidate"
            else "Работодатель предложил подключить представителя ФСП. Канал откроется для ФСП после согласия кандидата.")
    db.commit()
    if data.body and data.body.strip():
        _post(db, user, t, side, data.body)
    _notify(bg, db, t, side, "Открыт трёхсторонний канал с представителем ФСП")
    db.refresh(t)
    return _thread_out(db, t, side, full=True)


@router.get("/threads/{tid}", summary="Канал и сообщения", responses=AUTH)
def get_thread(resolved: tuple[TrioThread, str, User] = Depends(_resolve_dep),
               db: Session = Depends(get_db)) -> dict:
    t, side, _ = resolved
    return _thread_out(db, t, side, full=True)


@router.post("/threads/{tid}/messages", status_code=201, summary="Написать в канал",
             responses={**AUTH, 409: err("Канал закрыт или ждёт согласия кандидата"), 429: err("Слишком много сообщений")})
def post_message(data: MessageIn, bg: BackgroundTasks,
                 resolved: tuple[TrioThread, str, User] = Depends(_resolve_dep),
                 db: Session = Depends(get_db)) -> dict:
    t, side, user = resolved
    m = _post(db, user, t, side, data.body)
    _notify(bg, db, t, side, m.body)
    return _thread_out(db, t, side, full=True)


@router.post("/threads/{tid}/consent", summary="Кандидат соглашается подключить ФСП", responses=AUTH)
def consent(tid: uuid.UUID, bg: BackgroundTasks, user: User = Depends(_cand_user),
            db: Session = Depends(get_db)) -> dict:
    t, side = _resolve(db, user, tid)
    if t.status == "pending":
        t.status = "active"
        t.activated_at = utcnow()
        _system(db, t, "Кандидат согласился: представитель ФСП подключён к каналу.")
        db.commit()
        _notify(bg, db, t, "candidate", "Кандидат согласился подключить представителя ФСП к каналу")
    return _thread_out(db, t, side, full=True)


@router.post("/threads/{tid}/close", summary="Закрыть канал (дальше только чтение)", responses=AUTH)
def close(resolved: tuple[TrioThread, str, User] = Depends(_resolve_dep),
          db: Session = Depends(get_db)) -> dict:
    t, side, _ = resolved
    if t.status != "closed":
        t.status = "closed"
        t.closed_at = utcnow()
        _system(db, t, f"{SIDE_TITLE[side]} закрыл(а) канал. Переписка доступна только для чтения.")
        db.commit()
    return _thread_out(db, t, side, full=True)
