"""Найм после принятия приглашения: собеседование, оффер, исход найма — API обеих сторон.

Кандидат видит и меняет только свои приглашения, работодатель — только приглашения своей компании; чужое — 404.
Каждый шаг уведомляет другую сторону (push, если подписан, и письмо; демо-учёткам письма не уходят) и, если этап
сменился, переводит кандидата на этап в ATS работодателя в фоне (app.modules.hiring.ats).
"""
from __future__ import annotations

from datetime import date
from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import err
from app.integrations.push.service import notify_user
from app.modules.auth.models import User
from app.modules.contact.router import _cand_inv, _emp_inv, _employer_of
from app.modules.contact.salary import basis_title
from app.modules.hiring import ats as hats
from app.modules.hiring import service as svc
from app.modules.matching.router import my_company
from app.modules.notifications.mailer import notify
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile

TAGS = [{"name": "hiring", "description": "Найм после принятия приглашения: слоты собеседования, оффер со встречным, "
                                          "исход найма; этапы уходят в ATS работодателя и возвращаются обратно"}]
candidate_router = APIRouter(prefix="/api/candidate/invitations", tags=["hiring"])
employer_router = APIRouter(prefix="/api/employer/invitations", tags=["hiring"])
router = APIRouter(prefix="/api/hiring", tags=["hiring"])
candidate = require_role(UserRole.candidate)
employer = require_role(UserRole.employer)
C_AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата"), 404: err("Приглашение не найдено")}
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 404: err("Приглашение не найдено")}
CLOSED = {409: err("Приглашение не принято, контакты закрыты, найм завершён или шаг не по порядку")}
Basis = Literal["gross", "net"]


class SlotIn(BaseModel):
    starts_at: str = Field(description="Начало, ISO 8601; без часового пояса — московское время")
    duration_min: int = Field(60, ge=15, le=240)
    format: Literal["video", "phone", "office"] = "video"
    place: str | None = Field(None, max_length=500, description="Ссылка на видеозвонок (https) или адрес офиса")


class ProposeIn(BaseModel):
    slots: list[SlotIn] = Field(min_length=1, max_length=svc.SLOTS_MAX)
    title: str | None = Field(None, max_length=120, description="Например, «Техническое собеседование»")
    note: str | None = Field(None, max_length=1000, description="Комментарий кандидату")


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=1000)


class ChooseIn(BaseModel):
    slot_id: str = Field(min_length=1, max_length=8)


class OtherIn(BaseModel):
    note: str = Field(min_length=1, max_length=500, description="Когда удобно: дни, время")


class OfferIn(BaseModel):
    salary: int = Field(gt=0, le=10_000_000, description="₽ в месяц")
    salary_basis: Basis | None = Field(None, description="По умолчанию — как в приглашении")
    start_date: date
    respond_until: date | None = Field(None, description="Срок ответа (до конца дня по Москве); по умолчанию +3 дня")
    comment: str | None = Field(None, max_length=1000)


class CounterIn(BaseModel):
    salary: int = Field(gt=0, le=10_000_000)
    salary_basis: Basis | None = None
    comment: str | None = Field(None, max_length=1000)


