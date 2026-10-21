"""Помощники коротких семейств Principal (волна 10, поток ПБ-В): qa, security, mobile, analyst.

Только для генераторов ``<направление>/principal_*.py`` этого потока. Короткое задание — ≤ 7 мин
(``time_limit_s`` ≤ 420, как блок у границы Lead/Principal в симуляции уровней).

* ``numeric_mcq`` — расчётный mcq_concept: четыре числа одной формы и длины (подпись не выдаёт величину), ключ
  печатает программа-модель по тем же числам, что видит кандидат (перебор, имитация, точные дроби — не формула
  генератора). Ловушки — модели типичных ошибок из пула семейства; сколько ловушек меньше ключа (0–3), выбирается
  равновероятно до подбора чисел, поэтому место ключа по величине не выдаёт ответ.
* ``choice_mcq`` — выбор одного решения из фиксированного набора (порядок, мера, порог): ключ — программа; какое
  решение верное, задаётся по seed поровну (генератор подбирает числа под заданный ответ).
* ``n_below`` — семейство выбирает его равновероятно из трёх-четырёх значений (если ловушек ниже ключа мало —
  из 1–3 или 0–2): ключ на каждом месте по величине не чаще 1/3.
* ``FMT`` — форматы чисел (исходный текст функции ``fmt`` вкладывается в программу проверки дословно).
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from assessment_bank.families._lead_b_utils import computed_mcq
from assessment_bank.gen_utils import spread_pick

# Форматы подписи: все варианты одной длины (проверяется), десятичная запятая.
FMT = {
    "int": "def fmt(x):\n    return str(int(round(x)))\n",
    "d1": "def fmt(x):\n    return f'{x:.1f}'.replace('.', ',')\n",
    "d2": "def fmt(x):\n    return f'{x:.2f}'.replace('.', ',')\n",
    "p0": "def fmt(x):\n    return f'{100 * x:.0f}' + ' %'\n",
    "p1": "def fmt(x):\n    return f'{100 * x:.1f}'.replace('.', ',') + ' %'\n",
    "p2": "def fmt(x):\n    return f'{100 * x:.2f}'.replace('.', ',') + ' %'\n",
    "p3": "def fmt(x):\n    return f'{100 * x:.3f}'.replace('.', ',') + ' %'\n",
}
_SCALE = {"int": 1, "d1": 10, "d2": 100, "p0": 100, "p1": 1000, "p2": 10000, "p3": 100000}


def formatter(kind: str, unit: str = "") -> tuple[Callable[[float], str], str]:
    """(функция fmt, её исходный текст для программы проверки); ``unit`` дописывается через пробел."""
    src = FMT[kind]
    if unit:
        src = src.rstrip("\n") + f" + {(' ' + unit)!r}\n"
    ns: dict[str, Any] = {}
    exec(src, ns)  # noqa: S102 — фиксированный текст из словаря выше
    return ns["fmt"], src


def near_rounding_edge(x: float, kind: str, eps: float = 0.02) -> bool:
    """Значение близко к границе округления (…,5 в последнем знаке) — программа и генератор могут разойтись."""
    y = abs(x) * _SCALE[kind]
    frac = y - int(y)
    return abs(frac - 0.5) < eps


def pick_traps(good: float, pool: dict[str, float], n_below: int, rng, fmt: Callable[[float], str],
               kind: str, rel: float = 0.08, lo: float | None = None, hi: float | None = None) -> list[str] | None:
    """Три ловушки из ``pool``: ровно ``n_below`` меньше ключа, остальные больше; подписи различны и одной длины,
    каждое значение отличается от ключа и от других не меньше чем на ``rel`` (приближённый расчёт даёт тот же
    ключ). Значения вне [lo, hi] и у границы округления отбрасываются. None — не подобрать (генератор повторяет)."""
    if near_rounding_edge(good, kind) or (lo is not None and good < lo) or (hi is not None and good >= hi):
        return None
    ok = {}
    for k, v in pool.items():
        if v is None or v != v or v in (float("inf"), float("-inf")):
            continue
        if (lo is not None and v < lo) or (hi is not None and v >= hi) or near_rounding_edge(v, kind):
            continue
        if abs(v - good) < rel * max(abs(v), abs(good)):
            continue
        ok[k] = v
    below = sorted(k for k, v in ok.items() if v < good)
    above = sorted(k for k, v in ok.items() if v > good)
    def fits(tvals: list[float]) -> bool:
        vals = [good] + list(tvals)
        texts = [fmt(v) for v in vals]
        if len(set(texts)) != 4 or len({len(t) for t in texts}) != 1:
            return False
        sv = sorted(vals)
        return all(b - a >= rel * max(abs(b), 1e-12) for a, b in zip(sv, sv[1:]))

    def control(x: float) -> float | None:
        v = round(x * _SCALE[kind]) / _SCALE[kind]
        if v <= 0 or (lo is not None and v < lo) or (hi is not None and v >= hi):
            return None
        return v

    rng.shuffle(below)
    rng.shuffle(above)
    # варианты — ровно по шкале, ранг ключа задан заранее; если ловушек с одной стороны не хватает — контрольные
    # значения «_fb_ctl*» тем же шагом (аудит 21.10: иначе ключ выдают «ближайший к среднему» и «центр кластера»)
    picked = spread_pick(rng, good, below, above, n_below, 3 - n_below, ok.__getitem__, fits,
                         control=control, min_step=max(0.15, 1.6 * rel))
    if picked is None:
        return None
    for n, v in picked:
        pool[n] = v  # контрольные значения — в общий словарь (по нему numeric_mcq строит подписи)
    return [n for n, _ in picked]


def numeric_mcq(fid: str, seed: int, rng, *, ctx: str, stem: str, good: float, pool: dict[str, float],
                traps: Sequence[str], fmt: Callable[[float], str], program: str, why: str,
                params: dict[str, Any], code: str | None = None, note: str | None = None):
    """Расчётный mcq_concept: ``program`` печатает подпись верного варианта (через вложенный ``fmt``)."""
    ctl = [fmt(pool[t]) for t in traps if t.startswith("_fb_")]
    if ctl:
        why = (f"{why} Контрольные значения на той же шкале (не связаны с конкретной ошибкой): "
               f"{', '.join(ctl)}.")
    return computed_mcq(fid, seed, rng, stem=stem, correct=fmt(good), distractors=[fmt(pool[t]) for t in traps],
                        program=program, why=why, context=ctx, code=code, language="text",
                        params={**params, "traps": list(traps), "good": good},
                        note=note or "Программа-модель считает ответ по тем же числам, что показаны кандидату.",
                        max_ratio=1.0)


def choice_mcq(fid: str, seed: int, rng, *, ctx: str, stem: str, correct: str, distractors: Sequence[str],
               program: str, why: str, params: dict[str, Any], code: str | None = None, note: str | None = None,
               max_ratio: float = 1.35):
    """Выбор решения из набора: ``program`` печатает текст верного решения."""
    return computed_mcq(fid, seed, rng, stem=stem, correct=correct, distractors=list(distractors), program=program,
                        why=why, context=ctx, code=code, language="text", params=params,
                        note=note or "Программа-модель перебирает решения и печатает лучшее по тем же числам.",
                        max_ratio=max_ratio)
