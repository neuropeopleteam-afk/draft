"""Переписка внутри платформы, встречное предложение и отзыв доступа к контактам: API.

Уведомления о сообщениях и решениях — push (Web Push, если пользователь подписан) и письмо. Письмо о сообщениях —
только на первое непрочитанное в треде, чтобы не засыпать почту. Демо-учёткам письма не отправляются (notify).
"""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.integrations.push.service import notify_user
from app.modules.auth.models import User
from app.modules.contact import service as svc
from app.modules.contact.salary import basis_title
from app.modules.invitations.models import Invitation
from app.modules.invitations.router import _inv_out
from app.modules.matching.router import my_company
from app.modules.notifications.mailer import notify
from app.modules.profiles.models import CandidateProfile

TAGS = [{"name": "contact", "description": "Переписка по приглашению и отклику, встречное предложение кандидата, "
                                           "отзыв доступа к контактам"}]
router = APIRouter(prefix="/api/messages", tags=["contact"])
candidate_router = APIRouter(prefix="/api/candidate", tags=["contact"])
employer_router = APIRouter(prefix="/api/employer", tags=["contact"])
candidate = require_role(UserRole.candidate)
employer = require_role(UserRole.employer)
AUTH = {401: err("Не выполнен вход"), 404: err("Переписка не найдена или недоступна")}
Kind = Literal["invitation", "application"]


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=svc.CHAT_MAX_LEN,
                      description="До принятия приглашения — до 1000 символов, контакты в тексте маскируются")


class CounterIn(BaseModel):
    salary_from: int = Field(gt=0, le=10_000_000, description="Встречная вилка «от», ₽ в месяц")
    salary_to: int = Field(gt=0, le=10_000_000, description="Встречная вилка «до», ₽ в месяц")
    salary_basis: Literal["gross", "net"] | None = Field(
        None, description="gross — до вычета НДФЛ, net — на руки; по умолчанию — как в приглашении")
    comment: str | None = Field(None, max_length=1000, description="Почему такая вилка (необязательно)")

    @model_validator(mode="after")
    def _range(self):
        if self.salary_from > self.salary_to:
            raise ValueError("Нижняя граница вилки больше верхней")
        return self


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=1000, description="Комментарий кандидату (необязательно)")


def _tell(bg: BackgroundTasks, u: User | None, subject: str, lines: list[str], path: str, push_body: str,
          tag: str, email: bool = True) -> None:
    if u is None:
        return
    bg.add_task(notify_user, u.id, subject, push_body[:160], path, tag)
    if email:
        bg.add_task(notify, u.email, subject, lines, is_demo=u.is_demo, link_path=path)


def _link(side_of_recipient: str, kind: str, tid) -> str:
    return f"/{side_of_recipient}/messages?t={kind}:{tid}"


# ------------------------------------------------------------------ переписка

