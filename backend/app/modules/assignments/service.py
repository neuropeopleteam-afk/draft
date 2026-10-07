"""Задания работодателя: сборка по требованиям, выдача кандидату, автопроверка, факты T1, уведомления."""
from __future__ import annotations

from datetime import timedelta
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource
from app.core.errors import api_error
from app.cup import tasks as auto
from app.integrations.push.service import send_to_user
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.assignments import bank
from app.modules.assignments.models import Assignment, AssignmentAttempt
from app.modules.auth.models import User
from app.modules.catalog.seed_data import STACK, category_title
from app.modules.jury import scope as jury_scope
from app.modules.matching.models import EmployerNeed
from app.modules.notifications.mailer import notify
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateProfile, Company
from app.modules.profiles.models import CandidateFact

log = logging.getLogger(__name__)

GRACE_S = 120  # после дедлайна ответ принимается ещё две минуты (как в кубке)
SOURCE_REF = "assignment:"  # source_ref фактов: assignment:<attempt_id>
SOURCE_TITLE = {"probe": "зонд с автопроверкой", "vacancy": "задание к вакансии", "feed": "задание из ленты"}


def tag_title(t: str) -> str:
    return STACK.get(t, (t,))[0]


# ------------------------------------------------------------------ требования: откуда стек и категория

def requirements_from(db: Session, company: Company, *, need_id=None, vacancy_id=None, stack=None,
                      direction=None, grade=None) -> dict:
    """Стек, направление, грейд и подсказки (название, вилка) из потребности, вакансии или вручную."""
    out: dict = {"stack": [], "direction": direction, "grade": grade, "title": None, "salary_from": None,
                 "salary_to": None, "need_id": None, "vacancy_id": None}
    if need_id:
        n = db.get(EmployerNeed, need_id)
        if n is None or n.company_id != company.id:
            raise api_error(404, "need_not_found", "Потребность не найдена")
        req = n.requirements or {}
        out["stack"] = [x["tag"] for x in (req.get("stack_required") or []) + (req.get("stack_desired") or [])
                        if x.get("tag")]
        out["direction"] = out["direction"] or req.get("direction") or n.direction_id
        out["grade"] = out["grade"] or req.get("grade") or n.grade_id
        out["title"] = f"Задание по требованиям: {n.title}"
        out["salary_from"], out["salary_to"] = req.get("salary_from") or n.salary_from, req.get("salary_to") or n.salary_to
        out["need_id"] = n.id
    if vacancy_id:
        v = db.get(Vacancy, vacancy_id)
        if v is None or v.company_id != company.id:
            raise api_error(404, "vacancy_not_found", "Вакансия не найдена")
        out["stack"] = out["stack"] or list(v.stack or [])
        d, _, g = (v.category_id or "").partition(".")
        out["direction"] = out["direction"] or d or None
        out["grade"] = out["grade"] or g or None
        out["title"] = f"Задание к вакансии: {v.title}"
        out["salary_from"], out["salary_to"] = v.salary_from, v.salary_to
        out["vacancy_id"] = v.id
    if stack:
        out["stack"] = list(dict.fromkeys(list(stack) + out["stack"]))
    out["stack"] = [t for t in out["stack"] if t in STACK]
    if not out["direction"] or not out["grade"]:
        raise api_error(422, "category_required", "Укажите направление и грейд (категорию) задания")
    return out


def preview(db: Session, company: Company, *, n_tasks: int = 5, seed: int | None = None, **src) -> dict:
    r = requirements_from(db, company, **src)
    fams = bank.pick(r["direction"], r["grade"], r["stack"], n_tasks, seed=seed)
    cov = bank.coverage_for(r["direction"], r["grade"], r["stack"])
    return {**r, "need_id": str(r["need_id"]) if r["need_id"] else None,
            "vacancy_id": str(r["vacancy_id"]) if r["vacancy_id"] else None,
            "category_title": category_title(f"{r['direction']}.{r['grade']}"),
            "stack_titles": [tag_title(t) for t in r["stack"]],
            "families": bank.families_public(fams), "n_tasks": len(fams),
            "coverage": {"covered": cov["covered"], "missing": cov["missing"],
                         "missing_titles": [tag_title(t) for t in cov["missing"]]},
            "time_limit_min": suggested_time(fams)}


