"""Синтетический мир бенчмарка подбора со скрытой истиной (см. matching_bench.py).

Каждый кандидат состоит из двух частей, и они не смешиваются:

* ``Latent`` — истина, которую система не видит: направление, истинный уровень θ*, истинный грейд,
  набор реально освоенных навыков, «соревновательный талант» (от него зависит паспорт ФСП).
* ``Observed`` — то, что видят платформа и базовые линии:
  - T0, самоописание: заявленный грейд, заявленный стек, стаж, текст резюме. Оно шумное, у части кандидатов
    «раздутое» (грейд на ступень выше, лишние модные навыки, повтор ключевых слов) или «скромное»
    (грейд ниже, половина навыков не указана);
  - T1, тест: θ̂ = θ* + ε, ε ~ N(0, σθ), решение по грейду — функцией платформы ``engine.grade_decision``
    (при отказе — пересдача на ступень ниже, как подсказывает платформа); навыки — по ответам на задания,
    теги которых взяты из реального банка (``assessment_bank`` + ``skill_map``);
  - T2, паспорт ФСП: подтверждённые реестром достижения у части кандидатов; у остальных истории ФСП нет.

Потребность — тоже две части: спецификация (истина: направление, грейд, обязательные и желательные навыки)
и текст, который разбирает парсер платформы (``need_parser``). Ранжирование получает только результат разбора.

Bundle для ``ranking.score_candidate`` строится функцией ``build_bundle`` только из ``Observed``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import cached_property
from datetime import date, datetime, timezone
from decimal import Decimal
import math
from types import SimpleNamespace
import uuid

import numpy as np

from app.core.enums import EvidenceLevel, FactSource, FspEventLevel, WorkFormat
from app.modules.assessment.engine import GRADE_CUTS, grade_decision
from app.modules.assessment.skill_map import to_stack_tags
from app.modules.catalog.dictionary import STACK_ALIASES
from app.modules.catalog.seed_data import GRADE_LEVEL, GRADE_ORDER, STACK
from app.modules.fsp.models import FspAchievement
from app.modules.profiles.facts import Bundle, fsp_strength
from app.modules.profiles.models import CandidateFact, CandidateProfile

DIRS = ("backend", "frontend", "data_ml", "qa", "security")
GRADES = GRADE_ORDER  # все грейды платформы снизу вверх (со Стажёром)
NEED_GRADE_P = (0.08, 0.28, 0.42, 0.22)  # доля потребностей по грейдам: стажировок мало, Middle больше всего
FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # дата «теста» в синтетике: от неё не зависит ничего

# Популярность навыка в направлении: базовая вероятность, что кандидат им реально владеет.
# Из того же распределения работодатели выбирают требования (просят распространённое).
POPULARITY: dict[str, dict[str, float]] = {
    "backend": {"python": .8, "postgresql": .7, "rest-api": .7, "git": .8, "sql": .7, "docker": .6, "linux": .6,
                "http": .6, "redis": .45, "fastapi": .4, "django": .35, "asyncio": .35, "algorithms": .4,
                "kafka": .25, "rabbitmq": .25, "flask": .25, "grpc": .15, "go": .15, "java": .15},
    "frontend": {"javascript": .9, "html-css": .85, "typescript": .7, "react": .7, "git": .8, "http": .5,
                 "state-management": .45, "vite-webpack": .45, "tailwind": .35, "nextjs": .3,
                 "frontend-testing": .3, "vue": .25, "algorithms": .25, "a11y": .2, "angular": .15},
    "data_ml": {"python": .9, "pandas": .8, "sql": .75, "numpy": .75, "git": .7, "scikit-learn": .6,
                "statistics": .6, "linux": .5, "docker": .4, "pytorch": .35, "algorithms": .35, "airflow": .25,
                "nlp": .25, "spark": .2, "clickhouse": .2, "cv": .2, "mlops": .2},
    "qa": {"test-design": .8, "manual-testing": .7, "api-testing": .6, "git": .6, "sql": .55, "http": .5,
           "linux": .45, "python": .45, "pytest": .4, "selenium": .35, "ci-cd": .35, "playwright": .3,
           "allure": .3, "docker": .3, "load-testing": .2},
    "security": {"linux": .8, "owasp": .7, "network-security": .65, "http": .6, "python": .55, "git": .5,
                 "pentest": .45, "burp-suite": .45, "sql": .4, "ctf": .4, "cryptography": .35, "siem-soc": .35,
                 "docker": .35, "reverse-engineering": .2, "forensics": .2},
}
# Как навык пишут в тексте потребности (форма, которую понимает работодатель)
NEED_PHRASE = {
    "rest-api": "REST API", "html-css": "HTML/CSS", "state-management": "Redux или Zustand",
    "vite-webpack": "Webpack или Vite", "frontend-testing": "тесты на Jest", "a11y": "доступность (a11y)",
    "statistics": "статистика и A/B-тесты", "cv": "компьютерное зрение", "test-design": "тест-дизайн",
    "manual-testing": "ручное тестирование", "api-testing": "тестирование API",
    "load-testing": "нагрузочное тестирование", "owasp": "OWASP Top 10", "pentest": "пентест веб-приложений",
    "network-security": "сетевая безопасность", "cryptography": "криптография", "siem-soc": "SIEM",
    "reverse-engineering": "реверс-инжиниринг", "forensics": "форензика", "algorithms": "алгоритмы и структуры данных",
    "http": "HTTP", "ci-cd": "CI/CD",
}
ROLE = {
    "backend": ["бэкенд-разработчик", "backend-разработчик", "разработчик серверной части"],
    "frontend": ["фронтенд-разработчик", "frontend-разработчик", "разработчик клиентской части"],
    "data_ml": ["Data Scientist", "ML-инженер", "аналитик данных"],
    "qa": ["QA-инженер", "тестировщик", "инженер по автотестам"],
    "security": ["специалист по информационной безопасности", "инженер по кибербезопасности", "AppSec-инженер"],
}
PROJECT = {
    "backend": ["Делал API для интернет-магазина и платёжных сервисов.", "Поддерживал микросервисы доставки.",
                "Писал внутренние сервисы и интеграции."],
    "frontend": ["Делал личный кабинет и витрину магазина.", "Верстал и поддерживал админ-панель.",
                 "Разрабатывал SPA для банка."],
    "data_ml": ["Строил модели оттока и рекомендации.", "Готовил отчёты и прогнозы спроса.",
                "Обучал модели классификации текстов."],
    "qa": ["Тестировал мобильное приложение и веб-кабинет.", "Писал тест-кейсы и автотесты для API.",
           "Отвечал за регресс перед релизами."],
    "security": ["Проводил аудит веб-приложений.", "Разбирал инциденты в SOC.", "Участвовал в CTF и багбаунти."],
}
DISCIPLINE_BY_DIR = {"backend": (("algorithmic", .5), ("product", .5)), "frontend": (("product", .8), ("algorithmic", .2)),
                     "data_ml": (("algorithmic", .7), ("product", .3)), "qa": (("product", .8), ("algorithmic", .2)),
                     "security": (("security", .8), ("algorithmic", .2))}
EVENT_NAME = {"school": "Школьный этап олимпиады", "regional": "Региональные соревнования ФСП",
              "interregional": "Межрегиональный кубок ФСП", "national": "Чемпионат России ФСП",
              "international": "Международные соревнования ФСП"}


@dataclass
class BenchConfig:
    """Все параметры синтетики. Значения по умолчанию — основной прогон; меняются только явно (CLI, анализ
    чувствительности). Пишутся в отчёт целиком."""

    seed: int = 20261006
    n_needs: int = 200
    n_candidates: int = 2000
    # T1: погрешность θ̂ = RMSE адаптивного теста платформы в симуляции на банке 128 семейств
    # (report.json → simulation.mean.rmse = 0,48); SE, которую сообщает тест, — около цели остановки 0,35
    theta_sigma: float = 0.48
    se_reported: float = 0.40
    items_mean: float = 14.8  # среднее число заданий в сессии (симуляция теста)
    common_share: float = 0.4  # доля общего блока в сессии (CATConfig.common_share)
    guess: float = 0.2  # угадывание в задании с выбором
    known_bonus: float = 0.3  # задание по освоенному навыку: сдвиг θ при ответе
    unknown_penalty: float = -1.2  # задание по неосвоенному навыку
    # T0: доли типов самоописания
    share_inflated: float = 0.20
    share_modest: float = 0.15
    inflate_all: bool = False  # «раздутые» дописывают все навыки направления (стратегия «знаю всё»)
    # T2: P(есть паспорт ФСП) = σ(fsp_base + fsp_slope·талант); талант = 0,8·θ* + N(0, 0,6), если fsp_informative
    fsp_base: float = -1.3
    fsp_slope: float = 0.9
    fsp_informative: bool = True
    # Истина: правила релевантности (true_relevance)
    truth: str = "capable"  # capable — может выполнять работу грейда; strict — только точный грейд
    cov_full: float = 0.75
    cov_min: float = 0.5
    min_relevant_per_need: int = 3

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Latent:
    """Истина о кандидате. Не передаётся ни в ранжирование, ни в базовые линии."""

    direction: str
    theta: float
    true_grade: str | None  # None — ниже нижнего порога (Стажёра)
    known: frozenset[str]
    talent: float
    persona: str  # honest | inflated | modest


@dataclass
class Observed:
    """То, что видит система: T0, T1, T2."""

    idx: int
    public_ref: str
    direction_declared: str
    grade_declared: str
    stack_declared: list[str]
    experience_years: float
    work_format: str
    resume_text: str
    # T1 (последняя сессия; категория — только при подтверждении грейда)
    category_grade: str | None
    test: dict | None
    skills_t1: dict[str, dict] = field(default_factory=dict)
    sessions: int = 0
    # T2
    achievements: list[dict] = field(default_factory=list)


@dataclass
class Candidate:
    latent: Latent
    obs: Observed


@dataclass
class NeedSpec:
    """Истина о потребности (что работодатель на самом деле хочет)."""

    idx: int
    direction: str
    grade: str
    required: list[str]
    desired: list[str]
    work_format: str | None
    text: str


@dataclass
class World:
    config: BenchConfig
    candidates: list[Candidate]
    needs: list[NeedSpec]
    rel: np.ndarray  # (n_needs, n_candidates) — истинная релевантность 0..3
    bank_coverage: dict[str, list[str]]
    resampled_needs: int = 0


# ---------------------------------------------------------------- истина

def true_grade(theta: float) -> str | None:
    g = None
    for name in GRADES:
        if theta >= GRADE_CUTS[name]:
            g = name
    return g


def true_relevance(need: NeedSpec, lat: Latent, cfg: BenchConfig) -> int:
    """Истинная пригодность кандидата для потребности, 0..3 (релевантен — ≥ 2). Видит только Latent и NeedSpec.

    Основное правило (cfg.truth = "capable") — «может выполнять работу этого грейда»:
    * направление не совпадает → 0;
    * истинный грейд (θ* и пороги платформы −1 / 0 / 1; ниже порога Junior — ступень 0) равен запрошенному или
      на ступень выше → 2; на ступень ниже или на две выше (переквалифицирован) → 1; на две ниже → 0;
    * может выполнять работу и реально владеет ≥ 75 % обязательных навыков → 3;
    * владеет < 50 % обязательных навыков → не выше 1.
    Строгое правило (cfg.truth = "strict", для анализа чувствительности): грейд совпадает → 2, соседний в любую
    сторону → 1, через ступень → 0; 3 — только при точном грейде.
    """
    if lat.direction != need.direction:
        return 0
    have = GRADE_LEVEL[lat.true_grade] if lat.true_grade else GRADE_LEVEL[GRADES[0]] - 1
    diff = have - GRADE_LEVEL[need.grade]
    if cfg.truth == "strict":
        rel = {0: 2, 1: 1, -1: 1}.get(diff, 0)
        top = diff == 0
    else:
        rel = 2 if diff in (0, 1) else 1 if diff in (-1, 2) else 0
        top = diff in (0, 1)
    cov = (sum(1 for t in need.required if t in lat.known) / len(need.required)) if need.required else 1.0
    if top and cov >= cfg.cov_full:
        rel = 3
    if cov < cfg.cov_min:
        rel = min(rel, 1)
    return rel


# ---------------------------------------------------------------- банк: какие навыки тест вообще видит

def bank_blocks() -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Блоки банка: направление → [(family_id, исходные навыки)], 'common' — общий блок; канарейки исключены."""
    from assessment_bank import load_specs

    out: dict[str, list] = {}
    for fid, s in sorted(load_specs().items()):
        if getattr(s, "canary", False):
            continue
        d = getattr(s.direction, "value", s.direction)
        out.setdefault(str(d), []).append((fid, tuple(s.skills)))
    return out


