"""Зонды и приглашения: API работодателя и кандидата.

Разграничение прав: кандидат видит только свои зонды и приглашения; работодатель — только своей компании;
контакты кандидата работодатель получает только после принятия приглашения.
"""
from __future__ import annotations

import logging
from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import InvitationStatus, ProbeStatus, UserRole
from app.core.errors import api_error, err
from app.integrations import events as integration_events
from app.modules.auth.models import User
from app.modules.contact import service as contact_svc
from app.modules.contact.salary import basis_out, basis_title
from app.modules.invitations import service as svc
from app.modules.invitations.models import Invitation, Probe
from app.modules.matching.router import my_company
from app.modules.notifications.mailer import notify
from app.modules.profiles.models import CandidateProfile, Company

log = logging.getLogger(__name__)
employer_router = APIRouter(prefix="/api/employer", tags=["employer-contact"])
candidate_router = APIRouter(prefix="/api/candidate", tags=["candidate-contact"])
employer = require_role(UserRole.employer)
candidate = require_role(UserRole.candidate)
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 409: err("Нет профиля компании")}
C_AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}


class SalaryRange(BaseModel):
    salary_from: int = Field(gt=0, le=10_000_000, description="Вилка «от», ₽ в месяц — обязательно")
    salary_to: int = Field(gt=0, le=10_000_000, description="Вилка «до», ₽ — обязательно")
    salary_basis: Literal["gross", "net"] = Field("gross", description="gross — до вычета НДФЛ, net — на руки")

    @model_validator(mode="after")
    def _range(self):
        if self.salary_from > self.salary_to:
            raise ValueError("Нижняя граница вилки больше верхней")
        return self


class ProbeIn(SalaryRange):
    candidate_refs: list[str] = Field(min_length=1, max_length=20, description="Обезличенные идентификаторы кандидатов")
    need_id: uuid.UUID | None = None
    title: str = Field(min_length=3, max_length=200)
    task_text: str = Field(min_length=20, max_length=5000)
    answer_mode: Literal["solution", "approach", "any"] = "any"
    time_limit_min: int = Field(30, ge=5, le=240)


class EmploymentTerms(BaseModel):
    format: Literal["employment", "internship", "light_work"] = "employment"
    reduced_time: bool = False
    employer_acknowledged: bool = False


class InvitationIn(SalaryRange):
    candidate_ref: str
    need_id: uuid.UUID | None = None
    probe_id: uuid.UUID | None = None
    position_title: str = Field(min_length=3, max_length=200)
    offer_description: str = Field(min_length=20, max_length=5000)
    contact_method: str = Field(min_length=3, max_length=255, description="Как связаться с работодателем")
    employment_terms: EmploymentTerms = Field(default_factory=EmploymentTerms)


class ReviewIn(BaseModel):
    verdict: Literal["strong", "ok", "weak"]
    comment: str | None = Field(None, max_length=2000)


class ProbeAnswerIn(BaseModel):
    mode: Literal["solution", "approach"]
    text: str = Field(min_length=10, max_length=10000)
    link: str | None = Field(None, max_length=500)


class DeclineIn(BaseModel):
    reason: str | None = Field(None, max_length=1000, description="Необязательно")


class ComplaintIn(BaseModel):
    reason: Literal["salary", "role", "spam", "other"] = Field(
        description="salary — нереальная вилка, role — не та роль, spam — спам или массовая рассылка, other — другое")
    comment: str | None = Field(None, max_length=1000, description="Необязательно; работодатель комментарий не видит")


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def _probe_out(db: Session, p: Probe, side: str) -> dict:
    comp = db.get(Company, p.company_id)
    cand = db.get(CandidateProfile, p.candidate_user_id)
    out = {"id": str(p.id), "title": p.title, "task_text": p.task_text, "answer_mode": p.answer_mode,
           "salary_from": p.salary_from, "salary_to": p.salary_to, "time_limit_min": p.time_limit_s // 60,
           "status": p.status.value, "events": p.events, "answer": p.answer, "review": p.review,
           "created_at": p.created_at.isoformat(), "deadline_at": p.deadline_at.isoformat() if p.deadline_at else None,
           "company": {"name": comp.name, "industry": comp.industry} if comp else None, **basis_out(p.salary_basis)}
    if side == "employer":
        out["candidate_ref"] = cand.public_ref
        out["candidate_category"] = cand.current_category_id
    else:
        out["below_my_minimum"] = svc.below_minimum(cand, p.salary_to, p.salary_basis)
    return out


def _ats_transfers(db: Session, i: Invitation) -> list[dict]:
    from app.integrations.ats.service import invitation_transfers

    try:
        return invitation_transfers(db, i.company_id, i)
    except Exception:  # noqa: BLE001 — состояние ATS не должно ломать список приглашений
        db.rollback()
        log.exception("ats transfers failed")
        return []


