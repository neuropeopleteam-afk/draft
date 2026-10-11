"""Добор ступенью выше при малом пуле точного уровня (Я12б, 11.10; алгоритм match-v1.3).

Зачем. На 414 реальных вакансиях hh.ru подборка брала кандидатов только точной категории (направление · уровень).
В демо-пуле (500 модельных кандидатов, модель, не люди) это в среднем 16 подтверждённых, и лучший из первых пяти
покрывал 36,8 % обязательных навыков при потолке пула 37,3 %: порядок внутри категории был почти наилучшим, не хватало
самих кандидатов. По правилам истины бенчмарка (bench_world.true_relevance) кандидат на ступень выше «может выполнять
работу этого уровня» (релевантность 2, при ≥ 75 % обязательных — 3), на ступень ниже — нет (1), поэтому добираем
только ступень выше.

Правило (без LLM и без подгонки весов; веса и балл match-v1 не меняются):
1. Действует, если у потребности есть уровень, работодатель не выбрал категории сам и в точной категории меньше
   MIN_EXACT (30) подтверждённых и предварительных кандидатов. При большом пуле (бенчмарк 200 × 2000 — около 100 на
   категорию) правило не включается, порядок прежний.
2. В пул добавляются подтверждённые кандидаты категории на ступень выше (без подтверждённого грейда — только точной).
3. Первые KEEP (2) места — лучшие кандидаты точного уровня по прежнему порядку (match-v1.2).
4. Дальше — прежний порядок (статус грейда → ядро роли → ярус обязательного) по общему пулу, и только при равном ярусе
   обязательного точный уровень идёт раньше: кандидат на ступень выше стоит выше точного, только если покрывает
   больше обязательного. В карточке — «грейд на ступень выше запрошенного».
Замер — tools/realdata/grade_above_bench.py → docs/validation/grade_above.json (бенчмарк со скрытой истиной в малом и
большом пуле, правило «не хуже») и tools/realdata/hh_plus.py match (покрытие на вакансиях hh.ru «до/после»).
Флаг MATCH_GRADE_ABOVE (по умолчанию «1»; «0» — прежний порядок match-v1.2).
"""
from __future__ import annotations

import os

FLAG = "MATCH_GRADE_ABOVE"
MIN_EXACT = 30  # в точной категории меньше — добор ступенью выше
KEEP = 2  # первые места — лучшие точного уровня
ALGORITHM = "match-v1.3"


def enabled() -> bool:
    return os.environ.get(FLAG, "1").strip().lower() not in ("0", "false", "no", "off", "")


def applies(recs: list[dict], filters: dict | None, on: bool | None = None) -> dict | None:
    """{"exact": …, "above": …} из рекомендованных категорий, если правило действует; иначе None."""
    on = enabled() if on is None else on
    if not on or (filters or {}).get("categories"):
        return None
    exact = next((r for r in recs if r.get("relation") == "exact"), None)
    above = next((r for r in recs if r.get("relation") == "above"), None)
    if not exact or not above or exact.get("count", 0) >= MIN_EXACT or not above.get("count"):
        return None
    return {"exact": exact, "above": above}


def above_category(req: dict) -> str | None:
    """Категория на ступень выше уровня потребности (для бенчмарка; в продукте — recommended_categories)."""
    from app.modules.catalog.seed_data import GRADE_LEVEL

    d, g = req.get("direction"), req.get("grade")
    if not d or not g or g not in GRADE_LEVEL:
        return None
    nxt = [x for x, lv in GRADE_LEVEL.items() if lv == GRADE_LEVEL[g] + 1]
    return f"{d}.{nxt[0]}" if nxt else None


def merge(head: list, ordered: list, keep: int = KEEP) -> list:
    """Первые keep мест — head (лучшие точного уровня по прежнему порядку), дальше — ordered без них."""
    top = head[:keep]
    ids = {id(x) for x in top}
    return top + [x for x in ordered if id(x) not in ids]


def text(info: dict) -> str:
    ex, ab = info["exact"], info["above"]
    return (f"В категории «{ex['title']}» {ex['count']} кандидатов с подтверждённым или предварительным грейдом — меньше "
            f"{MIN_EXACT}, поэтому подборка "
            f"добавила категорию на ступень выше — «{ab['title']}» ({ab['count']}). Первые {KEEP} места — лучшие "
            f"точного уровня; дальше кандидат уровнем выше стоит выше точного, только если покрывает больше "
            f"обязательного. Снять галочку с категории — подборка только точного уровня.")


def meta(info: dict | None, results: list[dict]) -> dict:
    if not info:
        return {"on": enabled(), "applied": False}
    above_id = info["above"]["id"]
    return {"on": True, "applied": True, "exact": info["exact"]["id"], "above": above_id,
            "exact_count": info["exact"]["count"], "above_count": info["above"]["count"], "min_exact": MIN_EXACT,
            "keep": KEEP, "in_top5": sum(1 for r in results[:5] if r.get("category_id") == above_id),
            "text": text(info)}