def coverage(blocks: dict) -> dict[str, list[str]]:
    """Стек-теги, которые задания банка могут подтвердить в тесте направления."""
    out = {}
    for d in DIRS:
        tags: set[str] = set()
        for _, skills in blocks.get(d, []) + blocks.get("common", []):
            tags.update(to_stack_tags(d, list(skills)))
        out[d] = sorted(tags)
    return out


# ---------------------------------------------------------------- генерация

def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _phrase(tag: str) -> str:
    return NEED_PHRASE.get(tag) or STACK[tag][0]


def _resume_phrase(tag: str, rng: np.random.Generator) -> str:
    """В резюме навык пишут по-разному: обычно названием, иногда синонимом из словаря."""
    aliases = [a.strip() for a in STACK_ALIASES.get(tag, []) if len(a.strip()) > 2]
    if aliases and rng.random() < 0.3:
        return str(aliases[int(rng.integers(len(aliases)))])
    return STACK[tag][0]


def _weighted_sample(rng: np.random.Generator, items: list[str], weights: list[float], k: int) -> list[str]:
    w = np.asarray(weights, dtype=float)
    k = min(k, len(items))
    idx = rng.choice(len(items), size=k, replace=False, p=w / w.sum())
    return [items[i] for i in idx]


def _shift_grade(g: str, step: int) -> str:
    i = min(max(GRADES.index(g) + step, 0), len(GRADES) - 1)
    return GRADES[i]


