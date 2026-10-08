"""«Кубок работодателя»: API работодателя и кандидата."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.cup import service as svc
from app.cup import tasks as auto
from app.cup.models import Cup, CupEntry
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import category_title
from app.modules.contact.salary import basis_out, basis_title
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation
from app.modules.jury import scope as jury_scope
from app.modules.matching.router import my_company
from app.modules.notifications.mailer import notify
from app.modules.profiles.models import CandidateProfile, Company

employer_router = APIRouter(prefix="/api/employer/cups", tags=["cups"])
candidate_router = APIRouter(prefix="/api/candidate/cups", tags=["cups"])
employer = require_role(UserRole.employer)
candidate = require_role(UserRole.candidate)
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 409: err("Нет профиля компании")}
C_AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
TAGS = [{"name": "cups", "description": "«Кубок работодателя»: соревнование в категории на базе зонда, таблица "
                                        "результатов под псевдонимами, приглашения лучшим, запись в паспорт ФСП"}]


# ------------------------------------------------------------------ схемы

class CriterionIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    weight: float = Field(gt=0, le=1)


class CupIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=20, max_length=5000, description="Суть кубка — видна до старта")
    category_id: str = Field(pattern=r"^(backend|frontend|data_ml|qa|security)\.(intern|junior|middle|senior)$")
    mode: Literal["auto", "rubric", "employer"] = "auto"
    task_text: str | None = Field(None, max_length=8000, description="Задача (rubric/employer) — после старта")
    rubric: list[CriterionIn] | None = Field(None, min_length=2, max_length=5)
    n_tasks: int = Field(5, ge=3, le=8, description="auto: число заданий банка")
    time_limit_min: int = Field(15, ge=5, le=120)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration_days: int | None = Field(None, ge=1, le=30, description="Если ends_at не задан")
    salary_from: int = Field(gt=0, le=10_000_000, description="Вилка «от», ₽ — обязательно")
    salary_to: int = Field(gt=0, le=10_000_000, description="Вилка «до», ₽ — обязательно")
    salary_basis: Literal["gross", "net"] = Field("gross", description="gross — до вычета НДФЛ, net — на руки")
    invite_top_n: int = Field(3, ge=1, le=10, description="Сколько лучших получат приглашение")
    min_score: float = Field(0.5, ge=0, le=1, description="Порог балла для приглашения, 0..1")
    position_title: str = Field(min_length=3, max_length=200)
    offer_description: str = Field(min_length=20, max_length=5000)
    contact_method: str = Field(min_length=3, max_length=255)

    @model_validator(mode="after")
    def _check(self):
        if self.salary_from > self.salary_to:
            raise ValueError("Нижняя граница вилки больше верхней")
        if self.salary_to > inv_svc.SALARY_MAX_RATIO * self.salary_from:  # то же правило, что у приглашений
            raise ValueError("Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от»")
        if self.mode != "auto" and len((self.task_text or "").strip()) < 20:
            raise ValueError("Опишите задачу кубка (не короче 20 символов)")
        return self


class ScoreIn(BaseModel):
    score_pct: float | None = Field(None, ge=0, le=100)
    criteria: dict[str, float] | None = Field(None, description="rubric: {id критерия: 0 | 0.5 | 1}")
    comment: str | None = Field(None, max_length=2000)


class SubmitIn(BaseModel):
    answers: dict[str, str | int | None] | None = Field(None, description="auto: {token задания: ответ}")
    text: str | None = Field(None, max_length=10000)
    link: str | None = Field(None, max_length=500)


class FinishIn(BaseModel):
    early: bool = Field(False, description="Завершить досрочно (окончание = сейчас)")


# ------------------------------------------------------------------ представления

def _iso(v) -> str | None:
    """Время всегда с часовым поясом (SQLite возвращает наивное UTC) — таймер кандидата не съезжает на часы."""
    return as_aware(v).isoformat() if v else None


def _pct(v: float | None) -> int | None:
    return None if v is None else round(v * 100)


def cup_out(db: Session, cup: Cup, side: str) -> dict:
    comp = db.get(Company, cup.company_id)
    cnt = dict(db.execute(select(CupEntry.status, func.count()).where(CupEntry.cup_id == cup.id)
                          .group_by(CupEntry.status)).all())
    out = {
        "id": str(cup.id), "title": cup.title, "description": cup.description, "category_id": cup.category_id,
        "category_title": category_title(cup.category_id), "direction": cup.direction_id, "grade": cup.grade_id,
        "mode": cup.mode, "mode_title": svc.MODES.get(cup.mode, cup.mode), "phase": svc.phase(cup), "status": cup.status,
        "starts_at": _iso(cup.starts_at), "ends_at": _iso(cup.ends_at),
        "time_limit_min": cup.time_limit_min, "n_tasks": len(cup.task_families or []),
        "salary_from": cup.salary_from, "salary_to": cup.salary_to, **basis_out(cup.salary_basis),
        "invite_top_n": cup.invite_top_n,
        "min_score_pct": _pct(cup.min_score), "position_title": cup.position_title,
        "offer_description": cup.offer_description, "contact_method": cup.contact_method,
        "rubric": [{"id": c["id"], "title": c["title"], "weight": c["weight"]} for c in svc.rubric_of(cup)]
        if cup.mode == "rubric" else None,
        "company": {"id": str(comp.id), "name": comp.name, "industry": comp.industry, "city": comp.city} if comp else None,
        "participants": sum(cnt.values()), "submitted": cnt.get("submitted", 0) + cnt.get("scored", 0),
        "to_review": cnt.get("submitted", 0), "summary": cup.summary or {},
        "finalized_at": _iso(cup.finalized_at), "is_demo": cup.is_demo,
    }
    if side == "employer":
        out["task_text"] = cup.task_text
    return out


def leaderboard(db: Session, cup: Cup, side: str, me: uuid.UUID | None = None) -> list[dict]:
    rows = svc.entries(db, cup.id)
    # участники из чужих песочниц жюри не видны (как в подборках: scope.visible), места считаются без них
    emails = dict(db.execute(select(User.id, User.email).where(User.id.in_([e.candidate_user_id for e in rows])))
                  .all()) if rows else {}
    rows = [e for e in rows if e.candidate_user_id == me or jury_scope.visible(emails.get(e.candidate_user_id))]
    order = svc.ranked(rows)
    pos = {e.id: i for i, e in enumerate(order, start=1)}
    finished = cup.status == "finished"
    out = []
    for e in sorted(rows, key=lambda x: (pos.get(x.id, 10**6), x.alias)):
        if e.status == "joined" and side != "employer" and e.candidate_user_id != me:
            continue
        r = {"alias": e.alias, "position": e.place if finished else pos.get(e.id), "status": e.status,
             "score_pct": _pct(e.score) if e.status == "scored" else None, "time_spent_s": e.time_spent_s,
             "me": e.candidate_user_id == me, "invited": bool(e.invitation_id)}
        if side == "employer":
            r["entry_id"] = str(e.id)
            r["invite_note"] = e.invite_note
            if e.invitation_id:  # без имён до приглашения: после — обезличенный номер, после принятия — имя
                inv = db.get(Invitation, e.invitation_id)
                prof = db.get(CandidateProfile, e.candidate_user_id)
                r["candidate_ref"] = prof.public_ref if prof else None
                r["invitation_status"] = inv.status.value if inv else None
                r["full_name"] = prof.full_name if (inv and inv.contacts_revealed_at and prof) else None
        out.append(r)
    return out


def entry_out(db: Session, cup: Cup, e: CupEntry | None) -> dict | None:
    if e is None:
        return None
    started = e.status not in ("joined",)
    return {"id": str(e.id), "alias": e.alias, "status": e.status,
            "started_at": _iso(e.started_at),
            "deadline_at": _iso(e.deadline_at),
            "submitted_at": _iso(e.submitted_at),
            "time_spent_s": e.time_spent_s, "score_pct": _pct(e.score) if e.status == "scored" else None,
            "score_method": e.score_method, "place": e.place,
            "task_text": cup.task_text if started else None,
            "tasks": auto.public_tasks(e.tasks or [], reveal_result=cup.status == "finished") if started else [],
            "answer": {"text": e.answer.get("text"), "link": e.answer.get("link")} if e.answer else None,
            "auto": e.grading if cup.mode == "auto" and e.status == "scored" else None,
            "invitation_id": str(e.invitation_id) if e.invitation_id else None,
            "invitation_status": svc.invitation_status(db, e), "invite_note": e.invite_note,
            "passport_status": e.passport_status}


def solutions_out(db: Session, cup: Cup) -> list[dict]:
    """Решения для оценки работодателем — вслепую: псевдоним, текст без ПДн, ссылки скрыты."""
    out = []
    for e in svc.entries(db, cup.id):
        if e.status not in ("submitted", "scored"):
            continue
        g = e.grading or {}
        out.append({"entry_id": str(e.id), "alias": e.alias, "status": e.status,
                    "submitted_at": _iso(e.submitted_at),
                    "time_spent_s": e.time_spent_s, "score_pct": _pct(e.score), "score_method": e.score_method,
                    "text": (e.answer or {}).get("text_redacted"), "has_link": bool((e.answer or {}).get("link")),
                    "redacted": (e.answer or {}).get("redacted") or [],
                    "llm": {k: g["llm"].get(k) for k in ("status", "score", "criteria", "comment", "model")}
                    if g.get("llm") else None,
                    "employer": g.get("employer"), "auto": {"correct": g.get("correct"), "total": g.get("total")}
                    if cup.mode == "auto" else None})
    return out


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def notify_invited(bg: BackgroundTasks, db: Session, cup: Cup, inv_ids: list[uuid.UUID]) -> None:
    from app.integrations import events as integration_events

    comp = db.get(Company, cup.company_id)
    for iid in inv_ids:
        inv = db.get(Invitation, iid)
        cu = db.get(User, inv.candidate_user_id) if inv else None
        if not cu:
            continue
        bg.add_task(notify, cu.email, f"Приглашение по итогам кубка «{cup.title}»",
                    [f"Компания {comp.name if comp else ''} приглашает вас на позицию «{cup.position_title}» "
                     f"по итогам Кубка работодателя.",
                     f"Вилка зарплаты: {_rub(cup.salary_from)} – {_rub(cup.salary_to)} {basis_title(cup.salary_basis)}.",
                     "Ваши контакты работодатель увидит, только если вы примете приглашение."],
                    is_demo=cu.is_demo, link_path="/candidate/invitations")
        bg.add_task(integration_events.invitation_sent, iid)


def _own_cup(db: Session, user: User, cup_id: uuid.UUID) -> tuple[Cup, Company]:
    c = my_company(db, user)
    cup = db.get(Cup, cup_id)
    if cup is None or cup.company_id != c.id:
        raise api_error(404, "cup_not_found", "Кубок не найден")
    return cup, c


def _refresh(bg: BackgroundTasks, db: Session, cup: Cup) -> Cup:
    svc.close_expired(db, cup)
    inv = svc.maybe_auto_finalize(db, cup)
    if inv:
        notify_invited(bg, db, cup, inv)
    return db.get(Cup, cup.id)


# ------------------------------------------------------------------ работодатель

@employer_router.get("/options", summary="Подсказки для формы кубка: рынок категории, кандидаты, задания банка",
                     responses=E_AUTH)
def options(category_id: str = Query(pattern=r"^[a-z_]+\.[a-z]+$"), user: User = Depends(employer),
            db: Session = Depends(get_db)) -> dict:
    my_company(db, user)
    cat = db.get(Category, category_id)
    if cat is None:
        raise api_error(404, "category_not_found", "Категория не найдена")
    n = db.scalar(select(func.count()).select_from(CandidateProfile).where(
        CandidateProfile.current_category_id == category_id, CandidateProfile.visible_to_employers.is_(True))) or 0
    fam = auto.available_families(cat.direction_id, cat.grade_id)
    return {"category_id": cat.id, "category_title": cat.title,
            "market": {"from": cat.market_salary_from, "to": cat.market_salary_to, "median": cat.market_salary_median},
            "candidates": n, "auto_tasks_available": len(fam[cat.direction_id]) + len(fam["common"]),
            "modes": svc.MODES, "default_rubric": svc.DEFAULT_RUBRIC}


@employer_router.get("", summary="Кубки моей компании", responses=E_AUTH)
def my_cups(bg: BackgroundTasks, user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    from app.cup import demo

    demo.ensure_jury_cups(db, user, c)  # демо жюри, созданное до появления кубков: досоздать (один раз)
    rows = db.scalars(select(Cup).where(Cup.company_id == c.id).order_by(Cup.created_at.desc())).all()
    return [cup_out(db, _refresh(bg, db, cup), "employer") for cup in rows]


@employer_router.post("", status_code=201, summary="Запустить кубок в категории (вилка обязательна)",
                      responses={**E_AUTH, 422: err("Нет вилки, задачи или срок некорректен")})
def create(data: CupIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    cup = svc.create_cup(db, user, c, data.model_dump(exclude={"rubric"}) | {
        "rubric": [r.model_dump() for r in data.rubric] if data.rubric else None})
    return cup_out(db, cup, "employer")


@employer_router.get("/{cup_id}", summary="Кубок: таблица результатов и решения для оценки", responses=E_AUTH)
def get_cup(cup_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(employer),
            db: Session = Depends(get_db)) -> dict:
    cup, _ = _own_cup(db, user, cup_id)
    cup = _refresh(bg, db, cup)
    return {**cup_out(db, cup, "employer"), "leaderboard": leaderboard(db, cup, "employer"),
            "solutions": solutions_out(db, cup)}


@employer_router.post("/{cup_id}/entries/{entry_id}/score", summary="Оценить решение (rubric / employer)",
                      responses={**E_AUTH, 404: err("Не найдено"), 409: err("Нельзя оценить")})
def score(cup_id: uuid.UUID, entry_id: uuid.UUID, data: ScoreIn, bg: BackgroundTasks, user: User = Depends(employer),
          db: Session = Depends(get_db)) -> dict:
    cup, _ = _own_cup(db, user, cup_id)
    e = db.get(CupEntry, entry_id)
    if e is None or e.cup_id != cup.id:
        raise api_error(404, "cup_entry_not_found", "Решение не найдено")
    svc.score_by_employer(db, cup, e, score_pct=data.score_pct, criteria=data.criteria, comment=data.comment)
    return get_cup(cup_id, bg, user, db)


@employer_router.post("/{cup_id}/finish", summary="Подвести итоги: места, паспорт ФСП, приглашения лучшим",
                      responses={**E_AUTH, 404: err("Не найдено"), 409: err("Кубок идёт или есть неоценённые")})
def finish(cup_id: uuid.UUID, data: FinishIn, bg: BackgroundTasks, user: User = Depends(employer),
           db: Session = Depends(get_db)) -> dict:
    cup, _ = _own_cup(db, user, cup_id)
    inv = svc.finalize(db, cup, user, early=data.early)
    cup = db.get(Cup, cup_id)
    notify_invited(bg, db, cup, inv)
    return get_cup(cup_id, bg, user, db)


@employer_router.post("/{cup_id}/cancel", summary="Отменить кубок, пока никто не прислал решение",
                      responses={**E_AUTH, 404: err("Не найдено"), 409: err("Уже есть решения")})
def cancel(cup_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    cup, _ = _own_cup(db, user, cup_id)
    if cup.status != "active" or any(e.status in ("submitted", "scored") for e in svc.entries(db, cup.id)):
        raise api_error(409, "cup_cannot_cancel", "Отменить можно только кубок без присланных решений")
    cup.status = "cancelled"
    db.commit()
    return cup_out(db, cup, "employer")


# ------------------------------------------------------------------ кандидат

def _sees(cup: Cup, user: User) -> bool:
    """Кубок демо жюри виден только кандидатам своей песочницы; кубки платформы — всем."""
    return cup.jury_scope is None or cup.jury_scope == jury_scope.key_of(user.email)


def _cand_cup(db: Session, user: User, cup_id: uuid.UUID) -> Cup:
    cup = db.get(Cup, cup_id)
    if cup is None or cup.status == "cancelled" or not _sees(cup, user):
        raise api_error(404, "cup_not_found", "Кубок не найден")
    p = db.get(CandidateProfile, user.id)
    if (p is None or p.current_category_id != cup.category_id) and svc.entry_of(db, cup.id, user.id) is None:
        raise api_error(404, "cup_not_found", "Кубок не найден — он проходит в другой категории")
    return cup


def _cand_view(db: Session, cup: Cup, user: User) -> dict:
    e = svc.entry_of(db, cup.id, user.id)
    p = db.get(CandidateProfile, user.id)
    return {**cup_out(db, cup, "candidate"), "my_entry": entry_out(db, cup, e),
            "below_my_minimum": inv_svc.below_minimum(p, cup.salary_to, cup.salary_basis) if p else False,
            "can_join": e is None and svc.phase(cup) in ("upcoming", "active") and p is not None
            and p.current_category_id == cup.category_id,
            "profile_visible": bool(p and p.visible_to_employers),
            "leaderboard": leaderboard(db, cup, "candidate", user.id)}


@candidate_router.get("", summary="Кубки моей категории и мои участия", responses=C_AUTH)
def cand_cups(bg: BackgroundTasks, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = db.get(CandidateProfile, user.id)
    svc.sync_passport(db, user.id)
    mine = set(db.scalars(select(CupEntry.cup_id).where(CupEntry.candidate_user_id == user.id)).all())
    q = select(Cup).where(Cup.status != "cancelled")
    cat = p.current_category_id if p else None
    rows = [c for c in db.scalars(q.order_by(Cup.ends_at.desc())).all()
            if (c.id in mine or c.category_id == cat) and _sees(c, user)]
    items = []
    for cup in rows:
        cup = _refresh(bg, db, cup)
        e = svc.entry_of(db, cup.id, user.id)
        items.append({**cup_out(db, cup, "candidate"), "my_status": e.status if e else None,
                      "my_place": e.place if e else None,
                      "below_my_minimum": inv_svc.below_minimum(p, cup.salary_to, cup.salary_basis) if p else False})
    return {"category_id": cat, "category_title": category_title(cat) if cat else None, "items": items}


@candidate_router.get("/passport", summary="Мои места в кубках — записи паспорта ФСП (мероприятия платформы)",
                      responses=C_AUTH)
def cand_passport(user: User = Depends(candidate), db: Session = Depends(get_db)) -> list[dict]:
    svc.sync_passport(db, user.id)
    out = []
    for e in db.scalars(select(CupEntry).where(CupEntry.candidate_user_id == user.id, CupEntry.place.is_not(None))
                        .order_by(CupEntry.updated_at.desc())).all():
        cup = db.get(Cup, e.cup_id)
        comp = db.get(Company, cup.company_id) if cup else None
        total = int((cup.summary or {}).get("placed") or e.place)
        out.append({"cup_id": str(cup.id), "title": cup.title, "company": comp.name if comp else None,
                    "category_title": category_title(cup.category_id), "date": cup.ends_at.date().isoformat(),
                    "place": e.place, "of": total, "result_title": svc.result_title(e.place),
                    "score_pct": _pct(e.score), "level": "T1", "event_level": "platform",
                    "passport_status": e.passport_status, "invited": bool(e.invitation_id)})
    return out


@candidate_router.get("/{cup_id}", summary="Кубок: условия, моё участие, таблица результатов", responses=C_AUTH)
def cand_cup(cup_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(candidate),
             db: Session = Depends(get_db)) -> dict:
    cup = _refresh(bg, db, _cand_cup(db, user, cup_id))
    return _cand_view(db, cup, user)


@candidate_router.post("/{cup_id}/join", summary="Записаться в кубок", responses={**C_AUTH, 409: err("Нельзя")})
def cand_join(cup_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    cup = _cand_cup(db, user, cup_id)
    svc.join(db, cup, user)
    return _cand_view(db, cup, user)


@candidate_router.post("/{cup_id}/leave", summary="Отменить запись (до старта решения)", responses=C_AUTH)
def cand_leave(cup_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    cup = _cand_cup(db, user, cup_id)
    e = svc.entry_of(db, cup.id, user.id)
    if e is None:
        raise api_error(404, "cup_entry_not_found", "Вы не записаны в этот кубок")
    svc.leave(db, cup, e)
    return _cand_view(db, cup, user)


@candidate_router.post("/{cup_id}/start", summary="Начать решение — пошёл таймер", responses={**C_AUTH, 409: err("Нельзя")})
def cand_start(cup_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    cup = _cand_cup(db, user, cup_id)
    e = svc.entry_of(db, cup.id, user.id) or svc.join(db, cup, user)
    svc.start(db, cup, e)
    return _cand_view(db, cup, user)


@candidate_router.post("/{cup_id}/submit", summary="Отправить решение", responses={**C_AUTH, 409: err("Время вышло")})
def cand_submit(cup_id: uuid.UUID, data: SubmitIn, user: User = Depends(candidate),
                db: Session = Depends(get_db)) -> dict:
    cup = _cand_cup(db, user, cup_id)
    e = svc.entry_of(db, cup.id, user.id)
    if e is None:
        raise api_error(404, "cup_entry_not_found", "Вы не записаны в этот кубок")
    svc.submit(db, cup, e, answers=data.answers, text=data.text, link=data.link)
    return _cand_view(db, cup, user)