def _inv_out(db: Session, i: Invitation, side: str) -> dict:
    from app.integrations.ats.stages import stage_out

    comp = db.get(Company, i.company_id)
    cand = db.get(CandidateProfile, i.candidate_user_id)
    out = {"id": str(i.id), "position_title": i.position_title, "offer_description": i.offer_description,
           "employment_terms": i.employment_terms,
           "salary_from": i.salary_from, "salary_to": i.salary_to, "contact_method": i.contact_method,
           "evidence": i.evidence, "status": i.status.value, "decline_reason": i.decline_reason,
           "created_at": i.created_at.isoformat(), "viewed_at": i.viewed_at.isoformat() if i.viewed_at else None,
           "responded_at": i.responded_at.isoformat() if i.responded_at else None,
           "history": svc.events_of(db, i),
           "company": {"name": comp.name, "industry": comp.industry, "website": comp.website, "city": comp.city}
           if comp else None}
    out["complaint"] = svc.complaint_out(svc.complaint_of(db, i), with_comment=side == "candidate")
    out["ats_stage"] = stage_out(i.ats_stage, side)  # обратный канал: этап у работодателя по данным его ATS
    if side == "employer":
        out["candidate_ref"] = cand.public_ref
        out["candidate_category"] = cand.current_category_id
        out["contacts"] = svc.candidate_contacts(db, i.candidate_user_id) if i.contacts_revealed_at else None
        out["ats_transfers"] = _ats_transfers(db, i)  # состояние по каждой ATS: передано / ошибка / не передавалось
    else:
        out["below_my_minimum"] = svc.below_minimum(cand, i.salary_to, i.salary_basis)
    out.update(contact_svc.invitation_extras(db, i, side))  # НДФЛ, встречное, доступ к контактам, переписка
    return out


def _candidate_user(db: Session, uid: uuid.UUID) -> User:
    return db.get(User, uid)


# ------------------------------------------------------------------ работодатель: зонды

@employer_router.post("/probes", status_code=201, summary="Отправить зонд выбранным кандидатам (вилка обязательна)",
                      responses={**E_AUTH, 404: err("Кандидат не найден"),
                                 422: err("Нет вилки «от–до» или она некорректна")})