def _run_test(lat: Latent, claimed: str, cfg: BenchConfig, blocks: dict, rng: np.random.Generator) -> dict:
    """Одна сессия теста: θ̂ с погрешностью, решение платформы по грейду, ответы на задания с тегами банка."""
    theta_hat = float(np.clip(lat.theta + rng.normal(0, cfg.theta_sigma), -3.5, 3.5))
    se = float(np.clip(cfg.se_reported + rng.normal(0, 0.04), 0.3, 0.55))
    dec = grade_decision(theta_hat, se, claimed)
    n_items = int(np.clip(round(rng.normal(cfg.items_mean, 1.5)), 8, 16))
    n_common = int(round(cfg.common_share * n_items))
    fams: list[tuple[str, ...]] = []
    for blk, n in (("common", n_common), (lat.direction, n_items - n_common)):
        pool = blocks.get(blk, [])
        if pool:
            pick = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
            fams += [pool[i][1] for i in pick]
    skills: dict[str, dict] = {}
    correct = 0
    for fam_skills in fams:
        tags = to_stack_tags(lat.direction, list(fam_skills))
        if not tags:
            continue
        known_frac = sum(1 for t in tags if t in lat.known) / len(tags)
        shift = cfg.known_bonus if known_frac >= 0.5 else cfg.unknown_penalty
        b = lat.theta + rng.normal(0, 0.5)  # адаптивный тест подбирает задания около текущей оценки
        p = cfg.guess + (1 - cfg.guess) * _sig(1.7 * (lat.theta + shift - b))
        x = 1.0 if rng.random() < p else 0.0
        correct += int(x)
        for t in tags:
            d = skills.setdefault(t, {"correct": 0.0, "total": 0})
            d["total"] += 1
            d["correct"] += x
    for d in skills.values():
        d["score"] = round(d["correct"] / d["total"], 2) if d["total"] else 0.0
    return {"theta": round(theta_hat, 3), "se": round(se, 3), "claimed": claimed, "confirmed": dec["confirmed"],
            "retake_lower": dec["retake_lower"], "correct": correct, "answered": len(fams), "skills": skills}


