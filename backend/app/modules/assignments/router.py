"""Задания работодателя: API работодателя (сборка, зонд, вакансия, открытое) и кандидата (лента, решение)."""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.assignments import feed
from app.modules.assignments import rubric as rub
from app.modules.assignments import service as svc
from app.modules.assignments.models import Assignment, AssignmentAttempt
from app.modules.auth.models import User
from app.modules.tariffs.service import require_feature
from app.modules.invitations.service import profile_by_ref
from app.modules.matching.router import my_company
from app.modules.jury import scope as jury_scope
from app.modules.profiles import freshness
from app.modules.profiles.facts import load_bundles
from app.modules.profiles.models import CandidateProfile

employer_router = APIRouter(prefix="/api/employer/assignments", tags=["assignments"])
candidate_router = APIRouter(prefix="/api/candidate/assignments", tags=["assignments"])
employer = require_role(UserRole.employer)
candidate = require_role(UserRole.candidate)
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 409: err("Нет профиля компании")}
C_AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
TAGS = [{"name": "assignments", "description": "Задания работодателя с автопроверкой: сборка 3–5 заданий банка по "
                                               "стеку потребности или вакансии, зонд кандидату, задание к вакансии, "
                                               "лента «Задания для вас»; результат — факт T1 по навыку"}]


# ------------------------------------------------------------------ схемы

class SourceIn(BaseModel):
    need_id: uuid.UUID | None = None
    vacancy_id: uuid.UUID | None = None
    stack: list[str] | None = Field(None, max_length=20, description="Теги стека вручную (дополняют источник)")
    direction: str | None = Field(None, pattern=r"^(backend|frontend|data_ml|qa|security)$")
    grade: str | None = Field(None, pattern=r"^(junior|middle|senior)$")
    n_tasks: int = Field(5, ge=3, le=5)
    with_approach: bool = Field(False, description="К5: попросить описать подход — его оценивает работодатель по рубрике")
    approach_prompt: str | None = Field(None, max_length=1000, description="Текст просьбы о подходе (по умолчанию — типовой)")


class AssignmentIn(SourceIn):
    mode: Literal["probe", "vacancy", "open"]
    title: str | None = Field(None, min_length=3, max_length=200)
    description: str = Field("", max_length=3000, description="Что проверяем — видно кандидату до старта")
    time_limit_min: int | None = Field(None, ge=5, le=60)
    salary_from: int | None = Field(None, gt=0, le=10_000_000, description="probe/open: вилка обязательна")
    salary_to: int | None = Field(None, gt=0, le=10_000_000)
    candidate_refs: list[str] = Field(default_factory=list, max_length=20, description="probe: кому отправить")


class SendIn(BaseModel):
    candidate_refs: list[str] = Field(min_length=1, max_length=20)


class SubmitIn(BaseModel):
    answers: dict[str, str | int | None] = Field(default_factory=dict, description="token → ответ")
    approach: str | None = Field(None, max_length=4000, description="Ответ о подходе, если задание его просит")


class ReviewIn(BaseModel):
    scores: dict[str, int] = Field(description="критерий рубрики (kind=employer) → баллы одного из описанных уровней")
    comment: str | None = Field(None, max_length=1000)


class PrefsIn(BaseModel):
    frequency_days: Literal[0, 7, 14] = Field(description="Как часто предлагать задания в ленте, дней; 0 — не предлагать")


def _src(s: SourceIn) -> dict:
    return {"need_id": s.need_id, "vacancy_id": s.vacancy_id, "stack": s.stack, "direction": s.direction,
            "grade": s.grade}


# ------------------------------------------------------------------ работодатель

@employer_router.post("/preview", summary="Собрать задание по требованиям: какие семейства банка и покрытие стека",
                      responses={**E_AUTH, 404: err("Потребность или вакансия не найдена"),
                                 422: err("Нужна категория")})