class DeclineIn(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class OutcomeIn(BaseModel):
    outcome: Literal["hired", "declined", "rejected"]
    start_date: date | None = None
    note: str | None = Field(None, max_length=1000)


def _tell(bg: BackgroundTasks, u: User | None, subject: str, lines: list[str], path: str, push: str, tag: str) -> None:
    if u is None:
        return
    bg.add_task(notify_user, u.id, subject, push[:160], path, tag)
    bg.add_task(notify, u.email, subject, lines, is_demo=u.is_demo, link_path=path)


def _ref(db: Session, inv) -> str:
    cp = db.get(CandidateProfile, inv.candidate_user_id)
    return cp.public_ref if cp else "кандидат"


def _company(db: Session, inv) -> str:
    c = db.get(Company, inv.company_id)
    return c.name if c else "Работодатель"


def _emp_out(db: Session, inv) -> dict:
    out = svc.state_out(db, inv, "employer")
    out["ats"] = hats.ats_out(db, inv)
    return out


def _to_candidate(bg, db, inv, subject: str, lines: list[str], push: str) -> None:
    _tell(bg, db.get(User, inv.candidate_user_id), subject, lines, "/candidate/invitations",
          f"«{inv.position_title}»: {push}", f"hire-{inv.id}")


def _to_employer(bg, db, inv, subject: str, lines: list[str], push: str) -> None:
    _tell(bg, _employer_of(db, inv), subject, lines, "/employer/invitations", f"«{inv.position_title}»: {push}",
          f"hire-{inv.id}")


# ------------------------------------------------------------------ чтение

@employer_router.get("/{inv_id}/hiring", summary="Найм по приглашению: собеседование, оффер, исход, передача в ATS",
                     responses=E_AUTH)
def employer_state(inv_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return _emp_out(db, _emp_inv(db, user, inv_id))


@candidate_router.get("/{inv_id}/hiring", summary="Найм по приглашению: слоты собеседования, оффер, исход",
                      responses=C_AUTH)
def candidate_state(inv_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return svc.state_out(db, _cand_inv(db, user, inv_id), "candidate")


@router.get("/todo", summary="Что ждёт моего ответа по найму (счётчик в меню и напоминания в кабинете)",
            responses={401: err("Не выполнен вход")})
def todo(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if user.role == UserRole.candidate:
        return svc.todo(db, svc.accepted_invitations(db, candidate_id=user.id), "candidate")
    if user.role == UserRole.employer:
        ep = db.get(EmployerProfile, user.id)
        if ep is None or ep.company_id is None:
            return {"total": 0, "items": []}
        return svc.todo(db, svc.accepted_invitations(db, company_id=ep.company_id), "employer")
    return {"total": 0, "items": []}


# ------------------------------------------------------------------ собеседование

@employer_router.post("/{inv_id}/interviews", status_code=201, summary="Предложить 1–3 слота собеседования",
                      description="Дата и время — не раньше чем через 10 минут и не дальше 60 дней; видеозвонок — "
                                  "ссылка https, офис — адрес. Повторный вызов по активному собеседованию заменяет "
                                  "слоты (перенос).",
                      responses={**E_AUTH, **CLOSED, 422: err("Слоты не по правилам")})
def propose(inv_id: uuid.UUID, data: ProposeIn, bg: BackgroundTasks, user: User = Depends(employer),
            db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    iv = svc.propose(db, inv, user.id, [s.model_dump() for s in data.slots], data.title, data.note)
    n = len(iv.slots)
    _to_candidate(bg, db, inv, f"{_company(db, inv)}: время собеседования",
                  [f"Компания {_company(db, inv)} предлагает время собеседования по приглашению «{inv.position_title}»:",
                   *[f"— {svc.slot_text(s)}" for s in iv.slots],
                   "Выберите удобный слот или попросите другое время в кабинете, в разделе «Приглашения»."],
                  f"выберите время собеседования ({n} {'слот' if n == 1 else 'слота'})")
    return _emp_out(db, inv)


@candidate_router.post("/{inv_id}/interviews/{iid}/choose", summary="Выбрать слот собеседования",
                       responses={**C_AUTH, **CLOSED, 422: err("Нет такого слота")})
def choose(inv_id: uuid.UUID, iid: uuid.UUID, data: ChooseIn, bg: BackgroundTasks, user: User = Depends(candidate),
           db: Session = Depends(get_db)) -> dict:
    inv = _cand_inv(db, user, inv_id)
    iv = svc.choose(db, inv, user.id, iid, data.slot_id)
    when = f"{iv.starts_at and svc.msk(iv.starts_at)} · {svc.FORMATS[iv.format].lower()}"
    _to_employer(bg, db, inv, f"Кандидат {_ref(db, inv)} выбрал время собеседования",
                 [f"Кандидат {_ref(db, inv)} выбрал время собеседования по приглашению «{inv.position_title}»: {when}."],
                 f"собеседование {when}")
    bg.add_task(hats.push_stage_bg, inv.id, "interview", f"собеседование назначено, {when}")
    return svc.state_out(db, inv, "candidate")


@candidate_router.post("/{inv_id}/interviews/{iid}/reschedule", summary="Попросить другое время собеседования",
                       responses={**C_AUTH, **CLOSED, 422: err("Не указано, когда удобно")})
def reschedule(inv_id: uuid.UUID, iid: uuid.UUID, data: OtherIn, bg: BackgroundTasks,
               user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    inv = _cand_inv(db, user, inv_id)
    iv = svc.request_other(db, inv, user.id, iid, data.note)
    _to_employer(bg, db, inv, f"Кандидат {_ref(db, inv)} просит другое время собеседования",
                 [f"Кандидат {_ref(db, inv)} просит другое время собеседования по приглашению «{inv.position_title}»:",
                  f"«{iv.candidate_note}»", "Предложите новые слоты в кабинете, в разделе «Приглашения»."],
                 f"просит другое время: {iv.candidate_note}")
    return svc.state_out(db, inv, "candidate")


@employer_router.post("/{inv_id}/interviews/{iid}/done", summary="Отметить: собеседование прошло",
                      description="После начала собеседования; у демо-компаний песочницы жюри — в любой момент.",
                      responses={**E_AUTH, **CLOSED})
def done(inv_id: uuid.UUID, iid: uuid.UUID, data: NoteIn, user: User = Depends(employer),
         db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    svc.mark_done(db, inv, user.id, iid, data.note)
    return _emp_out(db, inv)


@employer_router.post("/{inv_id}/interviews/{iid}/cancel", summary="Отменить собеседование",
                      responses={**E_AUTH, **CLOSED})
def cancel(inv_id: uuid.UUID, iid: uuid.UUID, data: NoteIn, bg: BackgroundTasks, user: User = Depends(employer),
           db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    iv = svc.cancel(db, inv, user.id, iid, data.note)
    _to_candidate(bg, db, inv, f"{_company(db, inv)}: собеседование отменено",
                  [f"Компания {_company(db, inv)} отменила собеседование по приглашению «{inv.position_title}»."]
                  + ([f"Комментарий: {iv.result_note}"] if iv.result_note else []), "собеседование отменено")
    return _emp_out(db, inv)


# ------------------------------------------------------------------ оффер

@employer_router.post("/{inv_id}/offer", status_code=201, summary="Отправить оффер",
                      description="Сумма — не ниже «от» вилки приглашения (можно выше «до»); дата выхода — до 180 дней; "
                                  "срок ответа — до 30 дней. Один открытый оффер на приглашение.",
                      responses={**E_AUTH, **CLOSED, 422: err("Сумма или даты не по правилам")})
def offer(inv_id: uuid.UUID, data: OfferIn, bg: BackgroundTasks, user: User = Depends(employer),
          db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    basis = data.salary_basis or inv.salary_basis or "gross"
    ru = data.respond_until or svc.presets(db, inv)["offer"]["respond_until"]
    o = svc.send_offer(db, inv, user.id, salary=data.salary, basis=basis, start_date=data.start_date,
                       respond_until=ru, comment=data.comment)
    _to_candidate(bg, db, inv, f"Оффер от компании {_company(db, inv)}",
                  [f"Компания {_company(db, inv)} отправила оффер по приглашению «{inv.position_title}»:",
                   svc.offer_text(o)] + ([f"Комментарий: {o.comment}"] if o.comment else [])
                  + ["Принять, отклонить или ответить встречным можно в кабинете, в разделе «Приглашения»."],
                  f"оффер {svc.rub(o.salary)} {basis_title(o.salary_basis)}")
    bg.add_task(hats.push_stage_bg, inv.id, "offer", f"оффер {svc.offer_text(o)}")
    return _emp_out(db, inv)


@employer_router.post("/{inv_id}/offer/withdraw", summary="Отозвать открытый оффер", responses={**E_AUTH, **CLOSED})
def offer_withdraw(inv_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(employer),
                   db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    svc.withdraw_offer(db, inv, user.id)
    _to_candidate(bg, db, inv, f"{_company(db, inv)}: оффер отозван",
                  [f"Компания {_company(db, inv)} отозвала оффер по приглашению «{inv.position_title}»."],
                  "оффер отозван")
    return _emp_out(db, inv)


@employer_router.post("/{inv_id}/offer/counter/accept", summary="Принять встречное на оффер: сумма заменяется, "
                                                                "оффер принят", responses={**E_AUTH, **CLOSED})
def offer_counter_accept(inv_id: uuid.UUID, data: NoteIn, bg: BackgroundTasks, user: User = Depends(employer),
                         db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    o = svc.decide_counter(db, inv, user.id, True, data.note)
    _to_candidate(bg, db, inv, f"{_company(db, inv)} принимает ваше встречное",
                  [f"Компания {_company(db, inv)} согласилась на {svc.rub(o.salary)} {basis_title(o.salary_basis)} "
                   f"по приглашению «{inv.position_title}». Оффер принят, дата выхода {svc.ddmm(o.start_date)}."],
                  f"встречное принято, оффер {svc.rub(o.salary)}")
    return _emp_out(db, inv)


@employer_router.post("/{inv_id}/offer/counter/decline", summary="Отклонить встречное: остаётся прежний оффер",
                      responses={**E_AUTH, **CLOSED})
def offer_counter_decline(inv_id: uuid.UUID, data: NoteIn, bg: BackgroundTasks, user: User = Depends(employer),
                          db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    o = svc.decide_counter(db, inv, user.id, False, data.note)
    _to_candidate(bg, db, inv, f"{_company(db, inv)}: встречное отклонено",
                  [f"Компания {_company(db, inv)} оставляет оффер {svc.rub(o.salary)} {basis_title(o.salary_basis)} "
                   f"по приглашению «{inv.position_title}». Ответить можно до {svc.msk(o.respond_until)}."]
                  + ([f"Комментарий: {data.note}"] if data.note else []), "встречное отклонено, оффер в силе")
    return _emp_out(db, inv)


@candidate_router.post("/{inv_id}/offer/accept", summary="Принять оффер", responses={**C_AUTH, **CLOSED})
def offer_accept(inv_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(candidate),
                 db: Session = Depends(get_db)) -> dict:
    inv = _cand_inv(db, user, inv_id)
    o = svc.accept_offer(db, inv, user.id)
    _to_employer(bg, db, inv, f"Кандидат {_ref(db, inv)} принял оффер",
                 [f"Кандидат {_ref(db, inv)} принял оффер по приглашению «{inv.position_title}»: {svc.offer_text(o)}.",
                  "Когда кандидат выйдет на работу, отметьте это в карточке приглашения — этап уйдёт в ATS."],
                 "оффер принят")
    return svc.state_out(db, inv, "candidate")


@candidate_router.post("/{inv_id}/offer/decline", summary="Отклонить оффер (исход «отказ кандидата»)",
                       responses={**C_AUTH, **CLOSED})
def offer_decline(inv_id: uuid.UUID, data: DeclineIn, bg: BackgroundTasks, user: User = Depends(candidate),
                  db: Session = Depends(get_db)) -> dict:
    inv = _cand_inv(db, user, inv_id)
    o = svc.decline_offer(db, inv, user.id, data.reason)
    _to_employer(bg, db, inv, f"Кандидат {_ref(db, inv)} отклонил оффер",
                 [f"Кандидат {_ref(db, inv)} отклонил оффер по приглашению «{inv.position_title}»."]
                 + ([f"Причина: {o.decline_reason}"] if o.decline_reason else []), "оффер отклонён")
    bg.add_task(hats.push_stage_bg, inv.id, "declined", "кандидат отклонил оффер")
    return svc.state_out(db, inv, "candidate")


@candidate_router.post("/{inv_id}/offer/counter", status_code=201, summary="Встречное на оффер: своя сумма",
                       description=f"Выше оффера и не выше {svc.COUNTER_MAX_UP} × оффера; одно ожидающее, "
                                   f"не больше {svc.COUNTER_MAX} на оффер.",
                       responses={**C_AUTH, **CLOSED, 422: err("Сумма не по правилам")})
def offer_counter(inv_id: uuid.UUID, data: CounterIn, bg: BackgroundTasks, user: User = Depends(candidate),
                  db: Session = Depends(get_db)) -> dict:
    inv = _cand_inv(db, user, inv_id)
    o = svc.counter_offer(db, inv, user.id, data.salary, data.salary_basis, data.comment)
    c = svc.pending_counter(o)
    _to_employer(bg, db, inv, f"Встречное на оффер: кандидат {_ref(db, inv)}",
                 [f"Кандидат {_ref(db, inv)} ответил на оффер «{inv.position_title}» встречным: "
                  f"{svc.rub(c['salary'])} {basis_title(c['salary_basis'])}.",
                  f"Ваш оффер: {svc.rub(o.salary)} {basis_title(o.salary_basis)}."]
                 + ([f"Комментарий: {c['comment']}"] if c.get("comment") else []),
                 f"встречное {svc.rub(c['salary'])}")
    return svc.state_out(db, inv, "candidate")


# ------------------------------------------------------------------ исход найма

@employer_router.post("/{inv_id}/outcome", summary="Исход найма: вышел на работу / отказ кандидата / не прошёл",
                      description="«Вышел на работу» — после принятого оффера. Исход окончательный, уходит в ATS этапом.",
                      responses={**E_AUTH, **CLOSED})
def outcome(inv_id: uuid.UUID, data: OutcomeIn, bg: BackgroundTasks, user: User = Depends(employer),
            db: Session = Depends(get_db)) -> dict:
    inv = _emp_inv(db, user, inv_id)
    oc = svc.set_outcome(db, inv, user.id, data.outcome, data.note, data.start_date)
    comp = my_company(db, user).name
    if oc.outcome == "hired":
        _to_candidate(bg, db, inv, f"{comp}: выход на работу",
                      [f"Компания {comp} отметила ваш выход на работу по приглашению «{inv.position_title}»"
                       + (f" с {svc.ddmm(oc.start_date)}." if oc.start_date else ".")], "выход на работу отмечен")
    elif oc.outcome == "rejected":
        _to_candidate(bg, db, inv, f"{comp}: решение по найму",
                      [f"Компания {comp} завершила рассмотрение по приглашению «{inv.position_title}»."]
                      + ([f"Комментарий: {oc.note}"] if oc.note else []), "работодатель завершил рассмотрение")
    detail = {"hired": "вышел на работу" + (f" {svc.ddmm(oc.start_date)}" if oc.start_date else ""),
              "rejected": "не прошёл", "declined": "отказ кандидата"}[oc.outcome]
    bg.add_task(hats.push_stage_bg, inv.id, oc.outcome, detail + (f": {oc.note}" if oc.note else ""))
    return _emp_out(db, inv)
