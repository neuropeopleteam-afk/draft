"""Демо-данные для показа жюри: 150 кандидатов (по 10 в каждой из 15 категорий), 10 работодателей, 15 потребностей.

Все записи помечены как демо: users.is_demo / companies.is_demo, почты на зарезервированном домене *.invalid
(письма туда не уходят и уйти не могут), паспорта ФСП — link_source=demo («демо-реестр»), результаты тестов —
движок «demo-seed». Пароли — случайные и нигде не сохраняются (войти под демо-учётками нельзя).

Запуск:  python -m app.modules.demo.seed            # добавить, если демо-данных ещё нет
         python -m app.modules.demo.seed --reset    # удалить все демо-данные и создать заново
         python -m app.modules.demo.seed --delete   # только удалить
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import random
import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_engine, utcnow
from app.core.enums import (
    ConsentKind,
    EvidenceLevel,
    FactSource,
    FspEventLevel,
    FspLinkSource,
    GradeChangeReason,
    NeedStatus,
    TestSessionStatus,
    UserRole,
    WorkFormat,
)
from app.core.legal import CONSENT_VERSION
from app.core.security import hash_password
from app.modules.assessment.models import GradeHistory, SurveyResponse, SurveyStackTag, TestSession
from app.modules.auth.models import Consent, User
from app.modules.catalog.seed_data import STACK
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.facts import refresh_rating, set_t0_facts
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company, EmployerProfile
from app.modules.profiles.refs import new_public_ref

DIRECTIONS = ["backend", "frontend", "data_ml", "qa", "security"]
GRADES = ["junior", "middle", "senior"]
CUT = {"junior": -1.0, "middle": 0.0, "senior": 1.0}
EXP = {"junior": (0.5, 1.9), "middle": (2.0, 4.9), "senior": (5.0, 11.0)}
CORE = {
    "backend": ["python", "postgresql", "fastapi", "django", "redis", "docker", "rest-api", "kafka", "go", "java",
                "asyncio", "sql", "git", "linux", "rabbitmq", "grpc"],
    "frontend": ["javascript", "typescript", "react", "html-css", "vue", "nextjs", "tailwind", "state-management",
                 "vite-webpack", "frontend-testing", "a11y", "git", "angular"],
    "data_ml": ["python", "pandas", "numpy", "scikit-learn", "statistics", "sql", "pytorch", "spark", "airflow",
                "clickhouse", "nlp", "cv", "mlops"],
    "qa": ["test-design", "manual-testing", "api-testing", "pytest", "sql", "selenium", "playwright", "ci-cd",
           "allure", "load-testing", "git", "docker"],
    "security": ["owasp", "network-security", "linux", "cryptography", "pentest", "burp-suite", "siem-soc", "ctf",
                 "reverse-engineering", "forensics", "python", "docker"],
}
ROLES = {"backend": ["developer", "tech_lead", "architect", "mentor"], "frontend": ["developer", "tech_lead", "mentor"],
         "data_ml": ["researcher", "analyst", "developer", "mentor"], "qa": ["tester", "team_lead", "mentor"],
         "security": ["analyst", "researcher", "developer", "mentor"]}
SOFT = ["communication", "teamwork", "responsibility", "learning", "problem_solving", "time_management"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Нижний Новгород", "Томск",
          "Самара", "Краснодар", "Иннополис", "Пермь", "Ростов-на-Дону"]
FIRST_M = ["Алексей", "Дмитрий", "Иван", "Максим", "Артём", "Никита", "Егор", "Кирилл", "Михаил", "Павел", "Роман",
           "Тимур", "Олег", "Глеб", "Лев"]
FIRST_F = ["Анна", "Мария", "Екатерина", "Дарья", "Ольга", "Полина", "Алиса", "София", "Виктория", "Ксения", "Ирина"]
LAST = ["Орлов", "Соколов", "Волков", "Лебедев", "Морозов", "Новиков", "Зайцев", "Павлов", "Семёнов", "Голубев",
        "Виноградов", "Богданов", "Воробьёв", "Фёдоров", "Михайлов", "Белов", "Тарасов", "Беляев", "Комаров", "Киселёв"]
EVENTS = {
    "algorithmic": ["Чемпионат России по программированию (алгоритмическое)", "Кубок России по спортивному программированию",
                    "Первенство ФО по алгоритмическому программированию"],
    "product": ["Чемпионат России по продуктовому программированию", "Всероссийский хакатон ФСП",
                "Кубок ФСП по продуктовому программированию"],
    "security": ["Чемпионат России по программированию систем ИБ (CTF)", "Кубок ФСП по информационной безопасности"],
    "robotics": ["Чемпионат России по программированию робототехники"],
    "uav": ["Чемпионат России по программированию БАС"],
}
DISC_BY_DIR = {"backend": ["product", "algorithmic"], "frontend": ["product"], "data_ml": ["algorithmic", "product", "uav"],
               "qa": ["product"], "security": ["security", "algorithmic"]}
COMPANIES = [
    ("Демо: ФинТех Север", "Финансовые технологии", "Санкт-Петербург"),
    ("Демо: ГородДанные", "Городские сервисы и аналитика", "Москва"),
    ("Демо: КиберЩит", "Информационная безопасность", "Москва"),
    ("Демо: Ритейл Платформа", "Электронная коммерция", "Казань"),
    ("Демо: МедИнфо", "Цифровая медицина", "Новосибирск"),
    ("Демо: ЛогистикПро", "Логистика", "Екатеринбург"),
    ("Демо: ЭдТех Лаб", "Образовательные технологии", "Томск"),
    ("Демо: ПромИИ", "Промышленный ИИ", "Пермь"),
    ("Демо: Студия Интерфейсов", "Веб-разработка на заказ", "Нижний Новгород"),
    ("Демо: Тест-Качество", "Аутсорсинг тестирования", "Самара"),
]
NEEDS = [
    (0, "Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
        "Будет плюсом Kafka. Удалённо, 220–300 тыс."),
    (0, "Нужен senior Java-разработчик для платёжного ядра: Java, PostgreSQL, Kafka, gRPC обязательно. Гибрид, Санкт-Петербург."),
    (1, "Data Scientist middle: Python, pandas, scikit-learn, статистика, SQL. Желательно Airflow и ClickHouse. 200–280 тыс. ₽"),
    (1, "Junior аналитик данных/ML: Python, pandas, SQL; будет плюсом опыт с numpy. Офис в Москве или гибрид."),
    (2, "Специалист по ИБ middle: OWASP, Burp Suite, пентест веб-приложений, сетевая безопасность. Желательно CTF."),
    (2, "Senior SOC-аналитик: SIEM/SOC, форензика, сетевая безопасность, Linux. Удалённо."),
    (3, "Frontend-разработчик middle: React, TypeScript, HTML/CSS обязательно; Next.js будет плюсом. 180–250 тыс."),
    (3, "Бэкенд junior: Python, Django, SQL, Git. Обучим остальному. Казань или удалённо."),
    (4, "QA-инженер middle: тест-дизайн, API-тестирование, pytest; желательно Playwright и Allure."),
    (5, "Senior Go-разработчик для маршрутизации: Go, PostgreSQL, Kafka, Docker. От 5 лет опыта."),
    (6, "Junior frontend: JavaScript, HTML/CSS, React. Желательно TypeScript. Томск, офис или гибрид."),
    (7, "ML-инженер senior: PyTorch, компьютерное зрение (CV), MLOps, Python. Желательно Spark."),
    (8, "Senior frontend: TypeScript, React, state management, доступность (a11y), тестирование фронтенда."),
    (9, "Junior QA: ручное тестирование, тест-дизайн, SQL, основы API-тестирования. Самара, офис."),
    (9, "Автоматизатор тестирования senior: Python, pytest, Selenium или Playwright, CI/CD, нагрузочное тестирование."),
]


def delete_demo(db: Session) -> int:
    n = db.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(True))) or 0
    company_ids = db.scalars(select(Company.id).where(Company.is_demo.is_(True))).all()
    if company_ids:
        db.execute(delete(EmployerNeed).where(EmployerNeed.company_id.in_(company_ids)))
    db.execute(delete(User).where(User.is_demo.is_(True)))
    db.execute(delete(Company).where(Company.is_demo.is_(True)))
    db.commit()
    return n


def _user(db: Session, email: str, role: UserRole, pwd_hash: str) -> User:
    u = User(email=email, password_hash=pwd_hash, role=role, is_email_verified=True, email_verified_at=utcnow(),
             is_demo=True)
    db.add(u)
    db.flush()
    for kind in (ConsentKind.processing, ConsentKind.publication):
        db.add(Consent(user_id=u.id, kind=kind, document_version=CONSENT_VERSION))
    return u


def _candidate(db: Session, rnd: random.Random, idx: int, direction: str, grade: str, pwd_hash: str, with_fsp: bool,
               status: str = "confirmed"):
    """Демо-кандидат. status — статус грейда (единая модель): confirmed — категория подтверждена тестом;
    provisional — «Junior (предварительно)» (только grade == junior); unconfirmed_notest — опрос пройден, теста нет;
    unconfirmed_failed — тест на заявленный грейд его не подтвердил (категории нет)."""
    u = _user(db, f"demo-candidate-{idx:03d}@demo.invalid", UserRole.candidate, pwd_hash)
    female = rnd.random() < 0.35
    last = rnd.choice(LAST) + ("а" if female else "")
    name = f"{rnd.choice(FIRST_F if female else FIRST_M)} {last}"
    exp = round(rnd.uniform(*EXP[grade]), 1)
    core = CORE[direction]
    k = {"junior": 4, "middle": 6, "senior": 8}[grade]
    stack = list(dict.fromkeys(core[:3] + rnd.sample(core[3:], min(len(core) - 3, k - 2))))[:k]
    roles = ["developer" if direction != "qa" else "tester"]
    if grade == "senior":
        roles += rnd.sample([r for r in ROLES[direction] if r not in roles], 1)
    if direction in ("data_ml", "security") and rnd.random() < 0.4:
        roles.append(rnd.choice(["researcher", "analyst"]))
    roles = list(dict.fromkeys(roles))
    city = rnd.choice(CITIES)
    wf = rnd.choice([WorkFormat.remote, WorkFormat.remote, WorkFormat.hybrid, WorkFormat.office, WorkFormat.any])
    base = {"junior": 70_000, "middle": 160_000, "senior": 280_000}[grade]
    p = CandidateProfile(
        user_id=u.id, full_name=name, phone=f"+7 900 {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}",
        telegram=f"@demo_{idx:03d}", city=city, work_format=wf, relocation=rnd.random() < 0.3, experience_years=exp,
        salary_min_hidden=int(round(base * rnd.uniform(0.9, 1.3), -4)), privacy={}, visible_to_employers=True,
        public_ref=new_public_ref(db), onboarding_completed_at=utcnow(), roles=roles,
        headline=f"{direction} · {grade} (демо)" if status == "confirmed" else f"{direction} (демо)",
    )
    db.add(p)
    db.flush()
    created = utcnow() - timedelta(days=rnd.randint(5, 80))
    survey = SurveyResponse(user_id=u.id, direction_id=direction, claimed_grade_id=grade, experience_years=exp,
                            answers={"stack": {t: rnd.randint(2, 3) for t in stack}, "roles": roles, "demo": True},
                            created_at=created)
    db.add(survey)
    db.flush()
    for t in stack:
        db.add(SurveyStackTag(survey_id=survey.id, stack_tag_id=t, self_level=survey.answers["stack"][t]))
    set_t0_facts(db, u.id, FactSource.self_report, stack=stack, roles=roles,
                 soft_skills=rnd.sample(SOFT, rnd.randint(1, 3)), experience_years=exp)
    if status == "unconfirmed_notest":  # опрос пройден, теста нет: «грейд не подтверждён (заявлен …)»
        db.flush()
        refresh_rating(db, u.id)
        return
    if status == "confirmed":
        # Результат теста: θ выше порога заявленного грейда (иначе категория не была бы присвоена)
        theta = round(CUT[grade] + rnd.uniform(0.15, 1.3), 2)
        se = round(rnd.uniform(0.32, 0.5), 2)
    elif status == "provisional":
        # у порога Junior: P(θ ≥ −1) в (0,10; 0,80) ⇔ θ̂ − порог в SE·(−1,28; 0,84)
        se = round(rnd.uniform(0.36, 0.48), 2)
        theta = round(CUT[grade] + se * rnd.uniform(-1.1, 0.6), 2)
    else:  # unconfirmed_failed: уровень ниже порога заявленного грейда доказан (P < 0,10)
        se = round(rnd.uniform(0.3, 0.4), 2)
        theta = round(CUT[grade] - se * rnd.uniform(1.5, 2.6), 2)
    answered = 18
    correct = min(answered, max(5, int(round(answered * (0.55 + 0.12 * (theta - CUT[grade])) + rnd.randint(-1, 1)))))
    confirmed = status == "confirmed"
    ts = TestSession(user_id=u.id, survey_id=survey.id, direction_id=direction, claimed_grade_id=grade,
                     status=TestSessionStatus.finished, form_seed=rnd.randint(1, 2**30), is_sandbox=False,
                     started_at=created, finished_at=created + timedelta(minutes=rnd.randint(18, 40)),
                     score=correct / answered, theta=theta, theta_se=se, result_grade_id=grade if confirmed else None,
                     result={"engine": "demo-seed", "demo": True, "engine_result": {"confirmed": confirmed,
                                                                                    "provisional": status == "provisional"}},
                     created_at=created)
    db.add(ts)
    db.flush()
    if status == "unconfirmed_failed":
        db.flush()
        refresh_rating(db, u.id)
        return
    from app.modules.assessment import provisional as prov

    p_claimed = round(1 - _norm_cdf((CUT[grade] - theta) / se), 3)
    if confirmed:
        lock = created + timedelta(days=90)
        db.add(GradeHistory(user_id=u.id, direction_id=direction, from_grade_id=None, to_grade_id=grade,
                            reason=GradeChangeReason.initial, test_session_id=ts.id, locked_until=lock, created_at=created))
        p.grade_locked_until = lock
        extra = {}
    else:  # предварительно: 90 дней не начинаются, вероятность и причина — как у движка (provisional.fact_extra)
        db.add(GradeHistory(user_id=u.id, direction_id=direction, from_grade_id=None, to_grade_id=grade,
                            reason=GradeChangeReason.provisional, test_session_id=ts.id, locked_until=None,
                            created_at=created))
        p.grade_provisional = True
        extra = {"status": "provisional",
                 "provisional": {"reason": "precision" if theta >= CUT[grade] else "uncertain", "p": p_claimed,
                                 "cut": CUT[grade], "level": prov.LEVEL, "since": created.isoformat(), "attempts": 0,
                                 "attempts_max": prov.CONFIRM_ATTEMPTS, "session_id": str(ts.id), "last_confirm": None}}
    p.current_direction_id, p.current_grade_id = direction, grade
    p.current_category_id = f"{direction}.{grade}"
    db.add(CandidateFact(user_id=u.id, kind="test_result", key=f"{direction}.{grade}", title=f"Тест {direction} · {grade}",
                         value={"theta": theta, "se": se, "grade": grade, "confirmed": confirmed, "correct": correct,
                                "answered": answered, "engine": "demo-seed", "session_id": str(ts.id),
                                "p_claimed": p_claimed, **extra},
                         evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
                         created_at=created))
    # Навыки, проверенные заданиями: часть заявленного стека, у сильных — больше
    tested = [t for t in stack if rnd.random() < 0.75]
    for t in tested:
        total = rnd.randint(2, 4)
        corr = max(0, min(total, int(round(total * min(1.0, 0.45 + 0.25 * (theta - CUT[grade]) + rnd.uniform(-0.2, 0.25))))))
        db.add(CandidateFact(user_id=u.id, kind="skill", key=t, title=STACK[t][0],
                             value={"score": round(corr / total, 2), "correct": corr, "total": total},
                             evidence_level=EvidenceLevel.T1, source=FactSource.test,
                             source_ref=f"test_session:{ts.id}", created_at=created))
    if with_fsp:
        pp = FspPassport(user_id=u.id, link_source=FspLinkSource.demo, synced_at=utcnow(),
                         sport_rank=rnd.choice([None, "III разряд", "II разряд", "I разряд", "КМС"]),
                         raw={"demo": True, "note": "демо-реестр хакатона"})
        db.add(pp)
        db.flush()
        for _ in range(rnd.randint(1, 3)):
            disc = rnd.choice(DISC_BY_DIR[direction])
            level = rnd.choices([FspEventLevel.regional, FspEventLevel.interregional, FspEventLevel.national,
                                 FspEventLevel.international], weights=[4, 3, 3, 1])[0]
            place = rnd.choices([1, 2, 3, rnd.randint(4, 10), rnd.randint(11, 60)], weights=[1, 1.5, 1.5, 3, 3])[0]
            title = "победитель" if place == 1 else "призёр" if place <= 3 else "финалист" if place <= 10 else "участник"
            db.add(FspAchievement(passport_id=pp.id, discipline=disc, event_name=rnd.choice(EVENTS[disc]),
                                  event_level=level, event_date=date(rnd.choice([2023, 2024, 2025, 2026]),
                                                                     rnd.randint(1, 12), rnd.randint(1, 28)),
                                  place=place, result_title=title, team_name=f"Команда {rnd.randint(1, 400)} (демо)",
                                  verified=True, source_ref="demo-registry"))
    db.flush()
    refresh_rating(db, u.id)


PROVISIONAL_DEMO = (("backend", True), ("frontend", False), ("data_ml", False), ("qa", True), ("security", False))
UNCONFIRMED_DEMO = (("backend", "middle", "unconfirmed_notest"), ("backend", "junior", "unconfirmed_failed"),
                    ("frontend", "senior", "unconfirmed_failed"), ("data_ml", "junior", "unconfirmed_notest"),
                    ("qa", "middle", "unconfirmed_failed"), ("security", "junior", "unconfirmed_notest"))


def _norm_cdf(x: float) -> float:
    import math
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _extra_candidates(db: Session, idx: int, rng_seed: int, pwd_hash: str) -> int:
    """Демо-кандидаты со статусами «предварительно» и «не подтверждён» (после 150 основных, их не сдвигают)."""
    rnd_p = random.Random(rng_seed + 1)
    for d, with_fsp in PROVISIONAL_DEMO:
        idx += 1
        _candidate(db, rnd_p, idx, d, "junior", pwd_hash, with_fsp, status="provisional")
    rnd_u = random.Random(rng_seed + 2)
    for d, g, st in UNCONFIRMED_DEMO:
        idx += 1
        _candidate(db, rnd_u, idx, d, g, pwd_hash, False, status=st)
    db.commit()
    return idx


def seed(db: Session, rng_seed: int = 20261006) -> dict:
    rnd = random.Random(rng_seed)
    pwd_hash = hash_password(secrets.token_urlsafe(24))  # случайный, нигде не сохраняется
    idx = 0
    for d in DIRECTIONS:
        for g in GRADES:
            fsp_flags = [True] * 4 + [False] * 6
            rnd.shuffle(fsp_flags)
            for i in range(10):
                idx += 1
                _candidate(db, rnd, idx, d, g, pwd_hash, fsp_flags[i])
            db.commit()
    # Статусы грейда (единая модель) — отдельными генераторами, чтобы не сдвинуть 150 основных кандидатов:
    # 5 «Junior (предварительно)» и кандидаты без подтверждённого грейда (теста нет / тест не подтвердил)
    idx = _extra_candidates(db, idx, rng_seed, pwd_hash)
    employers = []
    for i, (name, industry, city) in enumerate(COMPANIES, start=1):
        u = _user(db, f"demo-employer-{i:02d}@demo.invalid", UserRole.employer, pwd_hash)
        c = Company(name=name, industry=industry, city=city, description=f"{industry}. Демо-компания для показа.",
                    contact_email=f"hr-{i:02d}@demo.invalid", created_by=u.id, is_demo=True)
        db.add(c)
        db.flush()
        db.add(EmployerProfile(user_id=u.id, company_id=c.id, full_name=f"HR {name}", position="Рекрутер (демо)"))
        employers.append((u, c))
    db.commit()
    for ci, text in NEEDS:
        u, c = employers[ci]
        req = parse_need(text, use_llm=False)
        n = EmployerNeed(company_id=c.id, created_by=u.id, title=text.split(":")[0][:200], raw_text=text,
                         requirements=req, direction_id=req.get("direction"), grade_id=req.get("grade"),
                         salary_from=req.get("salary_from"), salary_to=req.get("salary_to"), status=NeedStatus.active)
        db.add(n)
        db.flush()
        sel = ranking.build_selection(db, req, {})
        db.add(SelectionVersion(need_id=n.id, version=1, parent_version=None, filters={}, requirements=req,
                                results=sel["results"], algorithm_version=sel["algorithm"], created_by=u.id))
    db.commit()
    fsp = db.scalar(select(func.count()).select_from(FspPassport).join(User, User.id == FspPassport.user_id)
                    .where(User.is_demo.is_(True)))
    return {"candidates": idx, "with_fsp": fsp, "employers": len(employers), "needs": len(NEEDS)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Демо-данные платформы")
    ap.add_argument("--reset", action="store_true", help="удалить демо-данные и создать заново")
    ap.add_argument("--delete", action="store_true", help="только удалить демо-данные")
    a = ap.parse_args()
    get_engine()
    with SessionLocal() as db:
        exists = db.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(True))) or 0
        if a.reset or a.delete:
            print(f"Удалено демо-пользователей: {delete_demo(db)}")
            exists = 0
        if a.delete:
            return
        if exists:
            print(f"Демо-данные уже есть ({exists} пользователей). Для пересоздания: --reset")
            return
        print(seed(db))


if __name__ == "__main__":
    main()