def preview(body: SourceIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return svc.preview(db, my_company(db, user), n_tasks=body.n_tasks, **_src(body))


@employer_router.post("", status_code=201, summary="Создать задание: зонд кандидатам, к вакансии или открытое",
                      dependencies=[Depends(require_feature("assignments"))],  # Я29: тариф «Найм»/«Партнёр ФСП»
                      responses={**E_AUTH, 404: err("Источник или кандидат не найден"),
                                 409: err("У вакансии уже есть задание"), 422: err("Вилка или категория")})
def create(body: AssignmentIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    if body.mode == "probe" and not body.candidate_refs:
        raise api_error(422, "candidates_required", "Выберите кандидатов, которым отправить задание")
    cands = [profile_by_ref(db, r) for r in dict.fromkeys(body.candidate_refs)] if body.mode == "probe" else []
    a = svc.create(db, c, user, mode=body.mode, title=body.title, description=body.description,
                   n_tasks=body.n_tasks, time_limit_min=body.time_limit_min, salary_from=body.salary_from,
                   salary_to=body.salary_to, with_approach=body.with_approach, approach_prompt=body.approach_prompt,
                   **_src(body))
    sent = 0
    for p in cands:
        u = db.get(User, p.user_id)
        if u and svc.offer(db, a, u, "probe") is not None:
            sent += 1
    db.commit()
    return {**_out(db, a), "sent": sent}


@employer_router.get("", summary="Мои задания с итогами по кандидатам", responses=E_AUTH)
def my_assignments(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    if any(feed.maintenance(db, company_id=c.id).values()):
        db.commit()  # напоминание об оценке по рубрике — при открытии списка, как и фоновым обходом
    rows = db.scalars(select(Assignment).where(Assignment.company_id == c.id)
                      .order_by(Assignment.created_at.desc())).all()
    return [_out(db, a) for a in rows]


@employer_router.get("/{aid}", summary="Задание и попытки кандидатов (обезличенно)",
                     responses={**E_AUTH, 404: err("Задание не найдено")})
def one(aid: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    a = _mine(db, user, aid)
    return {**_out(db, a), "attempts": _attempts(db, a)}


@employer_router.post("/{aid}/send", summary="Отправить задание ещё кандидатам (как зонд)",
                      responses={**E_AUTH, 404: err("Задание или кандидат не найден"), 409: err("Задание закрыто")})
def send(aid: uuid.UUID, body: SendIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    a = _mine(db, user, aid)
    if a.status != "active":
        raise api_error(409, "assignment_closed", "Задание закрыто")
    sent = 0
    for r in dict.fromkeys(body.candidate_refs):
        u = db.get(User, profile_by_ref(db, r).user_id)
        if u and svc.offer(db, a, u, "probe") is not None:
            sent += 1
    db.commit()
    return {**_out(db, a), "sent": sent, "attempts": _attempts(db, a)}


@employer_router.post("/{aid}/attempts/{atid}/review", summary="Оценить подход кандидата по рубрике: баллы критериев работодателя",
                      responses={**E_AUTH, 404: err("Задание или попытка не найдены"), 409: err("Оценить нельзя"),
                                 422: err("Баллы вне описанных уровней")})
def review(aid: uuid.UUID, atid: uuid.UUID, body: ReviewIn, user: User = Depends(employer),
           db: Session = Depends(get_db)) -> dict:
    a = _mine(db, user, aid)
    at = db.get(AssignmentAttempt, atid)
    if at is None or at.assignment_id != a.id:
        raise api_error(404, "attempt_not_found", "Попытка не найдена")
    svc.review(db, at, a, body.scores, body.comment)
    db.commit()
    return {**_out(db, a), "attempts": _attempts(db, a)}


@employer_router.post("/{aid}/close", summary="Закрыть задание: новые попытки не выдаются",
                      responses={**E_AUTH, 404: err("Задание не найдено")})
def close(aid: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    a = _mine(db, user, aid)
    a.status = "closed"
    db.commit()
    return _out(db, a)


def _mine(db: Session, user: User, aid: uuid.UUID) -> Assignment:
    c = my_company(db, user)
    a = db.get(Assignment, aid)
    if a is None or a.company_id != c.id:
        raise api_error(404, "assignment_not_found", "Задание не найдено")
    return a


def _out(db: Session, a: Assignment) -> dict:
    counts = dict(db.execute(select(AssignmentAttempt.status, func.count()).where(AssignmentAttempt.assignment_id == a.id)
                             .group_by(AssignmentAttempt.status)).all())
    to_review = db.scalar(select(func.count()).select_from(AssignmentAttempt).where(
        AssignmentAttempt.assignment_id == a.id, AssignmentAttempt.status == "scored",
        AssignmentAttempt.review_status == "pending")) or 0
    return {**svc.assignment_out(db, a), "attempts_total": sum(counts.values()), "attempts_by_status": counts,
            "to_review": to_review}


def _attempts(db: Session, a: Assignment) -> list[dict]:
    rows = db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.assignment_id == a.id)
                      .order_by(AssignmentAttempt.offered_at.desc())).all()
    out = []
    for at in rows:
        svc.expire_overdue(db, at)
        p = db.get(CandidateProfile, at.candidate_user_id)
        out.append({**svc.attempt_brief(at, a, "employer"), "candidate_ref": p.public_ref if p else None,
                    "candidate_category": p.current_category_id if p else None,
                    "approach_text": at.approach_text if at.status == "scored" else None,
                    "review_remind_at": at.review_remind_at, "review_remind_count": at.review_remind_count})
    if any(at.status == "expired" for at in rows):
        db.commit()
    return out


# ------------------------------------------------------------------ кандидат

@candidate_router.get("", summary="Мои задания: зонды, к откликам и лента «Задания для вас»", responses=C_AUTH)
def my_attempts(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    feed.maintenance(db, user_id=user.id)  # истёкшие предложения и напоминания — до выдачи нового
    offered = feed.offer_if_due(db, user)
    rows = db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.candidate_user_id == user.id)
                      .order_by(AssignmentAttempt.offered_at.desc())).all()
    items = []
    for at in rows:
        svc.expire_overdue(db, at)
        a = db.get(Assignment, at.assignment_id)
        items.append({**svc.attempt_brief(at, a), "assignment": svc.assignment_out(db, a, for_candidate=True)})
    p = db.get(CandidateProfile, user.id)
    b = load_bundles(db, [user.id]).get(user.id)
    out = {"items": items, "feed_days": feed.feed_days(), "new_offer": str(offered.id) if offered else None,
           "has_category": bool(p and p.current_category_id), "schedule": feed.schedule(db, user),
           "freshness": freshness.summary(b.skills_t1) if b else None,
           "demo": jury_scope.key_of(user.email) is not None}
    db.commit()
    return out


@candidate_router.put("/prefs", summary="Как часто система предлагает задания в ленте (7 или 14 дней, 0 — выключить)",
                      responses=C_AUTH)
def set_prefs(body: PrefsIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    feed.set_freq(db, user.id, body.frequency_days)
    db.commit()
    return feed.schedule(db, user)


@candidate_router.post("/demo/next-week", summary="Только песочница жюри: «прошла неделя» — напоминание, истечение, новое предложение",
                       responses={**C_AUTH, 403: err("Только для демо-кандидата песочницы жюри")})
def demo_next_week(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    if jury_scope.key_of(user.email) is None or not user.is_demo:
        raise api_error(403, "jury_only", "Моделирование недели доступно только в песочнице жюри")
    return feed.demo_fast_forward(db, user)


@candidate_router.get("/{atid}", summary="Задание: описание, варианты (после старта), результат",
                      responses={**C_AUTH, 404: err("Задание не найдено")})
def one_attempt(atid: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    at, a = _own(db, user, atid)
    out = svc.attempt_out(db, at, a)
    db.commit()
    return out


@candidate_router.post("/{atid}/start", summary="Начать: выдаются варианты, идёт отсчёт времени",
                       responses={**C_AUTH, 404: err("Задание не найдено"), 409: err("Задание закрыто")})
def start(atid: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    at, a = _own(db, user, atid)
    svc.start(db, at, a)
    db.commit()
    return svc.attempt_out(db, at, a)


@candidate_router.post("/{atid}/submit", summary="Отправить ответы: автопроверка, факт T1, уведомление работодателю",
                       responses={**C_AUTH, 404: err("Задание не найдено"), 409: err("Сначала начните задание")})
def submit(atid: uuid.UUID, body: SubmitIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    at, a = _own(db, user, atid)
    svc.submit(db, at, a, body.answers, body.approach)
    db.commit()
    return svc.attempt_out(db, at, a)


@candidate_router.post("/{atid}/decline", summary="Отказаться от задания (на рейтинг не влияет)",
                       responses={**C_AUTH, 404: err("Задание не найдено"), 409: err("Попытка уже завершена")})
def decline(atid: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    at, a = _own(db, user, atid)
    svc.decline(db, at)
    db.commit()
    return svc.attempt_out(db, at, a)


def _own(db: Session, user: User, atid: uuid.UUID) -> tuple[AssignmentAttempt, Assignment]:
    at = db.get(AssignmentAttempt, atid)
    if at is None or at.candidate_user_id != user.id:
        raise api_error(404, "attempt_not_found", "Задание не найдено")
    return at, db.get(Assignment, at.assignment_id)
