"""Демо-данные песочницы жюри: четыре задания работодателя «Северный платёж» (И7, К5).

* «Задание по требованиям» из первой потребности (Backend · Middle: Python, FastAPI, PostgreSQL, Redis) — отправлено
  Марии как зонд с автопроверкой и просьбой описать подход: выполнено (4 из 5), работодатель уже оценил подход по рубрике
  (видно «до» — автопроверка и «после» — итог); Илья выполнил то же задание, его подход ждёт оценки (напоминание
  работодателю уже отправлено);
* задание к вакансии «Backend-разработчик (платежи)» (вакансия создаётся здесь же): Илья откликнулся — задание
  предложено и ждёт решения, работодатель видит это рядом с откликом;
* открытое задание (Python, SQL) — Марии в ленте «Задания для вас» (предложение три дня назад, напоминание уже
  отправлено), с причиной «почему вам»; открытое задание для Junior (Python, HTTP, Git) — Артёму, причина — слабые навыки.
  Кнопка «Смоделировать неделю» у Марии проводит обычный цикл ленты: напоминание, истечение, новое предложение.
Ключи вариантов — только на сервере; ответы в демо выставляются по ключу (score_method=demo). Старые даты навыков Марии
(тест пройден раньше, чем задание) заданы только в песочнице, чтобы «свежесть профиля» была видна сразу.
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
from app.modules.assignments import rubric as rub
from app.modules.assignments import service as svc
from app.modules.assignments import why as why_mod
from app.modules.assignments.models import Assignment, AssignmentAttempt
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.facts import load_bundles, skill_confirmed
from app.modules.profiles.models import CandidateProfile, Company

log = logging.getLogger(__name__)

VACANCY_TITLE = "Backend-разработчик (платежи)"


def seed_jury_assignments(db: Session, key: str, employer: User, company: Company, need: EmployerNeed | None,
                          maria: CandidateProfile | None, ilya: CandidateProfile | None,
                          artem: CandidateProfile | None = None) -> list[str]:
    rnd = random.Random(77)
    now = utcnow()
    out: list[str] = []
    direction, grade = "backend", "middle"
    stack = ["python", "fastapi", "postgresql", "redis"]
    if need is not None:
        req = need.requirements or {}
        stack = [x["tag"] for x in (req.get("stack_required") or []) + (req.get("stack_desired") or [])] or stack
        direction, grade = req.get("direction") or direction, req.get("grade") or grade

    if maria is not None:
        _age_test_skills(db, maria.user_id, now - timedelta(days=130))
    # 1. зонд с автопроверкой по требованиям потребности и просьбой о подходе — Марии, выполнен 4 из 5, подход оценён
    a1 = _assignment(db, employer, company, key, mode="probe", title="Задание по требованиям: Backend · Middle, платежи",
                     description="Пять заданий банка по стеку потребности: Python, FastAPI, PostgreSQL, Redis. "
                                 "Сложность — уровня Middle, проверка автоматическая.",
                     direction=direction, grade=grade, stack=stack, n=5, salary=(240_000, 290_000), need_id=need.id if need else None,
                     created_days=-4, rnd=rnd, with_approach=True)
    if maria is not None and maria.visible_to_employers:
        at = _attempt(db, a1, maria.user_id, "probe", offered=now - timedelta(days=3))
        _play(db, at, a1, correct_n=4, spent_s=11 * 60, submitted=now - timedelta(days=2, hours=5), rnd=rnd,
              approach=APPROACH_MARIA)
        svc.review(db, at, a1, {"approach": 15, "risks": 10}, "Шаги по стеку, риск гонок и проверка повторной доставки названы. "
                                                              "Не хватило оценки нагрузки.")
        at.reviewed_at = now - timedelta(days=2)
    if ilya is not None:
        at = _attempt(db, a1, ilya.user_id, "probe", offered=now - timedelta(days=4, hours=2))
        _play(db, at, a1, correct_n=3, spent_s=14 * 60, submitted=now - timedelta(days=4), rnd=rnd, approach=APPROACH_ILYA)
        at.review_remind_at, at.review_remind_count = now - timedelta(days=1), 1  # работодателю напоминание уже отправлено
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

    # 3. открытое задание «на общее обозрение»: Марии — в ленту «Задания для вас» (предложение, ещё не начато).
    # Стек — из навыков Марии, подтверждённых тестом (доля верных ≥ 50 %) и состаренных выше на 130 дней: тогда причина
    # предложения детерминированно «давно не подтверждался» (stale_skill), а не «подтверждён слабо» — какой навык в её
    # посеянном тесте окажется слабым, зависит от случайной формы (замер И26: 5 из 16 песочниц).
    open_stack = _stale_confirmed_stack(db, maria, prefer=("python", "sql", "postgresql"), fallback=["python", "sql", "postgresql"])
    a3 = _assignment(db, employer, company, key, mode="open", title="Открытое задание: SQL и Python для платёжного ядра",
                     description=f"Три задания банка: {', '.join(svc.tag_title(t) for t in open_stack)}. Открыто для всех "
                                 "кандидатов Backend · Middle с подходящим стеком; результат — факт T1 в профиле.",
                     direction="backend", grade="middle", stack=open_stack, n=3,
                     salary=(230_000, 280_000), created_days=-4, rnd=rnd)
    a4 = _assignment(db, employer, company, key, mode="open", title="Открытое задание: основы Python, HTTP и Git",
                     description="Три задания банка уровня Junior. Открыто для кандидатов Backend с подходящим стеком; "
                                 "результат — факт T1 в профиле.",
                     direction="backend", grade="junior", stack=["python", "http", "git"], n=3,
                     salary=(90_000, 120_000), created_days=-3, rnd=rnd)
    if maria is not None:
        at = _attempt(db, a3, maria.user_id, "feed", offered=now - timedelta(days=3))
        at.remind_at, at.remind_count = now - timedelta(days=1), 1  # напоминание уже отправлено — видно в ленте
    if artem is not None:
        _attempt(db, a4, artem.user_id, "feed", offered=now - timedelta(days=1))
    out += [a3.title, a4.title]
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
                need_id=None, vacancy_id=None, created_days: float = 0, with_approach: bool = False) -> Assignment:
    fams = bank.pick(direction, grade, stack, n, seed=rnd.randrange(1 << 30))
    a = Assignment(company_id=company.id, created_by=employer.id, need_id=need_id, vacancy_id=vacancy_id, mode=mode,
                   title=title, description=description, direction_id=direction, grade_id=grade, stack_tags=stack,
                   families=fams, coverage=bank.coverage_for(direction, grade, stack), n_tasks=len(fams),
                   time_limit_min=svc.suggested_time(fams), salary_from=salary[0], salary_to=salary[1],
                   status="active", is_demo=True, jury_scope=key, rubric=rub.build(with_approach),
                   approach_prompt=rub.default_prompt(title, [svc.tag_title(t) for t in stack]) if with_approach else None)
    a.created_at = utcnow() + timedelta(days=created_days)
    db.add(a)
    db.flush()
    return a


def _attempt(db: Session, a: Assignment, user_id, source: str, *, offered, application_id=None) -> AssignmentAttempt:
    at = AssignmentAttempt(assignment_id=a.id, candidate_user_id=user_id, source=source, application_id=application_id,
                           status="offered", offered_at=offered)
    at.created_at = offered
    cand = db.get(User, user_id)
    try:  # причина — по состоянию профиля на момент предложения, как и в обычном потоке
        at.why = why_mod.build(db, a, cand, source, frequency_days=7)
    except Exception:  # noqa: BLE001
        log.exception("demo: причина предложения не определена")
    db.add(at)
    db.flush()
    return at


APPROACH_MARIA = ("Начну с разбора платёжного потока: какие операции должны быть идемпотентными и где возможна повторная "
                  "доставка вебхука. Опишу контракт API и схему таблиц в PostgreSQL, затем сделаю обработчик на FastAPI "
                  "с ключом идемпотентности в Redis. Главный риск — гонки при параллельных запросах: закрою его уникальным "
                  "индексом и транзакцией. Результат проверю тестами на повторную доставку и прогоном на тестовом стенде.")
APPROACH_ILYA = ("Сначала уточню требования и нагрузку, потом разобью работу на этапы: модель данных, обработчик вебхуков, "
                 "очередь на Redis для повторов. Буду смотреть на логи и метрики после выкладки, чтобы понять, что "
                 "всё работает как задумано.")


def _stale_confirmed_stack(db: Session, maria: CandidateProfile | None, *, prefer: tuple[str, ...], fallback: list[str],
                           n: int = 3) -> list[str]:
    """Теги навыков Марии, подтверждённых тестом Backend (`skill_confirmed`), сначала предпочтительные, затем остальные по
    алфавиту; если подтверждённых меньше двух — стек по умолчанию (причина тогда может быть и weak_skill — честно)."""
    if maria is None:
        return list(fallback)
    b = load_bundles(db, [maria.user_id], direction="backend").get(maria.user_id)
    covered = set(bank.coverage_for("backend", "middle", sorted(b.skills_t1))["covered"]) if b else set()
    ok = {t for t, f in (b.skills_t1 if b else {}).items() if skill_confirmed(f) and t in covered}
    picked = [t for t in prefer if t in ok] + sorted(ok - set(prefer))
    return picked[:n] if len(picked) >= 2 else list(fallback)


def _age_test_skills(db: Session, user_id, when) -> None:
    """Песочница: навыки Марии из теста Backend были подтверждены раньше (130 дней назад) — «свежесть профиля» видна сразу."""
    for f in db.scalars(select(svc.CandidateFact).where(svc.CandidateFact.user_id == user_id,
                                                        svc.CandidateFact.kind == "skill")).all():
        if (f.source_ref or "").startswith("test_session:") and (f.value or {}).get("direction") == "backend":
            f.created_at = when
    db.flush()


def _play(db: Session, at: AssignmentAttempt, a: Assignment, *, correct_n: int, spent_s: int, submitted,
          rnd: random.Random, approach: str | None = None) -> None:
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
    at.approach_text = approach if a.approach_prompt else None
    svc.init_rubric(at, a)
    db.flush()
    svc.write_facts(db, at, a)
    for f in db.scalars(select(svc.CandidateFact).where(svc.CandidateFact.source_ref == f"{svc.SOURCE_REF}{at.id}")).all():
        f.created_at = submitted
    db.flush()
