"""Обратная связь после теста (идея 11 брифа): карта навыков, разрыв со спросом работодателей, маршрут роста.

* **Карта навыков** — по темам (стек-теги справочника, в которые сводятся навыки семейств банка, skill_map.py)
  и аспектам (сами навыки банка с русскими названиями). Для каждой темы: сколько заданий, доля набранных баллов,
  ожидаемая доля для θ кандидата по модели 2PL (выше / ниже своего уровня) и статус. Наружу не уходят ни
  формулировки заданий, ни ключи, ни семейства, ни позиции: только агрегаты по темам. Канарейки (контрольные
  опубликованные варианты) в карту не входят. Тест не банка (заглушка, демо-данные) — карта по фактам T1.
* **Спрос работодателей** — реальные активные потребности и опубликованные вакансии в БД по категории кандидата
  (если в категории меньше 3 — по направлению): какие навыки требуют чаще всего (обязательно / плюсом) и
  подтверждён ли навык у кандидата (T1 — тестом; T0 — только заявлен; нет). Отмечается, есть ли в банке
  задания на навык, — от этого зависит способ подтверждения.
* **Маршрут роста** — упорядоченные шаги: грейд, востребованные навыки без подтверждения, слабые темы теста;
  рекомендация дисциплин ФСП и следующего уровня соревнований с объяснением «почему».

Без LLM: всё считается правилами по данным сессии и БД (детерминированно, быстро, проверяемо).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware
from app.core.enums import NeedStatus, TestSessionStatus
from app.modules.assessment.integrity import summary_for_employer
from app.modules.assessment.models import TestSession
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.seed_data import DIRECTIONS, GRADES, STACK
from app.modules.profiles.facts import DISCIPLINE_RELEVANCE, load_bundles

STRONG, OK = 0.75, 0.5  # пороги статуса темы по доле набранных баллов
REL_DELTA = 0.2  # «выше/ниже вашего уровня»: отклонение от ожидаемой по θ доли
MIN_SOURCES_IN_GRADE = 3  # меньше потребностей в категории — спрос считается по направлению
TOP_DEMAND = 10
GRADE_CUTS = {"junior": -1.0, "middle": 0.0, "senior": 1.0}
GRADE_ORDER = ["junior", "middle", "senior"]
FSP_CALENDAR_URL = "https://fsp-russia.ru/calendar/"
COMMON_TAGS = {"algorithms", "sql", "http", "git", "linux", "docker"}

STATUS_TITLES = {"strong": "уверенно", "ok": "в целом освоено", "gap": "пробел", "pending": "на проверке"}
DEMAND_STATUS_TITLES = {"confirmed": "подтверждён тестом (T1)", "weak": "проверен тестом, результат ниже 50 %",
                        "declared": "заявлен, не подтверждён (T0)", "missing": "нет в профиле"}

# Темы для семейств, навыки которых не сводятся к стек-тегам справочника
_EXTRA_TOPICS = [({"networking", "cidr", "ipv4", "routing"}, "networking", "Сети и адресация"),
                 ({"web_security", "xss", "csp"}, "web-security", "Безопасность веб-клиента")]

# Аспекты темы — навыки семейств банка по-русски. Навык без названия здесь в аспекты не выводится
# (обычно это сама тема: python, sql, javascript …).
ASPECT_TITLES: dict[str, str] = {
    # общий блок: алгоритмы, SQL, HTTP, Git, Linux
    "binary_search": "бинарный поиск", "heap": "куча и очередь с приоритетом", "data_structures": "структуры данных",
    "complexity": "сложность алгоритмов", "sorting": "сортировка", "stack": "стек", "queue": "очередь",
    "intervals": "интервалы", "ordered_dict": "упорядоченные словари", "boundary_conditions": "граничные условия",
    "branching": "ветвление", "caching": "кэширование", "edge_cases": "крайние случаи", "off_by_one": "ошибки на единицу",
    "joins": "JOIN", "window_functions": "оконные функции", "having": "GROUP BY и HAVING", "subqueries": "подзапросы",
    "aggregation": "агрегация", "null_semantics": "NULL в условиях и агрегатах", "three_valued_logic": "трёхзначная логика",
    "indexes": "индексы", "query_planning": "план запроса", "date_ranges": "диапазоны дат", "transactions": "транзакции",
    "isolation_levels": "уровни изоляции", "isolation": "изоляция транзакций", "mvcc": "MVCC", "locking": "блокировки",
    "atomicity": "атомарность", "concurrency_control": "управление конкурентным доступом", "migrations": "миграции схемы",
    "orm": "ORM", "n_plus_one": "проблема N+1", "pagination": "пагинация", "reporting": "отчётные запросы",
    "slowly_changing_data": "медленно меняющиеся данные", "rest_api": "REST", "api_design": "проектирование API",
    "idempotency": "идемпотентность", "api": "контракты API", "webhooks": "вебхуки", "rate_limiting": "ограничение частоты",
    "timeouts": "таймауты", "retries": "повторы запросов", "history_rewriting": "переписывание истории",
    "shell": "командная оболочка", "bash": "bash", "awk": "awk", "permissions": "права доступа",
    "text_processing": "обработка текста", "exit_codes": "коды возврата", "logs": "журналы",
    "time_zones": "часовые пояса", "timezones": "часовые пояса", "datetime": "дата и время", "unicode": "Unicode",
    "utf8": "UTF-8", "encodings": "кодировки",
    # backend
    "asyncio": "asyncio", "concurrency": "конкурентность", "race_conditions": "гонки", "threads": "потоки",
    "contextvars": "contextvars", "event_loop": "цикл событий", "messaging": "очереди сообщений", "queues": "очереди",
    "at_least_once": "доставка «хотя бы один раз»", "payments": "платежи", "billing": "биллинг", "money": "денежные суммы",
    "decimal": "Decimal", "numeric_precision": "точность вычислений", "distributed_systems": "распределённые системы",
    "reliability": "надёжность", "consistency": "согласованность", "cache_invalidation": "инвалидация кэша",
    "error_handling": "обработка ошибок", "system_design": "проектирование систем", "architecture": "архитектура",
    "observability": "наблюдаемость", "tracing": "трассировка", "logging": "логирование", "monitoring": "мониторинг",
    "performance": "производительность", "dict": "словари", "functions": "функции", "state": "состояние",
    "iterators": "итераторы", "generators": "генераторы", "classes": "классы",
    # frontend
    "async_await": "async/await", "closures": "замыкания", "promises": "промисы", "scope": "области видимости",
    "timers": "таймеры", "operators": "операторы", "type_coercion": "приведение типов", "this": "this",
    "arrays": "массивы", "es_modules": "ES-модули", "bundlers": "сборщики", "build": "сборка", "monorepo": "монорепозиторий",
    "core_web_vitals": "Core Web Vitals", "web_performance": "производительность страниц", "accessibility": "доступность",
    "aria": "ARIA", "screen_readers": "скринридеры", "focus_management": "управление фокусом", "keyboard": "клавиатура",
    "html": "семантика HTML", "forms": "формы", "dom_events": "события DOM", "memory_leaks": "утечки памяти",
    "memoization": "мемоизация", "rendering": "рендеринг", "react_query": "запросы данных", "abort_controller": "отмена запросов",
    "state_management": "управление состоянием", "frontend_architecture": "архитектура фронтенда",
    "type_narrowing": "сужение типов", "type_guards": "type guards", "api_validation": "валидация ответов API",
    "web_security": "безопасность веб-клиента", "xss": "XSS", "csp": "CSP", "oauth": "OAuth", "auth_tokens": "токены",
    "html_escaping": "экранирование HTML", "ux": "UX",
    # data/ml
    "ab_testing": "A/B-тесты", "hypothesis_testing": "проверка гипотез", "p_value": "p-value",
    "power_analysis": "мощность теста", "sample_size": "размер выборки", "experiment_design": "дизайн эксперимента",
    "descriptive_statistics": "описательная статистика", "quartiles": "квартили", "outliers": "выбросы",
    "percentiles": "перцентили", "mann_whitney": "критерий Манна — Уитни", "ties": "связанные ранги",
    "data_cleaning": "очистка данных", "missing_values": "пропуски", "deduplication": "дедупликация", "csv": "CSV",
    "data_processing": "обработка данных", "etl": "ETL", "time_series": "временные ряды", "analytics": "аналитика",
    "categorical_encoding": "кодирование категорий", "feature_engineering": "признаки",
    "classification_metrics": "метрики классификации", "confusion_matrix": "матрица ошибок", "f1": "F1",
    "precision_recall": "precision и recall", "roc_auc": "ROC AUC", "pr_auc": "PR AUC", "threshold": "порог решения",
    "calibration": "калибровка", "class_imbalance": "несбалансированные классы", "cross_validation": "кросс-валидация",
    "group_kfold": "GroupKFold", "time_split": "разбиение по времени", "train_test_split": "разбиение выборки",
    "data_leakage": "утечка данных", "overfitting": "переобучение", "early_stopping": "ранняя остановка",
    "model_training": "обучение модели", "model_evaluation": "оценка модели", "validation": "валидация",
    "preprocessing": "предобработка", "random_seed": "воспроизводимость seed", "reproducibility": "воспроизводимость",
    "experiment_tracking": "трекинг экспериментов", "training_serving_skew": "расхождение обучения и прода",
    "ml_monitoring": "мониторинг моделей", "model_monitoring": "мониторинг моделей", "data_drift": "дрейф данных",
    "psi": "PSI", "ml_systems": "ML-системы", "llm": "LLM", "rag": "RAG", "chunking": "нарезка документов",
    "ranking": "ранжирование",
    # qa
    "test_review": "ревью тестов", "false_positive": "ложные срабатывания", "defect_localization": "локализация дефекта",
    "test_architecture": "архитектура тестов", "smoke_testing": "смоук-тесты", "incident_analysis": "разбор инцидентов",
    "data_testing": "тестирование данных", "data_quality": "качество данных", "etl_testing": "тестирование ETL",
    "fixtures": "фикстуры", "parametrize": "параметризация", "unittest_mock": "моки", "async_testing": "асинхронные тесты",
    "jest": "Jest", "ci": "CI", "test_design": "тест-дизайн", "boundary_value_analysis": "граничные значения",
    "equivalence_partitioning": "классы эквивалентности", "pairwise_testing": "попарное тестирование",
    "combinatorial_testing": "комбинаторное тестирование", "configuration_testing": "конфигурации",
    "decision_tables": "таблицы решений", "requirements": "требования", "risk_based_testing": "тестирование по рискам",
    "regression_strategy": "регрессия", "test_automation_strategy": "стратегия автоматизации",
    "release_management": "релизы", "api_testing": "тестирование API", "contract_testing": "контрактные тесты",
    "test_data_design": "тестовые данные", "performance_testing": "тестирование производительности",
    "load_testing": "нагрузочное тестирование", "slo": "SLO", "littles_law": "закон Литтла", "histograms": "гистограммы",
    "metrics_aggregation": "агрегация метрик", "flaky_tests": "нестабильные тесты", "test_isolation": "изоляция тестов",
    "brittle_tests": "хрупкие тесты", "assertions": "проверки", "test_maintenance": "поддержка тестов",
    "frontend_testing": "тесты фронтенда", "defect_management": "работа с дефектами", "triage": "триаж",
    "severity": "серьёзность", "priority": "приоритет",
    # security
    "secure_code_review": "ревью кода на уязвимости", "input_validation": "валидация ввода",
    "output_encoding": "кодирование вывода", "csrf": "CSRF", "cors": "CORS", "cookies": "cookie",
    "authorization": "авторизация", "access_control": "контроль доступа", "ownership": "проверка владельца",
    "parameterized_queries": "параметризованные запросы", "templates": "шаблоны", "serialization": "сериализация",
    "path_normalization": "нормализация путей", "token_validation": "проверка токенов",
    "session_lifecycle": "жизненный цикл сессии", "secure_defaults": "безопасные умолчания",
    "secure_configuration": "безопасная конфигурация", "configuration": "конфигурация",
    "secrets_management": "хранение секретов", "trust_boundaries": "границы доверия", "threat_modeling": "модель угроз",
    "secure_design": "безопасное проектирование", "dependencies": "зависимости", "patch_management": "обновления",
    "versioning": "версии", "release_policy": "политика выпусков", "data_minimization": "минимизация данных",
    "aead": "AEAD", "hmac": "HMAC", "nonce_uniqueness": "уникальность nonce", "password_hashing": "хеширование паролей",
    "scrypt": "scrypt", "salts": "соль", "secure_randomness": "криптостойкая случайность",
    "key_lifecycle": "жизненный цикл ключей", "constant_time_comparison": "сравнение за постоянное время",
    "incident_response": "реагирование на инциденты", "security_logging": "журналы безопасности",
    "vulnerability_triage": "разбор уязвимостей", "cvss": "CVSS", "risk_prioritization": "приоритизация рисков",
    "prioritization": "приоритизация", "evidence_preservation": "сохранение улик", "containment": "локализация инцидента",
    "recovery": "восстановление", "communication": "коммуникация в инциденте",
    "networking": "сети", "ipv4": "IPv4", "cidr": "CIDR", "routing": "маршрутизация",
}

DISCIPLINES = {d["id"]: d["title"] for d in FSP_DISCIPLINES}
# Темы, которые тренирует дисциплина ФСП (для объяснения «почему эта дисциплина»)
DISCIPLINE_TOPICS: dict[str, set[str]] = {
    "algorithmic": {"algorithms", "python", "sql", "javascript"},
    "product": {"rest-api", "http", "fastapi", "django", "postgresql", "redis", "rabbitmq", "kafka", "docker", "git",
                "react", "typescript", "javascript", "html-css", "state-management", "frontend-testing", "a11y",
                "vite-webpack", "test-design", "api-testing", "pytest", "ci-cd", "playwright", "load-testing",
                "pandas", "scikit-learn", "statistics", "mlops", "nlp", "airflow", "sql", "python", "asyncio"},
    "security": {"owasp", "cryptography", "network-security", "siem-soc", "forensics", "pentest", "linux",
                 "reverse-engineering", "ctf", "burp-suite", "web-security", "networking"},
    "robotics": {"python", "algorithms", "cv"},
    "uav": {"python", "algorithms", "cv", "pytorch"},
}
DISCIPLINE_WHY = {
    "algorithmic": "задачи на алгоритмы и структуры данных на время — то, что проверяет общий блок теста",
    "product": "командная разработка продукта за ограниченное время: API, данные, интерфейс, тесты — "
               "ровно то, что пишут в требованиях работодатели",
    "security": "CTF и защита систем: уязвимости веб-приложений, криптография, сети, разбор инцидентов",
    "robotics": "программирование роботов: алгоритмы, управление, компьютерное зрение",
    "uav": "программирование беспилотных систем: навигация, компьютерное зрение, работа с сенсорами",
}
DIRECTION_DISCIPLINES = {"backend": ["product", "algorithmic"], "frontend": ["product", "algorithmic"],
                         "data_ml": ["product", "algorithmic", "uav"], "qa": ["product"],
                         "security": ["security", "algorithmic"]}
LEVEL_ORDER = ["school", "regional", "interregional", "national", "international"]
LEVEL_RU = {"school": "школьный", "regional": "региональный", "interregional": "межрегиональный",
            "national": "всероссийский", "international": "международный"}
NEXT_STEP = {
    None: "Начните с региональных соревнований или отборочных этапов Кубка России (весной, по всем дисциплинам).",
    "school": "Следующий шаг — региональные соревнования и отборочные этапы Кубка России.",
    "regional": "Следующий шаг — межрегиональный уровень: отборочные этапы Кубка России и Кубка ФСП среди округов.",
    "interregional": "Следующий шаг — всероссийский уровень: финал Кубка России, Чемпионат России.",
    "national": "Вы уже на всероссийском уровне: цель — призовые места Чемпионата России и международные старты.",
    "international": "У вас международный уровень: удерживайте результат — свежие достижения весят больше.",
}


def _title(tag: str) -> str:
    for _, t, title in _EXTRA_TOPICS:
        if t == tag:
            return title
    return STACK.get(tag, (tag,))[0]


def _status(score: float | None) -> str:
    if score is None:
        return "pending"
    return "strong" if score >= STRONG else "ok" if score >= OK else "gap"


def _grade_of_b(b: float) -> str:
    """Уровень задания по средней трудности b относительно порогов грейдов."""
    return "junior" if b < -0.5 else "middle" if b < 0.5 else "senior"


@lru_cache(maxsize=8)
def bank_tags(direction: str) -> frozenset[str]:
    """Стек-теги, на которые в банке есть задания для направления (с общим блоком)."""
    try:
        from assessment_bank import load_specs

        from app.modules.assessment.skill_map import to_stack_tags
    except Exception:  # noqa: BLE001 — банк недоступен: считаем, что заданий нет
        return frozenset()
    out: set[str] = set()
    for s in load_specs().values():
        if s.direction in (direction, "common") and not s.canary:
            out.update(to_stack_tags(s.direction, s.skills))
    return frozenset(out)


def _topics_from_session(ts: TestSession) -> list[dict] | None:
    """Темы по заданиям сессии банка. None — сессия не банка (заглушка, демо-данные)."""
    res = ts.result or {}
    if not str(res.get("engine", "")).startswith("bank"):
        return None
    from assessment_bank.psychometrics import prob

    from app.modules.assessment.bank_engine import _pool_from_snapshot
    from app.modules.assessment.skill_map import to_stack_tags

    theta = ts.theta if ts.theta is not None else 0.0
    acc: dict[str, dict] = {}
    for it in (res.get("state") or {}).get("items", []):
        if not it.get("done") or it.get("canary"):
            continue
        xs = [v for v in it.get("x", []) if v is not None]
        score = float(np.mean(xs)) if xs else None
        try:
            pi = _pool_from_snapshot(it["pool"])
            expected = float(np.mean(prob(theta, pi.a_eff, pi.b)))
            b = float(np.mean(pi.b))
        except Exception:  # noqa: BLE001 — старый снимок без параметров: без ожидаемой доли
            expected, b = None, None
        tags = list(it.get("skills") or [])
        if not tags:
            bank = set(it.get("bank_skills") or [])
            tags = [next((t for keys, t, _ in _EXTRA_TOPICS if keys & bank), "other")]
        for tag in tags:
            d = acc.setdefault(tag, {"n": 0, "scored": 0, "sum": 0.0, "exp": [], "pending": 0, "blocks": Counter(),
                                     "b": [], "aspects": defaultdict(lambda: [0, 0.0, 0])})
            d["n"] += 1
            d["blocks"]["common" if it.get("block") == "common" else "direction"] += 1
            if b is not None:
                d["b"].append(b)
            if score is None:
                d["pending"] += 1
            else:
                d["scored"] += 1
                d["sum"] += score
                if expected is not None:
                    d["exp"].append(expected)
            for sk in it.get("bank_skills") or []:
                # аспект — к своей теме; навык без стек-тега — к основной (первой) теме задания
                own = to_stack_tags(it.get("block") or "common", [sk])
                if (own[0] if own else tags[0]) != tag:
                    continue
                if sk in ASPECT_TITLES and ASPECT_TITLES[sk].lower() != _title(tag).lower():
                    a = d["aspects"][sk]
                    a[0] += 1
                    if score is not None:
                        a[1] += score
                        a[2] += 1
    out = []
    for tag, d in acc.items():
        score = round(d["sum"] / d["scored"], 2) if d["scored"] else None
        expected = round(float(np.mean(d["exp"])), 2) if d["exp"] else None
        rel = None
        if score is not None and expected is not None:
            delta = score - expected
            rel = "above" if delta >= REL_DELTA else "below" if delta <= -REL_DELTA else "as_expected"
        aspects = [{"title": ASPECT_TITLES[k], "n": v[0], "score": round(v[1] / v[2], 2) if v[2] else None,
                    "status": _status(round(v[1] / v[2], 2) if v[2] else None)} for k, v in d["aspects"].items()]
        aspects.sort(key=lambda a: (a["score"] if a["score"] is not None else 2.0, a["title"]))
        out.append({
            "tag": tag, "title": _title(tag), "block": d["blocks"].most_common(1)[0][0], "n": d["n"],
            "scored": d["scored"], "pending": d["pending"], "score": score, "expected": expected, "relative": rel,
            "status": _status(score), "confidence": "low" if d["scored"] <= 1 else "medium" if d["scored"] == 2 else "high",
            "level": _grade_of_b(float(np.mean(d["b"]))) if d["b"] else None, "aspects": aspects[:8],
        })
    return out


def _topics_from_facts(bundle, direction: str) -> list[dict]:
    """Запасной путь: навыки T1 из фактов (заглушка теста, демо-данные без заданий банка)."""
    out = []
    for tag, f in bundle.skills_t1.items():
        v = f.value or {}
        score = v.get("score")
        n = int(v.get("total") or 0)
        out.append({"tag": tag, "title": _title(tag), "block": "common" if tag in COMMON_TAGS else "direction",
                    "n": n, "scored": n, "pending": 0, "score": score, "expected": None, "relative": None,
                    "status": _status(score), "confidence": "low" if n <= 1 else "medium" if n == 2 else "high",
                    "level": None, "aspects": []})
    return out


def _sort_topics(topics: list[dict]) -> list[dict]:
    return sorted(topics, key=lambda t: (0 if t["block"] == "common" else 1, -t["n"], t["title"]))


def _demand(db: Session, direction: str, grade: str | None, bundle, topics: dict[str, dict]) -> dict:
    """Спрос работодателей в категории: активные потребности и опубликованные вакансии в БД."""
    from app.integrations.vacancies.models import Vacancy
    from app.modules.matching.models import EmployerNeed

    sources: list[tuple[str | None, list[str], list[str]]] = []
    for n in db.scalars(select(EmployerNeed).where(EmployerNeed.status == NeedStatus.active,
                                                   EmployerNeed.direction_id == direction)).all():
        req = n.requirements or {}
        sources.append((n.grade_id or req.get("grade"),
                        [s["tag"] for s in req.get("stack_required") or [] if s.get("tag") in STACK],
                        [s["tag"] for s in req.get("stack_desired") or [] if s.get("tag") in STACK]))
    for v in db.scalars(select(Vacancy).where(Vacancy.status == "published",
                                              Vacancy.category_id.like(f"{direction}.%"))).all():
        sources.append(((v.category_id or "").split(".")[-1] or None, [t for t in v.stack or [] if t in STACK], []))
    sources = [s for s in sources if s[1] or s[2]]
    in_grade = [s for s in sources if grade and s[0] == grade]
    scope = "category" if len(in_grade) >= MIN_SOURCES_IN_GRADE else "direction"
    used = in_grade if scope == "category" else sources
    covered = bank_tags(direction)
    req_c, des_c = Counter(), Counter()
    for _, req, des in used:
        req_c.update(set(req))
        des_c.update(set(des) - set(req))

    def cand_status(tag: str) -> str:
        f = bundle.skills_t1.get(tag)
        if f is not None:
            return "confirmed" if (f.value or {}).get("score", 0) >= 0.5 else "weak"
        return "declared" if tag in bundle.stack_t0 else "missing"

    tags = sorted(set(req_c) | set(des_c), key=lambda t: (-(req_c[t] + 0.5 * des_c[t]), -req_c[t], _title(t)))
    items = []
    for t in tags[:TOP_DEMAND]:
        st = cand_status(t)
        tp = topics.get(t)
        items.append({"tag": t, "title": _title(t), "required": req_c[t], "desired": des_c[t],
                      "share": round((req_c[t] + des_c[t]) / len(used), 2) if used else 0.0,
                      "status": st, "status_title": DEMAND_STATUS_TITLES[st], "testable": t in covered,
                      "test_score": tp["score"] if tp else None})
    full, cov = 0, []
    for _, req, _ in used:
        if not req:
            continue
        ok = sum(1 for t in set(req) if cand_status(t) == "confirmed")
        cov.append(ok / len(set(req)))
        full += ok == len(set(req))
    n_req = len(cov)
    return {
        "scope": scope, "scope_title": (f"категория {DIRECTIONS.get(direction, direction)} · {GRADES.get(grade, grade)}"
                                        if scope == "category" else f"направление {DIRECTIONS.get(direction, direction)}"),
        "sources": len(used), "sources_in_category": len(in_grade), "items": items,
        "full_match": full, "with_required": n_req,
        "avg_required_coverage": round(sum(cov) / n_req, 2) if n_req else None,
        "note": ("Активные потребности работодателей и опубликованные вакансии на платформе. Навык «подтверждён», "
                 "если тест набрал по нему не меньше 50 % — так его видит работодатель (T1)."),
    }


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{round(v * 100)} %"


def _n_tasks(n: int) -> str:
    m10, m100 = n % 10, n % 100
    w = "задание" if m10 == 1 and m100 != 11 else "задания" if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else "заданий"
    return f"{n} {w}"


def _weak_aspects(tp: dict | None, k: int = 3) -> list[str]:
    if not tp:
        return []
    return [a["title"] for a in tp.get("aspects", []) if a["score"] is not None and a["score"] < OK][:k]


def _route(ts: TestSession | None, outcome: dict, profile, topics: dict[str, dict], demand: dict) -> list[dict]:
    steps: list[dict] = []
    er = outcome
    grade = (ts.claimed_grade_id if ts else None) or profile.current_grade_id
    lock = as_aware(profile.grade_locked_until)
    when = f" Пересдача со сменой грейда — с {lock:%d.%m.%Y}." if lock else ""
    if er:
        if er.get("confirmed") and er.get("upgrade_available") and grade in GRADE_ORDER[:-1]:
            nxt = GRADE_ORDER[GRADE_ORDER.index(grade) + 1]
            steps.append({"kind": "grade", "title": f"Тест на {GRADES[nxt]}",
                          "text": f"Результат уверенно выше порога {GRADES[grade]} — можно подтверждать {GRADES[nxt]}."
                                  + when, "tags": []})
        elif not er.get("confirmed"):
            lower = er.get("retake_lower")
            steps.append({"kind": "grade", "title": "Подготовиться и пересдать" if not lower else f"Тест на {GRADES.get(lower, lower)}",
                          "text": ("Грейд пока не подтверждён, текущая категория не понизится. Начните с пробелов ниже; "
                                   "повторная попытка — из другого набора заданий." if not lower else
                                   f"До {GRADES.get(grade, grade)} пока не хватает — подтвердите {GRADES.get(lower, lower)}, "
                                   "а к следующей попытке подтяните пробелы ниже."), "tags": []})
    n_src = demand.get("sources") or 0
    used_tags: set[str] = set()
    for d in demand.get("items", []):
        if len([s for s in steps if s["kind"] == "demand"]) >= 4:
            break
        if d["status"] == "confirmed":
            continue
        t, title = d["tag"], d["title"]
        word = "запроса" if n_src % 10 == 1 and n_src % 100 != 11 else "запросов"
        need = f"Требуют в {d['required'] + d['desired']} из {n_src} {word} работодателей" + (
            f" ({d['required']} — обязательно)" if d["required"] and d["desired"] else "")
        tp = topics.get(t)
        if d["status"] == "weak" or (tp and tp["status"] == "gap"):
            weak = _weak_aspects(tp)
            text = (f"{need}. В тесте — {_fmt_pct(tp['score'] if tp else None)}"
                    + (f" ({_n_tasks(tp['n'])})" if tp else "") + "."
                    + (f" Слабее всего: {', '.join(weak)}." if weak else "")
                    + " После подготовки пересдайте тест — задания подбираются заново.")
            steps.append({"kind": "demand", "title": f"Подтянуть «{title}»", "text": text, "tags": [t]})
        elif d["testable"]:
            if d["status"] == "declared":
                text = (f"{need}. В опросе навык заявлен, но тестом пока не подтверждён — работодатель видит его как "
                        "самоописание (T0). В банке есть задания на этот навык: при повторной попытке он может попасть в тест.")
                steps.append({"kind": "demand", "title": f"Подтвердить «{title}» тестом", "text": text, "tags": [t]})
            else:
                text = (f"{need}, в вашем профиле его нет. Освойте навык, добавьте его в опрос и пройдите тест — "
                        "он проверяется заданиями банка.")
                steps.append({"kind": "demand", "title": f"Освоить «{title}»", "text": text, "tags": [t]})
        else:
            text = (f"{need}. Заданий теста на этот навык нет — подтвердить его можно задачей-зондом от работодателя "
                    "(результат зонда — T1) или проектом на соревнованиях по продуктовому программированию."
                    + ("" if d["status"] == "declared" else " Сейчас его нет и в вашем профиле."))
            steps.append({"kind": "demand", "title": f"Показать «{title}» на практике", "text": text, "tags": [t]})
        used_tags.add(t)
    gaps = sorted([tp for tp in topics.values() if tp["status"] == "gap" and tp["tag"] not in used_tags],
                  key=lambda x: (x["score"] if x["score"] is not None else 1, -x["n"]))
    for tp in gaps[:3]:
        weak = _weak_aspects(tp)
        rel = " — ниже ожидаемого для вашего общего уровня" if tp.get("relative") == "below" else ""
        steps.append({"kind": "topic", "title": f"Подтянуть тему «{tp['title']}»",
                      "text": f"В тесте — {_fmt_pct(tp['score'])} ({_n_tasks(tp['n'])}){rel}."
                              + (f" Слабее всего: {', '.join(weak)}." if weak else ""), "tags": [tp["tag"]]})
    if not [s for s in steps if s["kind"] in ("demand", "topic")]:
        steps.append({"kind": "keep", "title": "Сильный профиль для категории",
                      "text": "Явных пробелов в теме теста и в спросе работодателей нет. Следующий рычаг — "
                              "достижения ФСП (T2): они дают бонус к месту в рейтинге категории.", "tags": []})
    return steps


def _competitions(db: Session, direction: str, category_id: str | None, bundle, topics: dict[str, dict],
                  demand: dict) -> list[dict]:
    from app.modules.fsp.models import FspAchievement, FspPassport
    from app.modules.profiles.models import CandidateProfile

    gaps = {t for t, tp in topics.items() if tp["status"] == "gap"}
    strong = {t for t, tp in topics.items() if tp["status"] == "strong"}
    wanted = {d["tag"] for d in demand.get("items", []) if d["status"] != "confirmed"}
    best: dict[str, str] = {}
    for a in bundle.achievements:
        lvl = a.event_level.value if hasattr(a.event_level, "value") else str(a.event_level)
        if lvl not in LEVEL_ORDER:  # кубок работодателя на платформе (platform) — не соревнование ФСП
            continue
        if a.discipline not in best or LEVEL_ORDER.index(lvl) > LEVEL_ORDER.index(best[a.discipline]):
            best[a.discipline] = lvl
    peers: dict = {}
    peers_with: dict[str, int] = {}
    if category_id:
        ids = db.scalars(select(CandidateProfile.user_id).where(CandidateProfile.current_category_id == category_id,
                                                                CandidateProfile.visible_to_employers.is_(True))).all()
        peers = {"n": len(ids)}
        rows = db.execute(select(FspPassport.user_id, FspAchievement.discipline)
                          .join(FspAchievement, FspAchievement.passport_id == FspPassport.id)
                          .where(FspPassport.user_id.in_(ids), FspAchievement.event_level.in_(LEVEL_ORDER))
                          ).all() if ids else []
        by: dict[str, set] = defaultdict(set)
        for uid, disc in rows:
            by[disc].add(uid)
        peers_with = {k: len(v) for k, v in by.items()}
    out = []
    for disc in DIRECTION_DISCIPLINES.get(direction, ["product"]):
        tset = DISCIPLINE_TOPICS.get(disc, set())
        g = sorted(gaps & tset, key=_title)
        s = sorted(strong & tset, key=_title)
        w = sorted(wanted & tset, key=_title)
        rel = DISCIPLINE_RELEVANCE.get(disc, {}).get(direction, 0.3)
        score = rel + 0.4 * len(g) + 0.25 * len(w) + 0.1 * len(s)
        reasons = [DISCIPLINE_WHY[disc][0].upper() + DISCIPLINE_WHY[disc][1:] + "."]
        if g:
            reasons.append("Тренирует ваши пробелы: " + ", ".join(_title(t) for t in g) + ".")
        if w:
            reasons.append("Развивает навыки, которые требуют работодатели: " + ", ".join(_title(t) for t in w) + ".")
        if s:
            reasons.append("Опирается на ваши сильные темы: " + ", ".join(_title(t) for t in s[:4]) + ".")
        lvl = best.get(disc)
        item = {"discipline": disc, "title": DISCIPLINES.get(disc, disc), "score": round(score, 2),
                "reasons": reasons, "your_level": lvl, "your_level_title": LEVEL_RU.get(lvl) if lvl else None,
                "next_step": NEXT_STEP.get(lvl, NEXT_STEP[None])}
        if peers.get("n"):
            item["peers"] = {"category_size": peers["n"], "with_discipline": peers_with.get(disc, 0)}
        out.append(item)
    out.sort(key=lambda x: -x["score"])
    return out


def _latest_finished(db: Session, user_id: uuid.UUID) -> TestSession | None:
    return db.scalar(select(TestSession).where(TestSession.user_id == user_id,
                                               TestSession.status == TestSessionStatus.finished)
                     .order_by(TestSession.created_at.desc()).limit(1))


def build(db: Session, user_id: uuid.UUID, session_id: uuid.UUID | None = None) -> dict:
    """Обратная связь по сессии теста (по умолчанию — последней завершённой)."""
    from app.core.errors import api_error

    ts = None
    if session_id is not None:
        ts = db.get(TestSession, session_id)
        if ts is None or ts.user_id != user_id:
            raise api_error(404, "session_not_found", "Сессия теста не найдена")
        if ts.status != TestSessionStatus.finished:
            raise api_error(409, "session_not_finished", "Обратная связь появится после завершения теста")
    else:
        ts = _latest_finished(db, user_id)
    bundle = load_bundles(db, [user_id]).get(user_id)
    if bundle is None:
        raise api_error(404, "profile_not_found", "Профиль кандидата не найден")
    p = bundle.profile
    if ts is None and not bundle.skills_t1:
        return {"available": False, "message": "Карта навыков появится после первого теста."}
    direction = (ts.direction_id if ts else None) or p.current_direction_id
    grade = (ts.claimed_grade_id if ts else None) or p.current_grade_id
    topics = _topics_from_session(ts) if ts is not None else None
    source = "bank_session"
    # Демо-данные и заглушка: заданий банка в сессии нет — карта по фактам T1 (только если это тот же тест)
    if topics is None:
        source = "facts"
        topics = _topics_from_facts(bundle, direction)
    topics = _sort_topics(topics)
    by_tag = {t["tag"]: t for t in topics}
    er = ((ts.result or {}).get("engine_result") or {}) if ts else {}
    demand = _demand(db, direction, p.current_grade_id if p.current_direction_id == direction and p.current_grade_id
                     else grade, bundle, by_tag)
    scored = [t for t in topics if t["score"] is not None]
    summary = {
        "topics": len(topics), "strong": sum(1 for t in topics if t["status"] == "strong"),
        "ok": sum(1 for t in topics if t["status"] == "ok"), "gap": sum(1 for t in topics if t["status"] == "gap"),
        "pending": sum(1 for t in topics if t["status"] == "pending"),
        "best": [t["title"] for t in sorted(scored, key=lambda t: (-t["score"], -t["n"]))[:3] if t["status"] == "strong"],
        "weakest": [t["title"] for t in sorted(scored, key=lambda t: (t["score"], -t["n"]))[:3] if t["status"] == "gap"],
    }
    return {
        "available": True, "source": source,
        "session": {
            "id": str(ts.id) if ts else None, "direction": direction, "direction_title": DIRECTIONS.get(direction),
            "claimed_grade": grade, "grade_title": GRADES.get(grade), "theta": ts.theta if ts else None,
            "se": ts.theta_se if ts else None, "confirmed": er.get("confirmed") if ts else None,
            "finished_at": ts.finished_at.isoformat() if ts and ts.finished_at else None,
            "category_id": p.current_category_id,
            # прозрачный античит: кандидат видит ту же «достоверность результата» и причины, что и работодатель
            "integrity": summary_for_employer((er.get("details") or {}).get("integrity")),
        },
        "skill_map": {"topics": topics, "summary": summary,
                      "note": ("Темы — навыки заданий банка, сведённые к стеку справочника. Конкретные задания и "
                               "ключи не показываются. «Ожидаемо» — доля баллов, которую модель теста предсказывает "
                               "для вашего общего уровня θ: тема выше или ниже неё — ваша относительная сильная или "
                               "слабая сторона. Контрольные задания-канарейки в карту не входят.")},
        "demand": demand,
        "route": _route(ts, er, p, by_tag, demand),
        "competitions": _competitions(db, direction, p.current_category_id, bundle, by_tag, demand),
        "fsp_calendar_url": FSP_CALENDAR_URL,
    }
