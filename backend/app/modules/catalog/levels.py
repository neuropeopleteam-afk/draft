"""Какие уровни видны в направлении: 4 базовых всегда, Lead и Principal — только за флагом и только по банку.

Решение владельца 10.10 (вариант Б): 6 уровней — Стажёр, Junior, Middle, Senior, Lead, Principal. Правило
организаторов FTT.4: уровень присваивается только по тесту, поэтому Lead/Principal в направлении видны, только если
в синхронизированном банке (``backend/assessment_bank``; ``tools/sync_bank.py`` кладёт туда лишь семейства, прошедшие
валидатор) у направления есть семейства этого уровня (``target_grades``):

* своих семейств направления — не меньше ``GRADES_EXT_MIN_OWN`` (по умолчанию 1);
* вместе с общим блоком (common) — не меньше ``GRADES_EXT_MIN_TOTAL`` (по умолчанию 3): тест берёт задания и из
  общего блока, а θ у порога Lead/Principal измеряют только трудные задания;
* Principal — только если виден Lead (уровни идут подряд, без пропусков).

Без флага ``GRADES_EXT_ENABLED`` функции возвращают прежние 4 уровня: ``seed_data.GRADE_ORDER`` и так без Lead/Principal.
Один источник для API (опрос, тест, разбор потребности), подборки, демо-данных, /criteria и /api/meta.
"""
from __future__ import annotations

from functools import lru_cache

from app.modules.catalog.seed_data import (ALL_GRADE_LEVEL, BASE_GRADE_ORDER, EXT_GRADE_ORDER, GRADE_ORDER,
                                           GRADES_EXT)


def enabled() -> bool:
    return GRADES_EXT


@lru_cache(maxsize=1)
def bank_ext_families() -> dict[str, dict[str, tuple[str, ...]]]:
    """Направление → уровень (lead/principal) → семейства банка с этим уровнем в target_grades (без канареек)."""
    out: dict[str, dict[str, list[str]]] = {}
    try:
        from assessment_bank import load_specs
        specs = load_specs()
    except Exception:  # noqa: BLE001 — без банка (заглушка тестов) Lead/Principal не видны нигде
        return {}
    for fid, s in specs.items():
        if getattr(s, "canary", False):
            continue
        for g in s.target_grades:
            if g in EXT_GRADE_ORDER:
                out.setdefault(s.direction, {}).setdefault(g, []).append(fid)
    return {d: {g: tuple(sorted(v)) for g, v in by.items()} for d, by in out.items()}


def ext_only(target_grades) -> bool:
    """Семейство только для Lead/Principal: target_grades непусты и целиком из {lead, principal}."""
    tg = set(target_grades or ())
    return bool(tg) and tg <= set(EXT_GRADE_ORDER)


def pool_specs(specs) -> list:
    """Спецификации для пула адаптивного теста: без флага GRADES_EXT_ENABLED семейства только Lead/Principal в пул не
    входят (банк может быть уже синхронизирован с ними, а шкала — из 4 уровней); с флагом — все."""
    specs = list(specs)
    return specs if GRADES_EXT else [s for s in specs if not ext_only(getattr(s, "target_grades", ()))]


def _preliminary_setting() -> bool:
    from app.core.config import get_settings

    return bool(get_settings().grades_ext_preliminary)


def _thresholds() -> tuple[int, int]:
    from app.core.config import get_settings

    s = get_settings()
    return max(0, int(s.grades_ext_min_own)), max(1, int(s.grades_ext_min_total))


def ext_supported(direction: str | None, grade: str) -> bool:
    """Есть ли в банке направления достаточно проверенных семейств уровня grade (lead | principal)."""
    if not GRADES_EXT or grade not in EXT_GRADE_ORDER or not direction:
        return False
    fam = bank_ext_families()
    own = len(fam.get(direction, {}).get(grade, ()))
    common = len(fam.get("common", {}).get(grade, ())) if direction != "common" else 0
    min_own, min_total = _thresholds()
    return own >= min_own and own + common >= min_total