def _make_candidate(i: int, cfg: BenchConfig, blocks: dict) -> Candidate:
    # Свои потоки случайности у каждого кандидата и у каждой части (истина, T0, тест, ФСП): при изменении одного
    # параметра (например, σθ) остальное у кандидата не меняется — варианты чувствительности сравнимы попарно
    rng, r0, rt, rf = (np.random.default_rng(x) for x in np.random.SeedSequence([cfg.seed, 1, i]).spawn(4))
    d = DIRS[int(rng.integers(len(DIRS)))]
    theta = float(rng.normal(0, 1))
    pop = POPULARITY[d]
    known = {t for t, p in pop.items() if rng.random() < float(np.clip(p * (0.75 + 0.2 * theta), 0.02, 0.97))}
    if not known:
        known = {max(pop, key=pop.get)}
    talent = (0.8 * theta + float(rng.normal(0, 0.6))) if cfg.fsp_informative else float(rng.normal(0, 1))
    u = r0.random()
    persona = "inflated" if u < cfg.share_inflated else "modest" if u < cfg.share_inflated + cfg.share_modest else "honest"
    lat = Latent(direction=d, theta=round(theta, 3), true_grade=true_grade(theta), known=frozenset(known),
                 talent=round(talent, 3), persona=persona)

    # T0 — самоописание
    base = lat.true_grade or GRADES[0]
    others = [t for t in pop if t not in known]
    if persona == "inflated":
        g_decl = _shift_grade(base, +1 if lat.true_grade else +2)
        n_extra = len(others) if cfg.inflate_all else int(r0.integers(4, 9))
        extra = _weighted_sample(r0, others, [pop[t] for t in others], n_extra) if others else []
        stack = sorted(known | set(extra))
        years = max(0.0, 1.5 + 2.2 * (theta + 1) + r0.normal(0, 1)) + 3
    elif persona == "modest":
        g_decl = _shift_grade(base, -1) if r0.random() < 0.6 else base
        stack = [t for t in sorted(known) if r0.random() < 0.5] or sorted(known)[:1]
        years = max(0.0, 1.5 + 2.2 * (theta + 1) + r0.normal(0, 1) - 1)
    else:
        u2 = r0.random()
        g_decl = _shift_grade(base, +1) if u2 < 0.15 else _shift_grade(base, -1) if u2 < 0.30 else base
        stack = sorted({t for t in sorted(known) if r0.random() < 0.85} | {t for t in others if r0.random() < 0.06})
        stack = stack or sorted(known)[:1]
        years = max(0.0, 1.5 + 2.2 * (theta + 1) + r0.normal(0, 1))
    years = round(float(years), 1)
    role = ROLE[d][int(r0.integers(len(ROLE[d])))]
    words = [_resume_phrase(t, r0) for t in r0.permutation(stack)]
    proj = PROJECT[d][int(r0.integers(len(PROJECT[d])))]
    if persona == "inflated":
        text = (f"{role.capitalize()}, {g_decl.capitalize()}. Эксперт. Опыт {years:g} лет. Ключевые навыки: "
                f"{', '.join(words)}. Также владею: {', '.join(r0.permutation(words))}. {proj}")
    elif persona == "modest":
        text = f"{role.capitalize()}. Работал с {', '.join(words)}."
    else:
        text = f"{role.capitalize()}, {g_decl}. Опыт {years:g} лет. Стек: {', '.join(words)}. {proj}"
    wf = ("office", "hybrid", "remote", "any")[int(r0.integers(4))]

    # T1 — тест на заявленный грейд, при отказе — пересдача ступенью ниже (не больше одной)
    sess = _run_test(lat, g_decl, cfg, blocks, rt)
    n_sess = 1
    if not sess["confirmed"] and sess["retake_lower"]:
        sess = _run_test(lat, sess["retake_lower"], cfg, blocks, rt)
        n_sess = 2
    cat_grade = sess["claimed"] if sess["confirmed"] else None

    # T2 — паспорт ФСП
    ach: list[dict] = []
    if rf.random() < _sig(cfg.fsp_base + cfg.fsp_slope * talent):
        for _ in range(1 + min(3, int(rf.poisson(0.6)))):
            c = talent + float(rf.normal(0, 0.5))
            lvl = ("international" if c > 2.4 else "national" if c > 1.6 else "interregional" if c > 0.8
                   else "regional" if c > 0 else "school")
            place = (1 if c > 1.8 else int(rf.integers(2, 4)) if c > 1.0 else int(rf.integers(4, 11)) if c > 0.2
                     else int(rf.integers(11, 41)))
            disc, wts = zip(*DISCIPLINE_BY_DIR[d], strict=True)
            ach.append({"discipline": str(rf.choice(disc, p=np.asarray(wts) / sum(wts))), "level": lvl,
                        "place": place, "year": int(rf.integers(2023, 2027)), "verified": True})
    if persona == "inflated" and rf.random() < 0.25:  # «значок из анкеты» без подтверждения реестром
        ach.append({"discipline": "product", "level": "national", "place": 1, "year": 2025, "verified": False})

    obs = Observed(idx=i, public_ref=f"B{int(rng.integers(16 ** 7)):07X}", direction_declared=d,
                   grade_declared=g_decl, stack_declared=stack, experience_years=years, work_format=wf,
                   resume_text=text, category_grade=cat_grade,
                   test={k: sess[k] for k in ("theta", "se", "claimed", "confirmed", "correct", "answered")}
                   if cat_grade else None,
                   skills_t1=sess["skills"] if cat_grade else {}, sessions=n_sess, achievements=ach)
    return Candidate(latent=lat, obs=obs)


