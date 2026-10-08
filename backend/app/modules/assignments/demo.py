"""Демо-данные песочницы жюри: три задания работодателя «Северный платёж» (И7).

* «Задание по требованиям» из первой потребности (Backend · Middle: Python, FastAPI, PostgreSQL, Redis) — отправлено
  Марии как зонд с автопроверкой и уже выполнено (4 из 5): факты T1 по навыкам видны в подборке и в «почему»;
* задание к вакансии «Backend-разработчик (платежи)» (вакансия создаётся здесь же): Илья откликнулся — задание
  предложено и ждёт решения, работодатель видит это рядом с откликом;
* открытое задание «на общее обозрение» (Python, SQL) — попадает Марии в ленту «Задания для вас» как предложение.
Ключи вариантов — только на сервере; ответы Марии в демо выставляются по ключу (score_method=demo).
"""
from __future__ import annotations

from datetime import timedelta
import logging
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.cup import tasks as auto
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.assignments import bank
from app.modules.assignments import service as svc
from app.modules.assignments.models import Assignment, AssignmentAttempt
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import CandidateProfile, Company

log = logging.getLogger(__name__)

VACANCY_TITLE = "Backend-разработчик (платежи)"


def seed_jury_assignments(db: Session, key: str, employer: User, company: Company, need: EmployerNeed | None,
                          maria: CandidateProfile | None, ilya: CandidateProfile | None) -> list[str]:
    rnd = random.Random(77)
    now = utcnow()
    out: list[str] = []
    direction, grade = "backend", "middle"
    stack = ["python", "fastapi", "postgresql", "redis"]
    if need is not None:
        req = need.requirements or {}
        stack = [x["tag"] for x in (req.get("stack_required") or []) + (req.get("stack_desired") or [])] or stack
        direction, grade = req.get("direction") or direction, req.get("grade") or grade

    # 1. зонд с автопроверкой по требованиям потребности — Марии, выполнен 4 из 5
    a1 = _assignment(db, employer, company, key, mode="probe", title="Задание по требованиям: Backend · Middle, платежи",
                     description="Пять заданий банка по стеку потребности: Python, FastAPI, PostgreSQL, Redis. "
                                 "Сложность — уровня Middle, проверка автоматическая.",
                     direction=direction, grade=grade, stack=stack, n=5, salary=(240_000, 290_000), need_id=need.id if need else None,
                     created_days=-3, rnd=rnd)
    if maria is not None and maria.visible_to_employers:
        at = _attempt(db, a1, maria.user_id, "probe", offered=now - timedelta(days=3))
        _play(db, at, a1, correct_n=4, spent_s=11 * 60, submitted=now - timedelta(days=2, hours=5), rnd=rnd)
    out.append(a1.title)

    # 2. вакансия с прикреплённым заданием: Илья откликнулся, задание предложено (ждёт решения)
    v = db.scalar(select(Vacancy).where(Vacancy.company_id == company.id, Vacancy.title == VACANCY_TITLE))
    if v is None:
        v = Vacancy(company_id=company.id, created_by=employer.id, title=VACANCY_TITLE, category_id="backend.middle",
                    description="Команда платежей: FastAPI, PostgreSQL, Redis. Идемпотентность, транзакции, вебхуки "
                                "провайдеров. Удалённо, гибкий график. Откликнувшиеся проходят короткое задание "
                                "с автопроверкой — результат виден рядом с откликом.",
                    stack=["python", "fastapi", "postgresql", "redis", "docker"], salary_from=240_000, salary_to=290_000,
                    work_format="remote", city="Санкт-Петербург", status="published",
                    published_at=now - timedelta(days=5), is_demo=True)
        db.add(v)
        db.flush()
    a2 = _assignment(db, employer, company, key, mode="vacancy", title=f"Задание к вакансии: {VACANCY_TITLE}",
                     description="Четыре задания банка по стеку вакансии; откликнувшийся проходит их после отклика.",
                     direction="backend", grade="middle", stack=list(v.stack), n=4, salary=(v.salary_from, v.salary_to),
                     vacancy_id=v.id, created_days=-5, rnd=rnd)
    if ilya is not None:
        app = db.scalar(select(VacancyApplication).where(VacancyApplication.vacancy_id == v.id,
                                                         VacancyApplication.candidate_user_id == ilya.user_id))
        if app is None:
            app = VacancyApplication(vacancy_id=v.id, candidate_user_id=ilya.user_id, status="viewed",
                                     cover_letter="Делал платёжные интеграции и очереди на Redis; интересна команда платежей.",
                                     viewed_at=now - timedelta(days=1),
                                     events=[{"status": "sent", "at": (now - timedelta(days=1, hours=3)).isoformat(), "by": "candidate"},
                                             {"status": "viewed", "at": (now - timedelta(days=1)).isoformat(), "by": "employer"}])
            app.created_at = now - timedelta(days=1, hours=3)
            db.add(app)
            db.flush()
        _attempt(db, a2, ilya.user_id, "vacancy", offered=now - timedelta(days=1, hours=3), application_id=app.id)
    out.append(a2.title)

    # 3. открытое задание «на общее обозрение»: Марии — в ленту «Задания для вас» (предложение, ещё не начато)
    a3 = _assignment(db, employer, company, key, mode="open", title="Открытое задание: SQL и Python для платёжного ядра",
                     description="Три задания банка на SQL и Python. Открыто для всех кандидатов Backend · Middle "
                                 "с подходящим стеком; результат — факт T1 в профиле.",
                     direction="backend", grade="middle", stack=["python", "sql", "postgresql"], n=3,
                     salary=(230_000, 280_000), created_days=-2, rnd=rnd)
    if maria is not None:
        _attempt(db, a3, maria.user_id, "feed", offered=now - timedelta(hours=6))
    out.append(a3.title)
    db.commit()
    _rebuild_selection(db, need)
    return out


