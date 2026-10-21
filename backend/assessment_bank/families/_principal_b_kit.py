"""Помощники коротких семейств Principal потока ПБ-Б (data_ml, devops, data_eng; волна 10, 11.10).

Короткое задание Principal — расчётный mcq_concept на ≤ 7–8 минут: решение по технической стратегии
(какую альтернативу выбрать при ограничении, сколько ресурса заложить), ключ которого печатает программа-модель
по тем же числам, что видит кандидат (перебор сценариев, поминутная или понедельная имитация), а не формула
генератора.

* :func:`argmin_sep` — минимум с отрывом не меньше ``rel`` (иначе ``None``: ответ неоднозначен при округлении).
* :func:`search` — подбор чисел варианта: целевой ответ выбран по seed ДО подбора, числа перебираются, пока
  ответ модели не совпадёт с целью. Так ключ равновероятен среди альтернатив и не угадывается ни по форме
  подписи (самая длинная, «центральная»), ни по месту числа среди четырёх.
* :func:`trap_split` — для числового ответа: сколько ловушек будет больше ключа (0, 1 или 2 равновероятно),
  ловушки — из пулов завышающих и занижающих ошибок.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from assessment_bank.gen_utils import spread_pick


def argmin_sep(d: dict[str, float], rel: float = 0.04) -> str | None:
    """Ключ минимума, если второй по величине больше минимума хотя бы на ``rel`` от второго; иначе None."""
    if not d:
        return None
    s = sorted(d.values())
    if len(s) < 2:
        return min(d, key=d.get)
    return min(d, key=d.get) if s[1] - s[0] >= rel * abs(s[1]) else None


def search(rng: Any, sample: Callable[[Any], dict[str, Any]], accept: Callable[[dict[str, Any]], Any],
           tries: int = 20000) -> tuple[dict[str, Any], Any]:
    """Перебор ``sample(rng)``, пока ``accept(params)`` не вернёт не-None (детерминированно по rng)."""
    for _ in range(tries):
        p = sample(rng)
        r = accept(p)
        if r is not None:
            return p, r
    raise RuntimeError("не удалось подобрать параметры")


def trap_split(rng: Any, above: Sequence[str], below: Sequence[str], k: int = 3) -> list[str]:
    """k ловушек: n_above ∈ {0, 1, 2} равновероятно (не больше размера пулов) — из ``above``, остальные — из ``below``."""
    n_above = rng.choice([n for n in (0, 1, 2) if n <= len(above) and k - n <= len(below)])
    return sorted(rng.sample(sorted(above), n_above)) + sorted(rng.sample(sorted(below), k - n_above))


def distinct_ok(vals: Sequence[float], rel: float = 0.1, abs_min: float = 0.0) -> bool:
    """Все значения попарно различаются не меньше чем на rel от большего и на abs_min по модулю."""
    v = sorted(vals)
    return all(b - a >= max(rel * max(abs(b), 1e-9), abs_min) for a, b in zip(v, v[1:]))


def cap(s: str) -> str:
    """Первая буква — заглавная, остальные без изменений (str.capitalize портит «БД», «API», «GPU»)."""
    return s[:1].upper() + s[1:]


def pick_traps(rng: Any, key: float, cand: dict[str, float], n_above: int, *, rel: float = 0.12,
               abs_min: float = 2, k: int = 3) -> list[str] | None:
    """k ловушек из ``cand`` (имя → значение), из них ровно ``n_above`` больше ключа (n_above выбирается по seed
    ДО подбора чисел — иначе подбор смещает место ключа); значения ловушек и ключа попарно различимы.
    None — если при этих числах не набирается."""
    above = sorted(n for n, v in cand.items() if v > key)
    below = sorted(n for n, v in cand.items() if v < key)
    if len(above) < n_above or len(below) < k - n_above:
        return None
    rng.shuffle(above)
    rng.shuffle(below)
    # варианты — ровно по шкале (аудит 21.10: иначе ключ выдают «ближайший к среднему» и «центр кластера»)
    picked = spread_pick(rng, key, below, above, k - n_above, n_above, cand.__getitem__,
                         lambda tv: distinct_ok([key, *tv], rel, abs_min))
    return sorted(n for n, _ in picked) if picked else None