def _need_text(d: str, g: str, req: list[str], des: list[str], wf: str | None, rng: np.random.Generator) -> str:
    role = ROLE[d][int(rng.integers(len(ROLE[d])))]
    r = ", ".join(_phrase(t) for t in req)
    s = ", ".join(_phrase(t) for t in des)
    fmt = {"remote": " Удалённо.", "hybrid": " Гибрид, Москва.", "office": " Офис в Казани.", None: ""}[wf]
    k = int(rng.integers(3))
    if k == 0:
        return f"Ищем {g} {role}: обязательно {r}." + (f" Будет плюсом {s}." if des else "") + fmt
    if k == 1:
        return f"{role[0].upper() + role[1:]} уровня {g}. Требования: {r}." + (f" Желательно: {s}." if des else "") + fmt
    return f"Вакансия «{role}», грейд {g}. Нужно уверенно знать {r}" + (f"; плюсом будет {s}." if des else ".") + fmt


def _make_need(i: int, rng: np.random.Generator) -> NeedSpec:
    d = DIRS[i % len(DIRS)]
    g = str(rng.choice(GRADES, p=list(NEED_GRADE_P)))
    pop = POPULARITY[d]
    tags = list(pop)
    req = _weighted_sample(rng, tags, [pop[t] for t in tags], int(rng.integers(2, 5)))
    rest = [t for t in tags if t not in req]
    des = _weighted_sample(rng, rest, [pop[t] for t in rest], int(rng.integers(0, 3)))
    wf = [None, "remote", "hybrid", "office"][int(rng.integers(4))]
    return NeedSpec(idx=i, direction=d, grade=g, required=req, desired=des, work_format=wf,
                    text=_need_text(d, g, req, des, wf, rng))


