"""Подтверждённый фреймворк подтверждает базовый язык (W1, флаг MATCH_IMPLIED, по умолчанию включён).

Задание теста по FastAPI или Django решается только кодом на Python, по React или Vue — кодом на JavaScript, по
Spring — на Java, по PostgreSQL или ClickHouse — запросами SQL, по Docker и Kubernetes — командами Linux. Поэтому навык
фреймворка, подтверждённый заданиями теста (T1, доля ≥ 0,5), засчитывается как подтверждение базового языка при
расчёте покрытия обязательных навыков потребности (ranking.stack_part, must_have.coverage). Обратного вывода нет:
Python не подтверждает FastAPI.

Балл производного подтверждения — балл фреймворка × ``IMPLIED_FACTOR`` (0,9): прямое подтверждение языка всегда не
хуже производного. В объяснении подборки такой навык подписан «подтверждён через <фреймворк>» (T1, производное).

Связки — только однозначные: язык, без которого фреймворк не используется. TypeScript из React/Vue не выводится
(на React и Vue пишут и на JavaScript), выводится только из Angular (Angular — только TypeScript).
"""
from __future__ import annotations

import os

from app.modules.profiles.facts import skill_confirmed

IMPLIED_FACTOR = 0.9

# фреймворк/инструмент → базовые навыки, которые он подтверждает
IMPLIES: dict[str, tuple[str, ...]] = {
    # Python
    "fastapi": ("python",), "django": ("python",), "flask": ("python",), "asyncio": ("python",),
    "pandas": ("python",), "numpy": ("python",), "scikit-learn": ("python",), "pytorch": ("python",),
    "pytest": ("python",), "airflow": ("python",),
    # JavaScript / TypeScript
    "react": ("javascript",), "vue": ("javascript",), "nextjs": ("javascript", "react"),
    "angular": ("typescript", "javascript"), "react-native": ("javascript",),
    # Java / Kotlin
    "spring": ("java",), "jetpack-compose": ("kotlin", "android"),
    # Swift
    "swiftui": ("swift", "ios"),
    # SQL
    "postgresql": ("sql",), "clickhouse": ("sql",), "greenplum": ("sql",), "dbt": ("sql",),
    # Linux
    "docker": ("linux",), "kubernetes": ("linux", "docker"), "helm": ("kubernetes",), "ansible": ("linux",),
}


def enabled() -> bool:
    return os.environ.get("MATCH_IMPLIED", "1").strip().lower() not in ("0", "false", "no", "off", "")


def implied_by(skills_t1: dict, tag: str):
    """Подтверждённый фреймворк, который подтверждает tag (лучший по баллу), или None. Прямое подтверждение tag
    сюда не входит — его проверяет вызывающий код."""
    if not enabled():
        return None
    best = None
    for src, targets in IMPLIES.items():
        if tag not in targets:
            continue
        f = skills_t1.get(src)
        if skill_confirmed(f) and (best is None or f.value.get("score", 0) > best[1].value.get("score", 0)):
            best = (src, f)
    return best


def implied_score(skills_t1: dict, tag: str) -> float:
    hit = implied_by(skills_t1, tag)
    return round(IMPLIED_FACTOR * float(hit[1].value.get("score", 0)), 3) if hit else 0.0
