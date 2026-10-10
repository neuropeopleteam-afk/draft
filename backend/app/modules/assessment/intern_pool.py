"""Состав теста на грейд «Стажёр»: сопоставление семейств банка на стороне платформы (банк не меняется).

Правило:
* **основной набор** — семейства, у которых в ``target_grades`` есть ``intern`` (их добавляет поток банка;
  появятся — попадут в тест автоматически, без правок здесь);
* **запасной набор** — семейства для Junior закрытых форматов (find_bug, predict_output, choose_fix, mcq_concept) со
  средней трудностью не выше ``FALLBACK_MAX_B``: пока лёгких семейств в банке нет, тест на Стажёра идёт по самым
  простым заданиям Junior. Адаптивный выбор по информации у порога Стажёра сам предпочитает самые лёгкие из них;
  семейства у порога Junior нужны, чтобы заметить «уверенно выше — можно идти на Junior».
* Канарейки остаются (они не входят в θ), открытые форматы (open_answer, open_book_3step) исключаются:
  для начинающего они длинные и тянут тест за лимит времени.

Ротация субпулов для Стажёра выключена (``subpool=None``): лёгких семейств в банке пока мало, половины пула не хватило
бы на 8 заданий; повторная попытка не получает семейства прошлых попыток (И26: ни в основной части, ни в
дотестировании; лёгких мало — запасной путь LRU, виденные давнее всего, с новым вариантом).
Список семейств, которые нужны банку для полноценного теста Стажёра, — внутренний отчёт разработки
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from assessment_bank.psychometrics import PoolItem

OPEN_FORMATS = ("open_answer", "open_book_3step")
FALLBACK_MAX_B = 0.3        # средняя трудность семейства (предкалибровка) для запасного набора
MIN_SCORED = 8              # минимум оцениваемых семейств в пуле направления, иначе запасной набор расширяется


def _mean_b(item: PoolItem) -> float:
    return float(np.mean(item.b))


def intern_family_ids(pool: list[PoolItem] | tuple[PoolItem, ...], direction: str) -> set[str]:
    """Семейства, из которых строится тест на Стажёра для направления (общий блок + направление)."""
    scoped = [i for i in pool if not i.canary and i.block in ("common", direction)]
    primary = {i.family_id for i in scoped if "intern" in i.grades}
    closed_junior = [i for i in scoped if "junior" in i.grades and i.format not in OPEN_FORMATS]
    fallback = {i.family_id for i in closed_junior if _mean_b(i) <= FALLBACK_MAX_B}
    chosen = primary | fallback
    if len(chosen) < MIN_SCORED:  # банк сильно изменился: добираем самые лёгкие закрытые семейства Junior
        for i in sorted(closed_junior, key=_mean_b):
            chosen.add(i.family_id)
            if len(chosen) >= MIN_SCORED:
                break
    return chosen


def intern_exclusions(pool: list[PoolItem] | tuple[PoolItem, ...], direction: str) -> tuple[str, ...]:
    """Семейства, которые НЕ показываются в тесте на Стажёра (аргумент ``exclude`` у CATSession)."""
    keep = intern_family_ids(pool, direction)
    return tuple(sorted(i.family_id for i in pool if not i.canary and i.block in ("common", direction)
                        and i.family_id not in keep))


@lru_cache(maxsize=8)
def intern_pool_summary(direction: str) -> dict:
    """Для /validation и отчёта: сколько семейств и какие в тесте Стажёра по направлению."""
    from app.modules.assessment.bank_engine import _pool

    pool = _pool(1)
    keep = intern_family_ids(pool, direction)
    items = sorted((i for i in pool if i.family_id in keep), key=lambda i: (i.block != "common", _mean_b(i)))
    return {
        "direction": direction,
        "n_common": sum(1 for i in items if i.block == "common"),
        "n_direction": sum(1 for i in items if i.block != "common"),
        "n_primary": sum(1 for i in items if "intern" in i.grades),
        "families": [{"family_id": i.family_id, "block": i.block, "format": i.format, "b": round(_mean_b(i), 2),
                      "time_limit_s": i.time_limit_s, "grades": list(i.grades)} for i in items],
    }
