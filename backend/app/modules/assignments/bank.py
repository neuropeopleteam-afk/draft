"""Подбор семейств банка под стек потребности или вакансии.

Тот же банк и та же автопроверка, что в тесте платформы и в кубке (app.cup.tasks: варианты по seed, ключи на
сервере, сверка ответа с ключом без исполнения кода). Отличие от кубка — семейства выбираются не случайно по
направлению, а по стек-тегам требований: сначала семейства, покрывающие теги стека (каждому тегу — хотя бы одно,
по кругу), затем добор семействами направления. Сложность сопоставимая: для грейда берутся семейства с целевым
грейдом, упорядоченные по близости априорной трудности к порогу грейда.

Банк меняется параллельно (поток И3) — здесь только публичный API assessment_bank, без правок банка.
"""
from __future__ import annotations

import random
import secrets

from assessment_bank import load_specs

from app.cup.tasks import AUTO_FORMATS
from app.modules.assessment.skill_map import to_stack_tags
from app.modules.catalog.seed_data import STACK
from app.modules.profiles.facts import GRADE_CUTS

N_MIN, N_MAX = 3, 5


def family_tags(spec) -> list[str]:
    return to_stack_tags(spec.direction, spec.skills)


def _difficulty(spec) -> float:
    pd = spec.prior_difficulty
    return float(getattr(pd, "b", 0.0) or 0.0)


def _pool(direction: str, grade: str) -> list:
    """Автопроверяемые неканареечные семейства направления и общего блока, подходящие грейду."""
    specs = load_specs()
    pool = [s for s in specs.values() if s.direction in (direction, "common") and s.format in AUTO_FORMATS
            and not s.canary]
    fit = [s for s in pool if grade in s.target_grades]
    return fit if len(fit) >= N_MIN else pool


def coverage_for(direction: str, grade: str, stack_tags: list[str]) -> dict:
    """Какие теги стека банк может проверить (честно показываем работодателю, чего в банке нет)."""
    pool = _pool(direction, grade)
    have = {t for s in pool for t in family_tags(s)}
    covered = [t for t in stack_tags if t in have]
    return {"covered": covered, "missing": [t for t in stack_tags if t not in have]}


def pick(direction: str, grade: str, stack_tags: list[str], n: int, seed: int | None = None) -> list[dict]:
    """n семейств под стек: [{family_id, title, tags, difficulty, format}] — без ключей и вариантов."""
    n = max(N_MIN, min(N_MAX, n))
    rnd = random.Random(seed if seed is not None else secrets.randbits(32))
    cut = GRADE_CUTS.get(grade, 0.0)
    pool = sorted(_pool(direction, grade), key=lambda s: (abs(_difficulty(s) - cut), s.family_id))
    wanted = [t for t in stack_tags if t]
    chosen: list = []

    def take(spec) -> None:
        if spec not in chosen and len(chosen) < n:
            chosen.append(spec)

    # 1. по кругу: каждому тегу стека — ближайшее по сложности семейство (с небольшим перемешиванием равных)
    by_tag = {t: [s for s in pool if t in family_tags(s)] for t in wanted}
    for lst in by_tag.values():
        head = lst[:3]
        rnd.shuffle(head)
        lst[:3] = head
    rounds = 0
    while len(chosen) < n and rounds < n and any(by_tag.values()):
        for t in wanted:
            lst = by_tag.get(t) or []
            while lst and lst[0] in chosen:
                lst.pop(0)
            if lst:
                take(lst.pop(0))
        rounds += 1
    # 2. добор: семейства направления, ещё не выбранные, ближайшие к порогу грейда
    for s in pool:
        if len(chosen) >= n:
            break
        if s.direction == direction:
            take(s)
    for s in pool:
        if len(chosen) >= n:
            break
        take(s)
    return [describe(s) for s in chosen]


def describe(spec) -> dict:
    tags = family_tags(spec)
    return {"family_id": spec.family_id, "title": spec.title, "tags": tags,
            "tag_titles": [STACK.get(t, (t,))[0] for t in tags], "difficulty": round(_difficulty(spec), 2),
            "format": spec.format, "language": spec.language, "time_limit_s": spec.time_limit_s}


def families_public(fams: list[dict]) -> list[dict]:
    """Описание набора для работодателя и кандидата: без family_id (чтобы не искать варианты вне платформы)."""
    return [{k: f[k] for k in ("title", "tags", "tag_titles", "difficulty", "format", "language") if k in f}
            for f in fams]