def generate(cfg: BenchConfig, blocks: dict | None = None) -> World:
    """Детерминированно по cfg.seed: у каждого кандидата и каждой потребности свой поток случайности."""
    blocks = blocks if blocks is not None else bank_blocks()
    cands = [_make_candidate(i, cfg, blocks) for i in range(cfg.n_candidates)]
    needs, rows, resampled = [], [], 0
    for i in range(cfg.n_needs):
        rn = np.random.default_rng(np.random.SeedSequence([cfg.seed, 2, i]))
        for _ in range(50):
            n = _make_need(i, rn)
            row = [true_relevance(n, c.latent, cfg) for c in cands]
            if sum(1 for r in row if r >= 2) >= cfg.min_relevant_per_need:
                break
            resampled += 1
        needs.append(n)
        rows.append(row)
    return World(config=cfg, candidates=cands, needs=needs, rel=np.asarray(rows, dtype=np.int8),
                 bank_coverage=coverage(blocks), resampled_needs=resampled)


# ---------------------------------------------------------------- Bundle только из наблюдаемого

class _Light(SimpleNamespace):
    """Лёгкий объект с теми же полями, что у модели SQLAlchemy (для скорости на сотнях тысяч пар)."""


class BenchBundle(Bundle):
    """Тот же Bundle продукта; заявленный стек и сила ФСП кешируются (данные в бенчмарке не меняются)."""

    @cached_property
    def stack_t0(self) -> set[str]:  # type: ignore[override]
        return {f.key for f in self.t0.get("stack", [])}

    @cached_property
    def fsp(self) -> float:  # type: ignore[override]
        return fsp_strength(self.achievements, self.profile.current_direction_id)