@lru_cache(maxsize=64)
def _available(direction: str | None) -> tuple[str, ...]:
    if not GRADES_EXT:
        return GRADE_ORDER
    out = BASE_GRADE_ORDER
    for g in EXT_GRADE_ORDER:  # подряд: Principal — только при видимом Lead
        if not ext_supported(direction, g):
            break
        out += (g,)
    return out


def available_grades(direction: str | None) -> tuple[str, ...]:
    """Уровни, которые видны и присваиваются тестом в направлении (снизу вверх). Без флага — 4 прежних."""
    return _available(direction)


def top_grade(direction: str | None) -> str:
    return available_grades(direction)[-1]


def is_available(direction: str | None, grade: str | None) -> bool:
    return bool(grade) and grade in available_grades(direction)


def cap(direction: str | None, grade: str | None) -> str | None:
    """Уровень, не выше верхнего видимого в направлении (Lead в направлении без банка Lead → Senior)."""
    if not grade or grade not in ALL_GRADE_LEVEL:
        return grade
    top = top_grade(direction)
    return top if ALL_GRADE_LEVEL[grade] > ALL_GRADE_LEVEL[top] else grade


def directions_with(grade: str, directions: list[str] | tuple[str, ...]) -> list[str]:
    return [d for d in directions if is_available(d, grade)]


def status(directions: list[str] | tuple[str, ...] | None = None) -> dict:
    """Сводка для /api/meta, /criteria и docs: флаг, пороги, уровни и число семейств Lead/Principal по направлениям."""
    from app.modules.catalog.seed_data import DIRECTIONS

    dirs = list(directions or DIRECTIONS)
    fam = bank_ext_families()
    min_own, min_total = _thresholds()
    return {
        "enabled": GRADES_EXT,
        "grades": list(GRADE_ORDER),
        "min_own": min_own, "min_total": min_total,
        "preliminary": bool(GRADES_EXT and _preliminary_setting()),
        "common": {g: len(fam.get("common", {}).get(g, ())) for g in EXT_GRADE_ORDER},
        "by_direction": {d: {"grades": list(available_grades(d)),
                             "families": {g: len(fam.get(d, {}).get(g, ())) for g in EXT_GRADE_ORDER}}
                         for d in dirs},
    }


PRELIMINARY_TITLE = "предварительно"
PRELIMINARY_NOTE = ("Lead и Principal — по тесту, но предварительно: на симуляции тест различает эти уровни хуже, "
                    "чем Junior–Senior (модель, не люди; /validation, раздел «Lead и Principal»).")
SECOND_STAGE_NOTE = ("Уточнить уровень можно вторым этапом — короткой сессией из трудных заданий у границы "
                     "Senior/Lead и Lead/Principal.")


def ext_preliminary(grade: str | None) -> bool:
    """Lead/Principal с пометкой «предварительно» (флаг GRADES_EXT_ENABLED и GRADES_EXT_PRELIMINARY): уровень присвоен
    тестом, но точность различения Lead/Principal на симуляции ниже цели. Без флага — всегда False."""
    if not GRADES_EXT or grade not in EXT_GRADE_ORDER:
        return False
    from app.core.config import get_settings

    return bool(get_settings().grades_ext_preliminary)


def second_stage_available() -> bool:
    """Второй этап уточнения (флаг ASSESSMENT_TWO_STAGE_ENABLED — отдельная ветка; без неё настройки нет)."""
    from app.core.config import get_settings

    return bool(getattr(get_settings(), "assessment_two_stage_enabled", False))


def preliminary_info(grade: str | None) -> dict | None:
    """Пометка для результата теста, карточки и статуса грейда; None — пометки нет."""
    if not ext_preliminary(grade):
        return None
    return {"grade": grade, "title": PRELIMINARY_TITLE, "text": PRELIMINARY_NOTE,
            "second_stage": {"available": second_stage_available(), "text": SECOND_STAGE_NOTE}}


def reset_cache() -> None:
    """Для тестов: банк или пороги поменялись."""
    bank_ext_families.cache_clear()
    _available.cache_clear()