def suggested_time(fams: list[dict]) -> int:
    s = sum(int(f.get("time_limit_s") or 300) for f in fams)
    return max(5, min(60, -(-s // 60) + 2))


# ------------------------------------------------------------------ создание

def create(db: Session, company: Company, user: User, *, mode: str, title: str | None, description: str,
           n_tasks: int, time_limit_min: int | None, salary_from: int | None, salary_to: int | None,
           **src) -> Assignment:
    r = requirements_from(db, company, **src)
    fams = bank.pick(r["direction"], r["grade"], r["stack"], n_tasks)
    if len(fams) < bank.N_MIN:
        raise api_error(409, "bank_insufficient", "В банке недостаточно заданий с автопроверкой для этой категории")
    if mode == "vacancy":
        if not r["vacancy_id"]:
            raise api_error(422, "vacancy_required", "Для задания к вакансии укажите вакансию")
        if active_for_vacancy(db, r["vacancy_id"]) is not None:
            raise api_error(409, "assignment_exists", "У вакансии уже есть активное задание — сначала закройте его")
        salary_from, salary_to = r["salary_from"], r["salary_to"]
    else:
        from app.modules.invitations.service import check_salary

        salary_from, salary_to = salary_from or r["salary_from"], salary_to or r["salary_to"]
        check_salary(salary_from, salary_to)  # зонд и открытое задание — предложение, вилка обязательна
    a = Assignment(
        company_id=company.id, created_by=user.id, need_id=r["need_id"], vacancy_id=r["vacancy_id"], mode=mode,
        title=(title or r["title"] or "Задание работодателя")[:200], description=description or "",
        direction_id=r["direction"], grade_id=r["grade"], stack_tags=r["stack"], families=fams,
        coverage=bank.coverage_for(r["direction"], r["grade"], r["stack"]), n_tasks=len(fams),
        time_limit_min=time_limit_min or suggested_time(fams), salary_from=salary_from, salary_to=salary_to,
        is_demo=bool(user.is_demo), jury_scope=jury_scope.key_of(user.email),
    )
    db.add(a)
    db.flush()
    return a


def active_for_vacancy(db: Session, vacancy_id) -> Assignment | None:
    return db.scalar(select(Assignment).where(Assignment.vacancy_id == vacancy_id, Assignment.mode == "vacancy",
                                              Assignment.status == "active").order_by(Assignment.created_at.desc()))


# ------------------------------------------------------------------ выдача кандидату

def offer(db: Session, a: Assignment, cand: User, source: str, *, application_id=None,
          send: bool = True) -> AssignmentAttempt | None:
    """Предложить задание кандидату (одна попытка на задание). Уведомление — письмо и push."""
    ex = db.scalar(select(AssignmentAttempt).where(AssignmentAttempt.assignment_id == a.id,
                                                   AssignmentAttempt.candidate_user_id == cand.id))
    if ex is not None:
        return None
    at = AssignmentAttempt(assignment_id=a.id, candidate_user_id=cand.id, source=source,
                           application_id=application_id, status="offered", offered_at=utcnow())
    db.add(at)
    db.flush()
    if send:
        company = db.get(Company, a.company_id)
        path = f"/candidate/assignments/{at.id}"
        head = {"probe": "Задание с автопроверкой от компании", "vacancy": "К отклику прилагается задание компании",
                "feed": "Задание для вас от компании"}[source]
        notify(cand.email, f"{head} {company.name if company else ''}".strip(),
               [f"«{a.title}»: {a.n_tasks} заданий банка по стеку {', '.join(tag_title(t) for t in a.stack_tags[:5])}, "
                f"{a.time_limit_min} минут. Проверка автоматическая, результат станет фактом T1 в вашем профиле.",
                "Задание необязательно: отказ не влияет на рейтинг и категорию."],
               is_demo=cand.is_demo, link_path=path)
        try:
            send_to_user(db, cand.id, f"{head} {company.name if company else ''}".strip(),
                         f"«{a.title}» · {a.n_tasks} заданий · {a.time_limit_min} мин", path, f"assignment-{at.id}")
        except Exception:  # noqa: BLE001 — push не должен ломать основной сценарий
            log.exception("push о задании не отправлен")
    return at


def start(db: Session, at: AssignmentAttempt, a: Assignment) -> AssignmentAttempt:
    if a.status != "active":
        raise api_error(409, "assignment_closed", "Работодатель закрыл это задание")
    if at.status == "offered":
        at.tasks = auto.issue([f["family_id"] for f in a.families])
        at.started_at = utcnow()
        at.deadline_at = at.started_at + timedelta(minutes=a.time_limit_min)
        at.status = "in_progress"
        db.flush()
    elif at.status != "in_progress":
        raise api_error(409, "attempt_closed", "Попытка уже завершена")
    return at


def submit(db: Session, at: AssignmentAttempt, a: Assignment, answers: dict) -> AssignmentAttempt:
    if at.status != "in_progress":
        raise api_error(409, "attempt_not_started", "Сначала начните задание")
    now = utcnow()
    at.submitted_at = now
    at.time_spent_s = int((now - as_aware(at.started_at)).total_seconds()) if at.started_at else None
    if at.deadline_at and now > as_aware(at.deadline_at) + timedelta(seconds=GRACE_S):
        at.status = "expired"
        db.flush()
        return at
    items = list(at.tasks)
    at.score = auto.score(items, answers or {})
    at.tasks = items  # новый список — SQLAlchemy увидит изменение JSON
    at.correct = sum(1 for it in items if it.get("correct"))
    at.total = len(items)
    at.skills = _skills(items)
    at.status = "scored"
    at.score_method = "auto"
    db.flush()
    write_facts(db, at, a)
    _notify_employer(db, at, a)
    return at


def decline(db: Session, at: AssignmentAttempt) -> AssignmentAttempt:
    if at.status not in ("offered", "in_progress"):
        raise api_error(409, "attempt_closed", "Попытка уже завершена")
    at.status = "declined"
    db.flush()
    return at


def expire_overdue(db: Session, at: AssignmentAttempt) -> None:
    """Время вышло, ответа нет — попытка истекает при следующем обращении."""
    if at.status == "in_progress" and at.deadline_at and utcnow() > as_aware(at.deadline_at) + timedelta(seconds=GRACE_S):
        at.status = "expired"
        db.flush()


def _skills(items: list[dict]) -> dict:
    """По каждому тегу стека: сколько заданий с этим тегом и сколько верно."""
    from assessment_bank import load_specs

    specs = load_specs()
    acc: dict[str, dict] = {}
    for it in items:
        spec = specs.get(it["family_id"])
        if spec is None:
            continue
        for t in bank.family_tags(spec):
            d = acc.setdefault(t, {"correct": 0, "total": 0})
            d["total"] += 1
            d["correct"] += int(bool(it.get("correct")))
    for d in acc.values():
        d["score"] = round(d["correct"] / d["total"], 4) if d["total"] else 0.0
    return acc


# ------------------------------------------------------------------ факты T1

def write_facts(db: Session, at: AssignmentAttempt, a: Assignment) -> None:
    """Результат — факты T1: по навыку (kind=skill, сливаются с тестом в load_bundles) и общий (kind=probe)."""
    ref = f"{SOURCE_REF}{at.id}"
    for f in db.scalars(select(CandidateFact).where(CandidateFact.source_ref == ref)).all():
        db.delete(f)
    company = db.get(Company, a.company_id)
    cname = company.name if company else "компания"
    for tag, d in (at.skills or {}).items():
        db.add(CandidateFact(
            user_id=at.candidate_user_id, kind="skill", key=tag, title=tag_title(tag),
            value={"score": d["score"], "correct": d["correct"], "total": d["total"], "origin": "assignment",
                   "assignment_title": a.title, "company": cname},
            evidence_level=EvidenceLevel.T1, source=FactSource.probe, source_ref=ref))
    db.add(CandidateFact(
        user_id=at.candidate_user_id, kind="probe", key=f"assignment:{a.id}", title=f"Задание работодателя: {a.title}",
        value={"score": at.score, "verdict": f"{at.correct} из {at.total} верно, автопроверка",
               "origin": "assignment", "company": cname, "source": at.source},
        evidence_level=EvidenceLevel.T1, source=FactSource.probe, source_ref=ref))
    db.flush()
    refresh_rating(db, at.candidate_user_id)


def _notify_employer(db: Session, at: AssignmentAttempt, a: Assignment) -> None:
    eu = db.get(User, a.created_by) if a.created_by else None
    p = db.get(CandidateProfile, at.candidate_user_id)
    ref = p.public_ref if p else "кандидат"
    if eu is None:
        return
    path = f"/employer/assignments/{a.id}"
    notify(eu.email, f"Кандидат {ref} выполнил задание «{a.title}»",
           [f"Результат автопроверки: {at.correct} из {at.total} верно.",
            "Результат записан как факт T1 и учтён в подборке."], is_demo=eu.is_demo, link_path=path)
    try:
        send_to_user(db, eu.id, f"Кандидат {ref} выполнил задание", f"«{a.title}»: {at.correct} из {at.total} верно",
                     path, f"assignment-done-{at.id}")
    except Exception:  # noqa: BLE001
        log.exception("push работодателю не отправлен")


# ------------------------------------------------------------------ интеграция с откликами на вакансии

def on_application(db: Session, v: Vacancy, app: VacancyApplication) -> AssignmentAttempt | None:
    """Отклик на вакансию с активным заданием — кандидату предлагается пройти задание."""
    a = active_for_vacancy(db, v.id)
    if a is None:
        return None
    cand = db.get(User, app.candidate_user_id)
    return offer(db, a, cand, "vacancy", application_id=app.id) if cand else None


def attempt_for_application(db: Session, app: VacancyApplication) -> dict | None:
    """Результат задания рядом с откликом (у работодателя и у кандидата)."""
    a = active_for_vacancy(db, app.vacancy_id)
    at = db.scalar(select(AssignmentAttempt).where(AssignmentAttempt.application_id == app.id)
                   .order_by(AssignmentAttempt.created_at.desc()))
    if at is None and a is not None:
        at = db.scalar(select(AssignmentAttempt).where(AssignmentAttempt.assignment_id == a.id,
                                                       AssignmentAttempt.candidate_user_id == app.candidate_user_id))
    if at is None:
        return None
    asg = a if a is not None and at.assignment_id == a.id else db.get(Assignment, at.assignment_id)
    return attempt_brief(at, asg)


def vacancy_brief(db: Session, vacancy_id) -> dict | None:
    a = active_for_vacancy(db, vacancy_id)
    return {"id": str(a.id), "title": a.title, "n_tasks": a.n_tasks, "time_limit_min": a.time_limit_min,
            "stack_titles": [tag_title(t) for t in a.stack_tags]} if a else None


# ------------------------------------------------------------------ представления

STATUS_TITLE = {"offered": "Предложено", "in_progress": "В работе", "scored": "Проверено", "declined": "Отклонено",
                "expired": "Время вышло"}


def attempt_brief(at: AssignmentAttempt, a: Assignment | None) -> dict:
    return {
        "attempt_id": str(at.id), "assignment_id": str(at.assignment_id), "title": a.title if a else None,
        "status": at.status, "status_title": STATUS_TITLE.get(at.status, at.status), "source": at.source,
        "score": at.score, "score_pct": round(at.score * 100) if at.score is not None else None,
        "correct": at.correct, "total": at.total, "time_spent_s": at.time_spent_s,
        "submitted_at": at.submitted_at, "offered_at": at.offered_at,
        "skills": [{"tag": t, "title": tag_title(t), **d} for t, d in sorted((at.skills or {}).items())],
    }


def assignment_out(db: Session, a: Assignment, *, for_candidate: bool = False) -> dict:
    company = db.get(Company, a.company_id)
    return {
        "id": str(a.id), "mode": a.mode, "title": a.title, "description": a.description, "status": a.status,
        "direction_id": a.direction_id, "grade_id": a.grade_id,
        "category_title": category_title(f"{a.direction_id}.{a.grade_id}"),
        "stack": [{"tag": t, "title": tag_title(t)} for t in a.stack_tags],
        "families": bank.families_public(a.families), "n_tasks": a.n_tasks, "time_limit_min": a.time_limit_min,
        "coverage": {**(a.coverage or {}), "missing_titles": [tag_title(t) for t in (a.coverage or {}).get("missing", [])]},
        "salary_from": a.salary_from, "salary_to": a.salary_to, "need_id": str(a.need_id) if a.need_id else None,
        "vacancy_id": str(a.vacancy_id) if a.vacancy_id else None, "is_demo": a.is_demo,
        "created_at": a.created_at,
        "company": {"id": str(company.id), "name": company.name} if company else None,
    }


def attempt_out(db: Session, at: AssignmentAttempt, a: Assignment) -> dict:
    """Для кандидата: задание, статус, варианты (без ключей), после проверки — верно/неверно по заданиям."""
    expire_overdue(db, at)
    out = {**attempt_brief(at, a), "assignment": assignment_out(db, a, for_candidate=True),
           "started_at": at.started_at, "deadline_at": at.deadline_at, "grace_s": GRACE_S,
           "tasks": auto.public_tasks(at.tasks, reveal_result=at.status == "scored") if at.status in ("in_progress", "scored") else None}
    if at.application_id:
        out["application_id"] = str(at.application_id)
    return out