def _mk(cls, orm: bool, **kw):
    return cls(**kw) if orm else _Light(**kw)


def _fact(uid: uuid.UUID, kind: str, key: str, value: dict, level: EvidenceLevel, source: FactSource,
          orm: bool) -> CandidateFact:
    return _mk(CandidateFact, orm, user_id=uid, kind=kind, key=key, title=STACK.get(key, (key,))[0], value=value,
               evidence_level=level, source=source, created_at=FIXED_NOW)


def build_bundle(o: Observed, mode: str = "platform", orm: bool = False) -> Bundle:
    """Bundle для ranking.score_candidate. Вход — только Observed (истины здесь нет физически).

    mode:
    * ``platform`` — как в продукте: категория и навыки T1 из теста, T0 — только заявлено, ФСП — подтверждённое;
    * ``t0_only`` — абляция «без теста»: категория по заявленному грейду, заявленные навыки засчитываются как
      подтверждённые, теста и ФСП нет;
    * ``no_guard`` — абляция «без защиты от раздувания»: всё как в продукте, но заявленные (T0) навыки
      засчитываются как подтверждённые со счётом 1,0.
    orm=True — объекты моделей SQLAlchemy (без сессии); по умолчанию лёгкие объекты с теми же полями
    (тест test_matching_bench сверяет, что скор одинаков).
    """
    uid = uuid.UUID(int=o.idx + 1)
    if mode == "t0_only":
        d, g = o.direction_declared, o.grade_declared
    else:
        d, g = (o.direction_declared, o.category_grade) if o.category_grade else (None, None)
    p = _mk(CandidateProfile, orm, user_id=uid, public_ref=o.public_ref, current_direction_id=d, current_grade_id=g,
            current_category_id=f"{d}.{g}" if d and g else None, work_format=WorkFormat(o.work_format),
            experience_years=Decimal(str(o.experience_years)), about=o.resume_text, rating_score=None)
    b = BenchBundle(profile=p)
    for t in o.stack_declared:
        b.t0["stack"].append(_fact(uid, "stack", t, {}, EvidenceLevel.T0, FactSource.self_report, orm))
    if mode != "t0_only" and o.test:
        b.test = _fact(uid, "test_result", f"{d}.{g}", dict(o.test, grade=g), EvidenceLevel.T1, FactSource.test, orm)
        for t, s in o.skills_t1.items():
            b.skills_t1[t] = _fact(uid, "skill", t, dict(s), EvidenceLevel.T1, FactSource.test, orm)
    if mode in ("t0_only", "no_guard"):
        for t in o.stack_declared:
            cur = b.skills_t1.get(t)
            if cur is None or cur.value.get("score", 0) < 1.0:
                b.skills_t1[t] = _fact(uid, "skill", t, {"score": 1.0, "correct": 1, "total": 1},
                                       EvidenceLevel.T1, FactSource.test, orm)
    if mode != "t0_only":
        for a in o.achievements:
            b.achievements.append(_mk(
                FspAchievement, orm, discipline=a["discipline"], event_name=EVENT_NAME[a["level"]],
                event_level=FspEventLevel(a["level"]), event_date=date(a["year"], 5, 1), place=a["place"],
                verified=a["verified"],
                result_title="победитель" if a["place"] == 1 else "призёр" if a["place"] <= 3 else None))
    p.rating_score = b.strength() if p.current_category_id else None
    return b
