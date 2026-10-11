"""Демо-данные: 500 кандидатов, 10 работодателей, 15 потребностей (с флагом GRADES_EXT_ENABLED — плюс модельные
Lead/Principal с номера 701 в направлениях, где эти уровни проверяет банк).

Исходные 150 кандидатов и их идентификаторы сохраняются; extend_candidates добавляет только 151..500.
Обе аудитории: школьники/студенты ФСП и опытные специалисты. Все результаты — синтетическое демо,
не доказательство прохождения реального банка по Kotlin, C#, PHP или Kubernetes.

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
from app.modules.catalog.seed_data import GRADE_CUTS, direction_title, tag_title
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.facts import refresh_rating, set_t0_facts
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company, EmployerProfile
from app.modules.profiles.refs import new_public_ref

DIRECTIONS = ["backend", "frontend", "data_ml", "qa", "security"]
GRADES = ["junior", "middle", "senior"]  # 150 исходных демо-кандидатов (по 10 на категорию); их состав не меняется
CUT = GRADE_CUTS
EXP = {"intern": (0.0, 0.4), "junior": (0.5, 1.9), "middle": (2.0, 4.9), "senior": (5.0, 11.0),
       "lead": (7.5, 14.0), "principal": (10.0, 18.0)}  # Lead/Principal — только модельные кандидаты под флагом
# Lead/Principal (флаг GRADES_EXT_ENABLED): модельные демо-кандидаты с номера 701 (501–580 — модельные кандидаты новых
# направлений каталога) — только в направлениях, где эти уровни проверяет банк (catalog.levels); без флага их нет,
# состав 500 прежних не меняется
EXT_FIRST = 701
EXT_PER_DIRECTION = {"lead": 3, "principal": 2}
# Стажёры — новые демо-кандидаты поверх исходных 150 (отдельный поток случайности, номера с 151)
INTERN_PER_DIRECTION = 2
INTERN_NEEDS = [
    (6, "Стажёр frontend без опыта: HTML/CSS, JavaScript, основы Git; обучим React. Томск, офис, стипендия 40–60 тыс."),
    (3, "Стажировка backend для студентов: Python, SQL, Git. Без опыта, наставник в команде. Казань или удалённо."),
]
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
               status: str = "confirmed", *, core_override: list[str] | None = None, audience: str | None = None):
    """Демо-кандидат. status — статус грейда (единая модель): confirmed — категория подтверждена тестом;
    provisional — «Junior (предварительно)» (только grade == junior); unconfirmed_notest — опрос пройден, теста нет;
    unconfirmed_failed — тест на заявленный грейд его не подтвердил (категории нет).
    core_override / audience — расширение демо до 500 (И8): свой стек и аудитория (школьник / студент / специалист)."""
    u = _user(db, f"demo-candidate-{idx:03d}@demo.invalid", UserRole.candidate, pwd_hash)
    female = rnd.random() < 0.35
    last = rnd.choice(LAST) + ("а" if female else "")
    name = f"{rnd.choice(FIRST_F if female else FIRST_M)} {last}"
    exp = round(rnd.uniform(*EXP[grade]), 1)
    core = core_override or CORE[direction]
    k = {"intern": 3, "junior": 4, "middle": 6, "senior": 8, "lead": 9, "principal": 10}[grade]
    stack = list(dict.fromkeys(core[:3] + rnd.sample(core[3:], min(len(core) - 3, k - 2))))[:k]
    roles = [{"qa": "tester", "analyst": "analyst", "devops": "devops"}.get(direction, "developer")]
    if grade in ("senior", "lead", "principal"):
        roles += rnd.sample([r for r in ROLES[direction] if r not in roles], 1)
    if grade in ("lead", "principal"):  # модельный Lead/Principal: роль лидера команды или архитектора
        roles += [r for r in ("tech_lead", "team_lead", "architect") if r in ROLES[direction]][:1]
    if direction in ("data_ml", "security") and rnd.random() < 0.4:
        roles.append(rnd.choice(["researcher", "analyst"]))
    roles = list(dict.fromkeys(roles))
    city = rnd.choice(CITIES)
    wf = rnd.choice([WorkFormat.remote, WorkFormat.remote, WorkFormat.hybrid, WorkFormat.office, WorkFormat.any])
    base = {"intern": 45_000, "junior": 70_000, "middle": 160_000, "senior": 280_000, "lead": 380_000,
            "principal": 520_000}[grade]
    p = CandidateProfile(
        user_id=u.id, full_name=name, phone=f"+7 900 {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}",
        telegram=f"@demo_{idx:03d}", city=city, work_format=wf, relocation=rnd.random() < 0.3, experience_years=exp,
        salary_min_hidden=int(round(base * rnd.uniform(0.9, 1.3), -4)), privacy={}, visible_to_employers=True,
        public_ref=new_public_ref(db), onboarding_completed_at=utcnow(), roles=roles,
        headline=f"{direction} · {grade} (демо)" if status == "confirmed" else f"{direction} (демо)",
    )
    db.add(p)
    if grade in ("lead", "principal"):
        p.about = (f"Модельный кандидат уровня {grade.capitalize()} — модель, не люди: синтетический профиль для показа "
                   "подбора на уровни Lead и Principal; результат теста тоже модельный.")
        p.privacy = {"demo_model": True}
    if audience:
        p.about = {"school": "Школьник, участник ФСП. Учебные проекты и соревнования (синтетическое демо).",
                   "student": "Студент, участник ФСП. Стажировка и командные проекты (синтетическое демо).",
                   "professional": "Опытный ИТ-специалист. Коммерческие проекты (синтетическое демо)."}[audience]
        p.privacy = {"demo_audience": audience}
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
    if grade == "intern":  # у Стажёра погрешность выше (лёгких семейств в банке пока мало); θ — чтобы P(θ ≥ порога) ≥ 0,8
        se = round(rnd.uniform(0.42, 0.5), 2)
        theta = round(CUT[grade] + 0.85 * se + rnd.uniform(0.02, 0.45), 2)
        answered = 16
        correct = max(5, int(round(answered * 0.45 + rnd.randint(-2, 2))))
    if grade in ("lead", "principal") and confirmed:  # модельный Lead/Principal: P(θ ≥ порога) ≥ 0,8, полный тест,
        # θ̂ ниже порога следующего уровня (иначе уровень был бы выше)
        se = round(rnd.uniform(0.36, 0.46), 2)
        theta = round(CUT[grade] + 0.85 * se + rnd.uniform(0.02, 0.2), 2)
        answered = 18
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
        # New dictionary entries broaden T0, not the actual assessment bank's coverage.
        # Consume RNG identically, but do not invent confirmation for unsupported new tags.
        if audience and t in {"kotlin", "csharp", "php", "kubernetes"}:
            continue
        db.add(CandidateFact(user_id=u.id, kind="skill", key=t, title=tag_title(t),
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
    return p


def extend_candidates(db: Session, rng_seed: int = 20261007, *, base_seed: int = 20261006) -> dict:
    """Идемпотентное добавление демо-кандидатов после 150 основных (их строки не читаются и не меняются):
    151…161 — статусы грейда (И1), 162…171 — стажёры (И13), далее до 500 — расширение И8 (две аудитории, широкий стек).
    Повторный запуск (и запуск на сервере без --reset) добавляет только отсутствующих."""
    existing = set(db.scalars(select(User.email).where(User.email.like("demo-candidate-%@demo.invalid"))))
    pwd_hash = hash_password(secrets.token_urlsafe(24))
    added = 0
    if f"demo-candidate-{STATUS_INTERN_FIRST:03d}@demo.invalid" not in existing:
        last = _status_and_intern_candidates(db, STATUS_INTERN_FIRST - 1, base_seed, pwd_hash)
        added += last - STATUS_INTERN_FIRST + 1
        existing |= {f"demo-candidate-{i:03d}@demo.invalid" for i in range(STATUS_INTERN_FIRST, last + 1)}
    backends = [
        ["go", "postgresql", "grpc", "kafka", "docker", "kubernetes", "redis", "git"],
        ["java", "kafka", "postgresql", "docker", "kubernetes", "grpc", "redis", "git"],
        ["kotlin", "postgresql", "kafka", "java", "docker", "kubernetes", "grpc", "git"],
        ["csharp", "postgresql", "rest-api", "kafka", "docker", "kubernetes", "redis", "git"],
        ["php", "postgresql", "redis", "docker", "kafka", "kubernetes", "http", "git"],
        CORE["backend"],
    ]
    audiences = {"school": 0, "student": 0, "professional": 0}
    for idx in range(151, 501):
        if f"demo-candidate-{idx:03d}@demo.invalid" in existing:  # в т. ч. 151…171 — статусы грейда и стажёры
            continue
        rnd = random.Random(rng_seed + idx)
        offset = idx - 151
        # План И8: 120 backend + 230 по остальным направлениям; индексы 151…171 заняты статусами грейда и стажёрами,
        # поэтому из backend-части расширения остаётся 99 (всего 500 демо-кандидатов)
        direction = "backend" if offset < 120 else DIRECTIONS[1 + (offset - 120) % 4]
        grade = GRADES[(offset // 5) % 3]
        audience = ("school" if offset % 4 == 0 else "student") if grade == "junior" else "professional"
        core = backends[offset % len(backends)] if direction == "backend" else CORE[direction]
        _candidate(db, rnd, idx, direction, grade, pwd_hash, audience != "professional" or offset % 3 == 0,
                   core_override=core, audience=audience)
        audiences[audience] += 1
        added += 1
        if added % 50 == 0:
            db.flush()
    db.flush()
    ext = ext_candidates(db, rng_seed, pwd_hash, existing)
    added += ext
    # existing уже включает добавленных выше 151…171; audiences — только расширение И8
    return {"added": added, "total": len(existing) + sum(audiences.values()) + ext, "audiences_added": audiences,
            "ext_added": ext}


def ext_candidates(db: Session, rng_seed: int, pwd_hash: str, existing: set[str]) -> int:
    """Модельные демо-кандидаты Lead/Principal (флаг GRADES_EXT_ENABLED): номера с 701, по направлению — 3 Lead и
    2 Principal, только если уровень виден в направлении (в банке есть его проверенные семейства). Идемпотентно:
    номер закреплён за (направление, уровень, i), отсутствующие добавляются после появления семейств в банке."""
    from app.modules.catalog import levels
    from app.modules.catalog.levels_seed import ensure

    if not levels.enabled():
        return 0
    ensure(db)  # грейды и категории Lead/Principal в справочнике
    added = 0
    idx = EXT_FIRST
    for d in DIRECTIONS:
        for g, n in EXT_PER_DIRECTION.items():
            for i in range(n):
                email = f"demo-candidate-{idx:03d}@demo.invalid"
                if email not in existing and levels.is_available(d, g):
                    rnd = random.Random(rng_seed + 7000 + idx)
                    _candidate(db, rnd, idx, d, g, pwd_hash, with_fsp=(i == 0))
                    existing.add(email)
                    added += 1
                idx += 1
    db.flush()
    return added


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


STATUS_INTERN_FIRST = 151  # первый индекс после 150 основных: статусы грейда (И1), затем стажёры (И13)


def _status_and_intern_candidates(db: Session, idx: int, rng_seed: int, pwd_hash: str) -> int:
    """151…161 — статусы грейда, 162…171 — стажёры; отдельные генераторы, 150 основных кандидатов не сдвигаются."""
    idx = _extra_candidates(db, idx, rng_seed, pwd_hash)
    rnd_i = random.Random(rng_seed + 13)
    for d in DIRECTIONS:
        for i in range(INTERN_PER_DIRECTION):
            idx += 1
            _candidate(db, rnd_i, idx, d, "intern", pwd_hash, with_fsp=(i == 0))
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
    # После 150 основных: статусы грейда (И1, 151…161), стажёры (И13, 162…171), расширение до 500 (И8)
    extension = extend_candidates(db, base_seed=rng_seed)
    db.commit()
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
    for ci, text in NEEDS + INTERN_NEEDS:
        u, c = employers[ci]
        req = parse_need(text, use_llm=False)
        n = EmployerNeed(company_id=c.id, created_by=u.id, title=text.split(":")[0][:200], raw_text=text,
                         requirements=req, direction_id=req.get("direction"), grade_id=req.get("grade"),
                         salary_from=req.get("salary_from"), salary_to=req.get("salary_to"), status=NeedStatus.active)
        db.add(n)
        db.flush()
        sel = ranking.build_selection(db, req, {})
        db.add(SelectionVersion(need_id=n.id, version=1, parent_version=None, filters={"_meta": sel["meta"]},
                                requirements=req, results=sel["results"], algorithm_version=sel["algorithm"],
                                created_by=u.id))  # Ф2: снимок версии — открытие без пересчёта
    db.commit()
    fsp = db.scalar(select(func.count()).select_from(FspPassport).join(User, User.id == FspPassport.user_id)
                    .where(User.is_demo.is_(True)))
    return {"candidates": idx + extension["added"], "interns": INTERN_PER_DIRECTION * len(DIRECTIONS), "with_fsp": fsp,
            "employers": len(employers), "needs": len(NEEDS) + len(INTERN_NEEDS)}


# ------------------------------------------------------------------ расширение каталога (волна 7, catalog/ext.py)
# Модельные кандидаты новых направлений: только для видимых направлений (CATALOG_EXT_ENABLED и проверенный банк),
# с подписью «модель, не люди». Номера 501…580 закреплены за направлением (по 20), чтобы порядок включения
# направлений не сдвигал кандидатов; 500 исходных демо-кандидатов не меняются.
EXT_DEMO_FIRST = {"devops": 501, "data_eng": 521, "mobile": 541, "analyst": 561}
EXT_DEMO_GRADES = ["intern"] * 4 + ["junior"] * 6 + ["middle"] * 6 + ["senior"] * 4
CORE.update({
    "devops": ["linux", "docker", "kubernetes", "ci-cd", "terraform", "monitoring", "ansible", "helm", "networking",
               "nginx", "sre", "cloud", "python", "git", "postgresql"],  # «bash» — синоним тега linux в
    # словаре разбора (dictionary.py), отдельного тега в справочнике нет: на PostgreSQL FK survey_stack_tags → stack_tags
    # откатывал весь пересев (FIX7, выкладка 6)
    "data_eng": ["sql", "python", "etl", "dwh", "airflow", "spark", "kafka", "dbt", "clickhouse", "greenplum",
                 "streaming", "data-quality", "postgresql", "git", "docker"],
    "mobile": ["kotlin", "android", "jetpack-compose", "mobile-architecture", "swift", "ios", "swiftui", "flutter",
               "react-native", "rest-api", "git", "frontend-testing", "ci-cd"],
    "analyst": ["requirements", "bpmn", "uml", "user-stories", "integrations", "sql", "er-modeling", "rest-api", "http",
                "postgresql", "test-design", "git"],
})
ROLES.update({"devops": ["devops", "tech_lead", "architect", "mentor"], "data_eng": ["developer", "architect", "mentor"],
              "mobile": ["developer", "tech_lead", "mentor"], "analyst": ["analyst", "team_lead", "mentor"]})
DISC_BY_DIR.update({"devops": ["product", "security"], "data_eng": ["product", "algorithmic"],
                    "mobile": ["product"], "analyst": ["product"]})
EXT_DEMO_NEEDS = {
    "devops": (5, "DevOps-инженер middle: Kubernetes, Terraform, CI/CD, Prometheus и Grafana, Linux. Желательно Ansible "
                  "и Helm. Екатеринбург или удалённо, 220–300 тыс. ₽"),
    "data_eng": (1, "Инженер данных middle: Airflow, Spark, SQL, DWH и dbt; желательно Kafka и ClickHouse. Москва, гибрид."),
    "mobile": (3, "Android-разработчик middle: Kotlin, Jetpack Compose, MVVM, работа с REST API. Казань или удалённо."),
    "analyst": (0, "Системный аналитик middle: сбор требований, BPMN, UML, проектирование интеграций и API, SQL. "
                   "Санкт-Петербург, гибрид."),
}


def extend_catalog_ext(db: Session, rng_seed: int = 20261010) -> dict:
    """Идемпотентно: модельные кандидаты (по 20 на направление: 4 стажёра, 6 Junior, 6 Middle, 4 Senior) и по одной
    демо-потребности у демо-компаний — только для видимых направлений расширения каталога. Без флага — ничего."""
    from app.modules.catalog import ext

    dirs = [d for d in EXT_DEMO_FIRST if ext.is_visible(d)]
    if not dirs:
        return {"added": 0, "directions": [], "needs": 0}
    existing = set(db.scalars(select(User.email).where(User.email.like("demo-candidate-%@demo.invalid"))))
    pwd_hash = hash_password(secrets.token_urlsafe(24))
    added = 0
    for d in dirs:
        for k, grade in enumerate(EXT_DEMO_GRADES):
            idx = EXT_DEMO_FIRST[d] + k
            if f"demo-candidate-{idx:03d}@demo.invalid" in existing:
                continue
            rnd = random.Random(rng_seed + idx)
            p = _candidate(db, rnd, idx, d, grade, pwd_hash, with_fsp=k % 3 == 0)
            if p is not None:
                p.headline = f"{direction_title(d)} · {grade} ({ext.MODEL_LABEL})"
                p.about = (f"Модельный кандидат направления «{direction_title(d)}» ({ext.MODEL_LABEL}): синтетический "
                           "профиль для показа подбора в новом направлении каталога.")
                p.privacy = {"demo_audience": "model"}
            added += 1
        db.flush()
    needs = 0
    companies = db.scalars(select(Company).where(Company.is_demo.is_(True)).order_by(Company.name)).all()
    by_name = {c.name: c for c in companies}
    for d in dirs:
        ci, text = EXT_DEMO_NEEDS[d]
        c = by_name.get(COMPANIES[ci][0])
        if c is None or db.scalar(select(EmployerNeed.id).where(EmployerNeed.company_id == c.id,
                                                                EmployerNeed.raw_text == text)):
            continue
        req = parse_need(text, use_llm=False)
        n = EmployerNeed(company_id=c.id, created_by=c.created_by, title=text.split(":")[0][:200], raw_text=text,
                         requirements=req, direction_id=req.get("direction"), grade_id=req.get("grade"),
                         salary_from=req.get("salary_from"), salary_to=req.get("salary_to"), status=NeedStatus.active)
        db.add(n)
        db.flush()
        sel = ranking.build_selection(db, req, {})
        db.add(SelectionVersion(need_id=n.id, version=1, parent_version=None, filters={"_meta": sel["meta"]},
                                requirements=req, results=sel["results"], algorithm_version=sel["algorithm"],
                                created_by=c.created_by))
        needs += 1
    db.commit()
    return {"added": added, "directions": dirs, "needs": needs}


def demo_pool_size(db: Session) -> int:
    """Демо-пользователи основных демо-данных — без учёток жюри и гостей живой демонстрации (@jury.example.com):
    их api создаёт сам при старте (общее демо, запасная песочница), и они не значат, что 150 кандидатов уже есть."""
    from app.modules.jury.scope import DOMAIN

    return db.scalar(select(func.count()).select_from(User).where(
        User.is_demo.is_(True), User.email.not_like(f"%@{DOMAIN}"))) or 0


def drop_jury_built_on_empty_pool(db: Session) -> list[str]:
    """Демо жюри (общее и песочницы), созданное api до основных демо-данных: его подборки и кубки собраны по пустой
    базе (в подборках — только кандидаты жюри, у Марии «1 место из 1»). Удаляем — при первом входе жюри оно
    создастся заново уже по полным данным, запасная песочница — при открытии главной.
    Возвращает удалённые ("" — общее)."""
    from app.modules.jury import seed as jury

    sids = ["", *sorted(jury.sandboxes(db))]
    for sid in sids:
        jury.delete_jury(db, sid)
    return sids


def main() -> None:
    ap = argparse.ArgumentParser(description="Демо-данные платформы")
    ap.add_argument("--reset", action="store_true", help="удалить демо-данные и создать заново")
    ap.add_argument("--delete", action="store_true", help="только удалить демо-данные")
    a = ap.parse_args()
    get_engine()
    with SessionLocal() as db:
        exists = demo_pool_size(db)
        if a.reset or a.delete:
            print(f"Удалено демо-пользователей: {delete_demo(db)}")
            exists = 0
        if a.delete:
            return
        from app.integrations.vacancies import demo as vacancies_demo

        if exists:
            # демо-данные уже есть: без --reset досоздаются только новые кандидаты (И8: 151…500), остальное не трогается
            print(extend_candidates(db))
            db.commit()
        else:
            if not a.reset and (boxes := [s for s in drop_jury_built_on_empty_pool(db) if s]):
                print(f"Демо жюри, созданное до демо-данных, удалено (песочниц: {len(boxes)}) — создастся при входе")
            print(seed(db))
        print(f"Демо-вакансии: {vacancies_demo.ensure(db)}")  # отдельной командой их легко забыть
        # модельные кандидаты новых направлений каталога (только при CATALOG_EXT_ENABLED и проверенном банке)
        print(f"Модельные кандидаты новых направлений: {extend_catalog_ext(db)}")


if __name__ == "__main__":
    main()