@router.get("/threads", summary="Мои переписки: по приглашениям и откликам, с непрочитанными", responses=AUTH)
def my_threads(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return svc.threads(db, user)


@router.get("/unread", summary="Число непрочитанных сообщений (для значка в меню)", responses=AUTH)
def unread(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return svc.unread_counts(db, user)


@router.get("/{kind}/{tid}", summary="Переписка (сообщения другой стороны отмечаются прочитанными)", responses=AUTH)
def get_thread(kind: Kind, tid: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    t = svc.resolve(db, user, kind, tid)
    svc.mark_read(db, t)
    return svc.thread_out(db, t)


@router.post("/{kind}/{tid}", status_code=201, summary="Написать сообщение",
             description="До принятия приглашения — «вопрос — ответ»: контакты в тексте маскируются, не больше "
                         f"{svc.QA_MAX_IN_ROW} сообщений подряд без ответа и {svc.QA_MAX_PER_SIDE} с каждой стороны. "
                         "После принятия и по отклику — обычный чат. Лимит от спама — "
                         f"{svc.RATE_10MIN} сообщений за 10 минут.",
             responses={**AUTH, 409: err("Переписка закрыта, лимит «вопрос — ответ» или повтор"),
                        422: err("Пустое или слишком длинное сообщение"), 429: err("Слишком много сообщений")})
def post_message(kind: Kind, tid: uuid.UUID, data: MessageIn, bg: BackgroundTasks,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    t = svc.resolve(db, user, kind, tid)
    m = svc.send(db, user, t, data.body)
    first = svc.unread_before(db, t, m) == 0
    to_side = t.counterpart_side
    who = svc.counterpart_title(db, t, to_side)  # как отправителя видит получатель
    where = f"«{t.title}»"
    for u in svc.recipients(db, t):
        _tell(bg, u, f"Новое сообщение: {who}", [f"{who} написал(а) вам по {'приглашению' if kind == 'invitation' else 'отклику'} {where}:",
                                                f"«{m.body[:500]}»", "Ответить можно в кабинете, в разделе «Сообщения»."],
              _link(to_side, kind, t.id), f"{who}: {m.body}", f"msg-{t.id}", email=first)
    out = svc.thread_out(db, t)
    out["sent"] = svc.message_out(m, t.side)
    return out


# ------------------------------------------------------------------ встречное предложение

def _cand_inv(db: Session, user: User, inv_id: uuid.UUID) -> Invitation:
    i = db.get(Invitation, inv_id)
    if i is None or i.candidate_user_id != user.id:
        raise api_error(404, "invitation_not_found", "Приглашение не найдено")
    return i


def _emp_inv(db: Session, user: User, inv_id: uuid.UUID) -> Invitation:
    c = my_company(db, user)
    i = db.get(Invitation, inv_id)
    if i is None or i.company_id != c.id:
        raise api_error(404, "invitation_not_found", "Приглашение не найдено")
    return i


def _employer_of(db: Session, i: Invitation) -> User | None:
    return db.get(User, i.employer_user_id) if i.employer_user_id else None


@candidate_router.post(
    "/invitations/{inv_id}/counter", status_code=201, summary="Встречное предложение: своя вилка в ответ на приглашение",
    description="Ширина вилки — не больше 1,5 (как у всех вилок); выше предложенной хотя бы одной границей; «от» — "
                f"не выше {svc.COUNTER_MAX_UP} × «до» приглашения. Не больше {svc.COUNTER_MAX} встречных на приглашение. "
                "Если работодатель примет встречное, приглашение будет принято и работодатель увидит ваши контакты.",
    responses={401: err("Не выполнен вход"), 403: err("Только для кандидата"), 404: err("Приглашение не найдено"),
               409: err("Приглашение закрыто, встречное уже ждёт ответа или лимит"),
               422: err("Вилка не по правилам")})
def counter(inv_id: uuid.UUID, data: CounterIn, bg: BackgroundTasks, user: User = Depends(candidate),
            db: Session = Depends(get_db)) -> dict:
    i = _cand_inv(db, user, inv_id)
    basis = data.salary_basis or i.salary_basis or "gross"
    svc.create_counter(db, i, user.id, data.salary_from, data.salary_to, basis, data.comment)
    ref = db.get(CandidateProfile, user.id).public_ref
    r = svc.rng(data.salary_from, data.salary_to, basis)
    _tell(bg, _employer_of(db, i), f"Встречное предложение кандидата {ref}",
          [f"Кандидат {ref} ответил на приглашение «{i.position_title}» встречной вилкой: {r}.",
           f"Ваша вилка: {svc.rng(i.salary_from, i.salary_to, i.salary_basis)}.",
           "Примите — приглашение будет принято и откроются контакты; отклоните — останется ваша вилка."],
          "/employer/invitations", f"«{i.position_title}»: {r}", f"inv-{i.id}")
    return _inv_out(db, i, "candidate")


@employer_router.post("/invitations/{inv_id}/counter/accept",
                      summary="Принять встречное предложение: вилка заменяется, приглашение принято, контакты открыты",
                      responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
                                 404: err("Приглашение не найдено"), 409: err("Нет ожидающего встречного")})
def counter_accept(inv_id: uuid.UUID, data: NoteIn, bg: BackgroundTasks, user: User = Depends(employer),
                   db: Session = Depends(get_db)) -> dict:
    i = _emp_inv(db, user, inv_id)
    c = svc.accept_counter(db, i, user.id, data.note)
    cu = db.get(User, i.candidate_user_id)
    comp = my_company(db, user)
    r = svc.rng(c.salary_from, c.salary_to, c.salary_basis)
    _tell(bg, cu, f"{comp.name} принимает ваше встречное предложение",
          [f"Компания {comp.name} согласилась на вашу вилку {r} по приглашению «{i.position_title}».",
           "Приглашение принято, работодатель видит ваши контакты и свяжется с вами."]
          + ([f"Комментарий: {c.employer_note}"] if c.employer_note else []),
          "/candidate/invitations", f"«{i.position_title}»: {r} — приглашение принято", f"inv-{i.id}")
    bg.add_task(_ats_after_accept, i.id)
    return _inv_out(db, i, "employer")


def _ats_after_accept(inv_id: uuid.UUID) -> None:
    """Как при обычном принятии (integrations.events.invitation_answered): авто-передача в ATS, если включена."""
    import logging

    from app.core.db import SessionLocal
    from app.integrations.ats.models import AtsSettings
    from app.integrations.ats.providers import enabled_targets
    from app.integrations.ats.service import deliver

    db = SessionLocal()
    try:
        i = db.get(Invitation, inv_id)
        st = db.get(AtsSettings, i.company_id) if i else None
        if st is not None and st.auto_push and enabled_targets(db, i.company_id, st):
            deliver(db, i.company_id, invitation_id=i.id, trigger="invitation_accepted")
    except Exception:  # noqa: BLE001 — сбой ATS не влияет на принятие
        logging.getLogger(__name__).exception("ATS after counter accept failed")
    finally:
        db.close()


@employer_router.post("/invitations/{inv_id}/counter/decline",
                      summary="Отклонить встречное предложение: приглашение остаётся открытым с вашей вилкой",
                      responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
                                 404: err("Приглашение не найдено"), 409: err("Нет ожидающего встречного")})
def counter_decline(inv_id: uuid.UUID, data: NoteIn, bg: BackgroundTasks, user: User = Depends(employer),
                    db: Session = Depends(get_db)) -> dict:
    i = _emp_inv(db, user, inv_id)
    c = svc.decline_counter(db, i, user.id, data.note)
    comp = my_company(db, user)
    _tell(bg, db.get(User, i.candidate_user_id), f"{comp.name}: ответ на встречное предложение",
          [f"Компания {comp.name} не готова к вилке {svc.rng(c.salary_from, c.salary_to, c.salary_basis)} "
           f"по приглашению «{i.position_title}».",
           f"В силе исходное предложение: {svc.rng(i.salary_from, i.salary_to, i.salary_basis)}. Его можно принять или отклонить."]
          + ([f"Комментарий: {c.employer_note}"] if c.employer_note else []),
          "/candidate/invitations", f"«{i.position_title}»: встречное отклонено, в силе исходная вилка", f"inv-{i.id}")
    return _inv_out(db, i, "employer")


# ------------------------------------------------------------------ доступ к контактам

@candidate_router.post("/invitations/{inv_id}/contacts/revoke",
                       summary="Отозвать доступ работодателя к моим контактам (после принятия)",
                       description="Работодатель снова видит обезличенную карточку: контакты, PDF с контактами и "
                                   "передача в ATS закрываются; переписка возвращается в режим «вопрос — ответ».",
                       responses={401: err("Не выполнен вход"), 403: err("Только для кандидата"),
                                  404: err("Приглашение не найдено"), 409: err("Приглашение не принято или доступ уже отозван")})
def revoke(inv_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    i = _cand_inv(db, user, inv_id)
    svc.revoke_contacts(db, i, user.id)
    ref = db.get(CandidateProfile, user.id).public_ref
    _tell(bg, _employer_of(db, i), f"Кандидат {ref} отозвал доступ к контактам",
          [f"Кандидат {ref} отозвал доступ к своим контактам по приглашению «{i.position_title}».",
           "Карточка снова обезличена. Переписка доступна в формате «вопрос — ответ»."],
          "/employer/invitations", f"«{i.position_title}»: доступ к контактам отозван", f"inv-{i.id}")
    return _inv_out(db, i, "candidate")


@candidate_router.post("/invitations/{inv_id}/contacts/restore", summary="Вернуть работодателю доступ к контактам",
                       responses={401: err("Не выполнен вход"), 403: err("Только для кандидата"),
                                  404: err("Приглашение не найдено"), 409: err("Доступ не отзывался")})
def restore(inv_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    i = _cand_inv(db, user, inv_id)
    svc.restore_contacts(db, i, user.id)
    ref = db.get(CandidateProfile, user.id).public_ref
    _tell(bg, _employer_of(db, i), f"Кандидат {ref} снова открыл контакты",
          [f"Кандидат {ref} вернул доступ к своим контактам по приглашению «{i.position_title}»."],
          "/employer/invitations", f"«{i.position_title}»: контакты снова открыты", f"inv-{i.id}")
    return _inv_out(db, i, "candidate")


__all__ = ["router", "candidate_router", "employer_router", "TAGS"]
