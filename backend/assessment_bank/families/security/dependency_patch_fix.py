"""Фиктивное уведомление о зависимости: минимальное исправленное совместимое обновление."""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, fix_variant

FAMILY_ID = "security.supply.dependency_patch_fix"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    package = rng.choice(["demo-parser", "demo-template", "demo-codec", "demo-export"])
    major, minor = rng.randint(2, 5), rng.randint(2, 8)
    fixed_patch = rng.randint(10, 16)
    branch = (major, minor)
    versions = [f"{major}.{minor}.{p}" for p in [8, 9, fixed_patch, fixed_patch + 1]]
    versions += [f"{major - 1}.{minor}.20", f"{major}.{minor + 1}.1"]
    rng.shuffle(versions)
    head = f"""BRANCH = {branch!r}
MIN_SAFE = {fixed_patch}

def parse_version(value):
    return tuple(int(x) for x in value.split('.'))

"""
    good = """def select_version(versions):
    parsed = [parse_version(v) for v in versions]
    safe = [v for v in parsed if v[:2] == BRANCH and v[2] >= MIN_SAFE]
    return '.'.join(map(str, min(safe))) if safe else None"""
    lex = """def select_version(versions):
    compatible = [v for v in versions if parse_version(v)[:2] == BRANCH]
    chosen = max(compatible) if compatible else None
    return chosen"""
    incompatible = good.replace("v[:2] == BRANCH and v[2] >= MIN_SAFE", "v[2] >= MIN_SAFE")
    fallback = good.replace("if safe else None", "if safe else '.'.join(map(str, min(parsed)))")
    test = f"""assert select_version({versions!r}) == {f'{major}.{minor}.{fixed_patch}'!r}
assert select_version([{f'{major}.{minor}.8'!r}, {f'{major}.{minor}.9'!r}]) is None
assert select_version([{f'{major - 1}.{minor}.20'!r}, {f'{major}.{minor + 1}.20'!r}]) is None
assert select_version([]) is None"""
    stem = (f"{ctx.capitalize()}: фиктивная зависимость `{package}`, уведомление учебное, "
            f"не про реальный пакет. В ветке {major}.{minor}.x все версии до patch={fixed_patch} "
            f"считаются уязвимыми, начиная с {fixed_patch} исправлены. Только эта ветка прошла "
            "проверку совместимости. По политике выбирается минимальная исправленная версия "
            "ветки, при отсутствии подходящей — None и блокировка выпуска. "
            f"Версии имеют ровно три целых компонента, без pre-release: {versions!r}. "
            "Выберите исправление сравнения; порядок входного списка не важен.")
    return fix_variant(
        FAMILY_ID, seed, rng, stem=stem, buggy=head + lex, correct=head + good,
        distractors=[head + lex, head + incompatible, head + fallback],
        test=test, context=ctx, defect="unsafe_dependency_selection",
        why="Версии сравниваются как тройки чисел, не строки. Фильтруются совместимая ветка "
            "и исправленный диапазон, отсутствие версии не ведёт к небезопасному fallback. "
            "После выбора обновляются lock-файл и транзитивные зависимости, выполняются "
            "регрессионные тесты и повторная проверка уведомления.",
        params={"source_urls": [SOURCES["coding"]], "synthetic_advisory": True, "versions": versions},
    )