def _rebuild_selection(db: Session, need: EmployerNeed | None) -> None:
    """Подборка v1 потребности построена до задания — пересчитать, чтобы факт T1 Марии был виден сразу."""
    from app.modules.matching import ranking
    from app.modules.matching.models import SelectionVersion

    if need is None:
        return
    for sv in db.scalars(select(SelectionVersion).where(SelectionVersion.need_id == need.id)).all():
        sel = ranking.build_selection(db, sv.requirements or need.requirements or {}, sv.filters or {})
        sv.results = sel["results"]
    db.commit()


def _assignment(db: Session, employer: User, company: Company, key: str, *, mode: str, title: str, description: str,
                direction: str, grade: str, stack: list[str], n: int, salary: tuple[int, int], rnd: random.Random,
                need_id=None, vacancy_id=None, created_days: float = 0) -> Assignment:
    fams = bank.pick(direction, grade, stack, n, seed=rnd.randrange(1 << 30))
    a = Assignment(company_id=company.id, created_by=employer.id, need_id=need_id, vacancy_id=vacancy_id, mode=mode,
                   title=title, description=description, direction_id=direction, grade_id=grade, stack_tags=stack,
                   families=fams, coverage=bank.coverage_for(direction, grade, stack), n_tasks=len(fams),
                   time_limit_min=svc.suggested_time(fams), salary_from=salary[0], salary_to=salary[1],
                   status="active", is_demo=True, jury_scope=key)
    a.created_at = utcnow() + timedelta(days=created_days)
    db.add(a)
    db.flush()
    return a


def _attempt(db: Session, a: Assignment, user_id, source: str, *, offered, application_id=None) -> AssignmentAttempt:
    at = AssignmentAttempt(assignment_id=a.id, candidate_user_id=user_id, source=source, application_id=application_id,
                           status="offered", offered_at=offered)
    at.created_at = offered
    db.add(at)
    db.flush()
    return at


def _play(db: Session, at: AssignmentAttempt, a: Assignment, *, correct_n: int, spent_s: int, submitted,
          rnd: random.Random) -> None:
    items = auto.issue([f["family_id"] for f in a.families])
    for i, it in enumerate(items):
        key = it["key"]["value"]
        if i < correct_n:
            ans = key
        elif it["kind"] == "option":
            ans = next(o["id"] for o in it["public"]["options"] if o["id"] != key)
        elif it["kind"] == "line":
            ans = int(key) % max(2, it["public"]["code_lines"]) + 1
        else:
            ans = "None"
        it["answer"] = ans
    at.tasks = items
    at.started_at = submitted - timedelta(seconds=spent_s)
    at.deadline_at = at.started_at + timedelta(minutes=a.time_limit_min)
    at.submitted_at = submitted
    at.time_spent_s = spent_s
    at.status = "in_progress"
    at.score = auto.score(items, {it["token"]: it["answer"] for it in items})
    at.tasks = list(items)
    at.correct = sum(1 for it in items if it.get("correct"))
    at.total = len(items)
    at.skills = svc._skills(items)  # noqa: SLF001 — тот же подсчёт, что при реальной проверке
    at.status = "scored"
    at.score_method = "demo"
    db.flush()
    svc.write_facts(db, at, a)
    for f in db.scalars(select(svc.CandidateFact).where(svc.CandidateFact.source_ref == f"{svc.SOURCE_REF}{at.id}")).all():
        f.created_at = submitted
    db.flush()