def send_probes(data: ProbeIn, bg: BackgroundTasks, user: User = Depends(employer),
                db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    svc.check_salary(data.salary_from, data.salary_to)  # ширина вилки — одной ошибкой, а не пропуском каждого
    created, skipped = [], []
    for ref in dict.fromkeys(data.candidate_refs):
        p = svc.profile_by_ref(db, ref)
        try:
            pr = svc.create_probe(db, user, c, p, title=data.title, task_text=data.task_text,
                                  answer_mode=data.answer_mode, salary_from=data.salary_from, salary_to=data.salary_to,
                                  time_limit_min=data.time_limit_min, need_id=data.need_id,
                                  salary_basis=data.salary_basis)
        except Exception as e:  # noqa: BLE001 — например, уже есть активный зонд
            db.rollback()
            skipped.append({"ref": ref, "reason": getattr(e, "detail", {}).get("message", "ошибка")})
            continue
        created.append(_probe_out(db, pr, "employer"))
        cu = _candidate_user(db, p.user_id)
        bg.add_task(notify, cu.email, f"Короткая задача от компании {c.name}",
                    [f"Компания {c.name} предлагает короткую задачу «{data.title}».",
                     f"Вилка зарплаты: {_rub(data.salary_from)} – {_rub(data.salary_to)} {basis_title(data.salary_basis)}.",
                     "Контакты не раскрываются, пока вы сами не примете приглашение."],
                    is_demo=cu.is_demo, link_path="/candidate/probes")
    return {"created": created, "skipped": skipped}


@employer_router.get("/probes", summary="Зонды моей компании", responses=E_AUTH)
def my_probes(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    rows = db.scalars(select(Probe).where(Probe.company_id == c.id).order_by(Probe.created_at.desc())).all()
    return [_probe_out(db, p, "employer") for p in rows]


@employer_router.post("/probes/{probe_id}/review", summary="Оценить ответ на зонд (становится фактом T1)",
                      responses={**E_AUTH, 404: err("Зонд не найден"), 409: err("Ответа ещё нет")})
def review(probe_id: uuid.UUID, data: ReviewIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    p = db.get(Probe, probe_id)
    if p is None or p.company_id != c.id:
        raise api_error(404, "probe_not_found", "Зонд не найден")
    return _probe_out(db, svc.review_probe(db, p, data.verdict, data.comment), "employer")


# ------------------------------------------------------------------ работодатель: приглашения

@employer_router.post(
    "/invitations", status_code=201, summary="Отправить приглашение-оффер",
    description="Вилка «от–до» в рублях обязательна. Не чаще одного приглашения кандидату от компании за 30 дней. "
                "Подтверждённые факты (T1/T2) прикладываются автоматически как доказательства соответствия.",
    responses={**E_AUTH, 404: err("Кандидат не найден"),
               409: err("invitation_cooldown — приглашение этому кандидату уже было в последние 30 дней"),
               422: err("Нет вилки «от–до» или она некорректна")},
)
def send_invitation(data: InvitationIn, bg: BackgroundTasks, user: User = Depends(employer),
                    db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    p = svc.profile_by_ref(db, data.candidate_ref)
    inv = svc.create_invitation(db, user, c, p, position_title=data.position_title,
                                offer_description=data.offer_description, salary_from=data.salary_from,
                                salary_to=data.salary_to, contact_method=data.contact_method, need_id=data.need_id,
                                probe_id=data.probe_id, employment_terms=data.employment_terms.model_dump(),
                                salary_basis=data.salary_basis)
    cu = _candidate_user(db, p.user_id)
    bg.add_task(notify, cu.email, f"Приглашение от компании {c.name}",
                [f"Компания {c.name} приглашает вас на позицию «{data.position_title}».",
                 f"Вилка зарплаты: {_rub(data.salary_from)} – {_rub(data.salary_to)} {basis_title(data.salary_basis)}.",
                 "Ваши контакты работодатель увидит, только если вы примете приглашение.",
                 "До принятия можно задать вопрос внутри платформы или предложить свою вилку."],
                is_demo=cu.is_demo, link_path="/candidate/invitations")
    bg.add_task(integration_events.invitation_sent, inv.id)
    return _inv_out(db, inv, "employer")


@employer_router.get("/invitations", summary="Приглашения моей компании со статусами и историей", responses=E_AUTH)
def my_invitations(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    rows = db.scalars(select(Invitation).where(Invitation.company_id == c.id)
                      .order_by(Invitation.created_at.desc())).all()
    return [_inv_out(db, i, "employer") for i in rows]


@employer_router.post("/invitations/{inv_id}/withdraw", summary="Отозвать неотвеченное приглашение",
                      responses={**E_AUTH, 404: err("Приглашение не найдено")})
def withdraw(inv_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    i = db.get(Invitation, inv_id)
    if i is None or i.company_id != c.id:
        raise api_error(404, "invitation_not_found", "Приглашение не найдено")
    return _inv_out(db, svc.withdraw(db, i, user.id), "employer")


# ------------------------------------------------------------------ кандидат

def _own(db: Session, model, obj_id: uuid.UUID, user: User, code: str, msg: str):
    o = db.get(model, obj_id)
    if o is None or o.candidate_user_id != user.id:
        raise api_error(404, code, msg)
    return o


@candidate_router.get("/invitations", summary="Мои приглашения", responses=C_AUTH)
def cand_invitations(user: User = Depends(candidate), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Invitation).where(Invitation.candidate_user_id == user.id,
                                               Invitation.status != InvitationStatus.withdrawn)
                      .order_by(Invitation.created_at.desc())).all()
    return [_inv_out(db, i, "candidate") for i in rows]


@candidate_router.get("/invitations/{inv_id}", summary="Приглашение (отмечается как просмотренное)",
                      responses={**C_AUTH, 404: err("Приглашение не найдено")})
def cand_invitation(inv_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    i = _own(db, Invitation, inv_id, user, "invitation_not_found", "Приглашение не найдено")
    svc.mark_viewed(db, i, user.id)
    return _inv_out(db, i, "candidate")


def _notify_employer(bg: BackgroundTasks, db: Session, employer_id, subject: str, lines: list[str], path: str):
    eu = db.get(User, employer_id) if employer_id else None
    if eu:
        bg.add_task(notify, eu.email, subject, lines, is_demo=eu.is_demo, link_path=path)


@candidate_router.post("/invitations/{inv_id}/accept", summary="Принять приглашение — работодатель увидит контакты",
                       responses={**C_AUTH, 404: err("Приглашение не найдено"), 409: err("Приглашение уже закрыто")})
def accept(inv_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    i = _own(db, Invitation, inv_id, user, "invitation_not_found", "Приглашение не найдено")
    svc.respond(db, i, user.id, True, None)
    ref = db.get(CandidateProfile, user.id).public_ref
    _notify_employer(bg, db, i.employer_user_id, f"Кандидат {ref} принял приглашение",
                     [f"Кандидат {ref} принял приглашение на позицию «{i.position_title}».",
                      "Контакты кандидата доступны в карточке приглашения."], "/employer/invitations")
    bg.add_task(integration_events.invitation_answered, i.id, True)
    return _inv_out(db, i, "candidate")


@candidate_router.post("/invitations/{inv_id}/decline", summary="Отклонить приглашение (причина — по желанию)",
                       responses={**C_AUTH, 404: err("Приглашение не найдено"), 409: err("Приглашение уже закрыто")})
def decline(inv_id: uuid.UUID, data: DeclineIn, bg: BackgroundTasks, user: User = Depends(candidate),
            db: Session = Depends(get_db)) -> dict:
    i = _own(db, Invitation, inv_id, user, "invitation_not_found", "Приглашение не найдено")
    svc.respond(db, i, user.id, False, data.reason)
    ref = db.get(CandidateProfile, user.id).public_ref
    _notify_employer(bg, db, i.employer_user_id, f"Кандидат {ref} отклонил приглашение",
                     [f"Кандидат {ref} отклонил приглашение на позицию «{i.position_title}»."]
                     + ([f"Причина: {i.decline_reason}"] if i.decline_reason else []), "/employer/invitations")
    bg.add_task(integration_events.invitation_answered, i.id, False)
    return _inv_out(db, i, "candidate")


@candidate_router.post("/invitations/{inv_id}/complaint", status_code=201,
                       summary="Пожаловаться на приглашение: нереальная вилка, не та роль, спам",
                       description="Неотвеченное приглашение заодно отклоняется. Жалобы снижают индекс доверия "
                                   "работодателя, который видят все кандидаты. Одна жалоба на приглашение.",
                       responses={**C_AUTH, 404: err("Приглашение не найдено"), 409: err("Жалоба уже отправлена")})
def complain(inv_id: uuid.UUID, data: ComplaintIn, bg: BackgroundTasks, user: User = Depends(candidate),
             db: Session = Depends(get_db)) -> dict:
    i = _own(db, Invitation, inv_id, user, "invitation_not_found", "Приглашение не найдено")
    was_open = i.status in (InvitationStatus.sent, InvitationStatus.viewed)
    svc.complain(db, i, user.id, data.reason, data.comment)
    ref = db.get(CandidateProfile, user.id).public_ref
    _notify_employer(bg, db, i.employer_user_id, f"Жалоба кандидата {ref} на приглашение",
                     [f"Кандидат {ref} пожаловался на приглашение «{i.position_title}»: "
                      f"{svc.COMPLAINT_REASONS[data.reason].lower()}.",
                      "Жалобы учитываются в индексе доверия компании, который видят кандидаты."], "/employer/invitations")
    if was_open:
        bg.add_task(integration_events.invitation_answered, i.id, False)
    return _inv_out(db, i, "candidate")


@candidate_router.get("/probes", summary="Мои зонды", responses=C_AUTH)
def cand_probes(user: User = Depends(candidate), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Probe).where(Probe.candidate_user_id == user.id).order_by(Probe.created_at.desc())).all()
    return [_probe_out(db, p, "candidate") for p in rows]


@candidate_router.get("/probes/{probe_id}", summary="Зонд (отмечается как просмотренный)",
                      responses={**C_AUTH, 404: err("Зонд не найден")})
def cand_probe(probe_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = _own(db, Probe, probe_id, user, "probe_not_found", "Зонд не найден")
    if p.status == ProbeStatus.sent:
        from app.core.db import utcnow

        p.viewed_at = utcnow()
        svc.probe_event(p, ProbeStatus.viewed, "candidate")
        db.commit()
    return _probe_out(db, p, "candidate")


@candidate_router.post("/probes/{probe_id}/answer", summary="Ответить на зонд: решение или подход",
                       responses={**C_AUTH, 404: err("Зонд не найден"), 409: err("Зонд закрыт"),
                                  422: err("Формат ответа не совпадает с запрошенным")})
def answer_probe(probe_id: uuid.UUID, data: ProbeAnswerIn, bg: BackgroundTasks, user: User = Depends(candidate),
                 db: Session = Depends(get_db)) -> dict:
    p = _own(db, Probe, probe_id, user, "probe_not_found", "Зонд не найден")
    svc.submit_probe(db, p, data.mode, data.text, data.link)
    ref = db.get(CandidateProfile, user.id).public_ref
    _notify_employer(bg, db, p.employer_user_id, f"Ответ на зонд «{p.title}»",
                     [f"Кандидат {ref} прислал {'решение' if data.mode == 'solution' else 'подход'} к задаче «{p.title}»."],
                     "/employer/probes")
    return _probe_out(db, p, "candidate")


@candidate_router.post("/probes/{probe_id}/decline", summary="Отказаться от зонда",
                       responses={**C_AUTH, 404: err("Зонд не найден"), 409: err("Зонд закрыт")})
def decline_probe(probe_id: uuid.UUID, data: DeclineIn, user: User = Depends(candidate),
                  db: Session = Depends(get_db)) -> dict:
    p = _own(db, Probe, probe_id, user, "probe_not_found", "Зонд не найден")
    return _probe_out(db, svc.decline_probe(db, p, data.reason), "candidate")
