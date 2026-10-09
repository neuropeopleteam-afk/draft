"""Расчёты проверки с живыми пользователями: SUS, P@5 по оценкам людей, интервалы, медианы. Чистые функции.

Правила, которые держит код (и текст на /validation):
* SUS — стандартный расчёт Брука: нечётные пункты (ответ − 1), чётные (5 − ответ), сумма × 2,5 → 0…100.
  Интервал среднего — 95 % по t-распределению Стьюдента (малые выборки).
* Релевантность — оценка кандидата подборки по шкале 1–5; «релевантен» — оценка 4 или 5 (REL_THRESHOLD).
  P@5 участника = доля релевантных среди оцененных им первых пяти; итог — среднее по участникам, интервал —
  bootstrap-перцентили по участникам (2000 повторов, фиксированное зерно: цифры воспроизводимы).
* Доли (завершили путь) — интервал Уилсона 95 %.
* Показ — только при N ≥ MIN_N ответивших; срез по роли — тоже только при N роли ≥ MIN_N.
"""
from __future__ import annotations

import math
import statistics

MIN_N = 3
SUS_BENCHMARK = 68.0  # среднее по большим выборкам (Sauro, Lewis, 2016): ориентир, не норматив
BOOT_N = 2000
BOOT_SEED = 20261009


def sus_score(items: list[int]) -> float:
    """SUS 0…100 по 10 ответам 1–5 (порядок — как в шкале: нечётные положительные, чётные отрицательные)."""
    if len(items) != 10 or any((not isinstance(v, int)) or isinstance(v, bool) or not 1 <= v <= 5 for v in items):
        raise ValueError("SUS: нужно 10 ответов от 1 до 5")
    odd = sum(items[i] - 1 for i in range(0, 10, 2))
    even = sum(5 - items[i] for i in range(1, 10, 2))
    return (odd + even) * 2.5


def mean_ci(values: list[float], level: float = 0.95, lo: float | None = None, hi: float | None = None) -> dict:
    """{n, mean, sd, ci: [нижняя, верхняя] | None} — t-интервал; ci=None при n < 2. Границы шкалы lo/hi обрезают интервал."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "ci": None}
    m = sum(values) / n
    if n < 2:
        return {"n": n, "mean": m, "sd": None, "ci": None}
    sd = statistics.stdev(values)
    from scipy import stats as sps

    half = float(sps.t.ppf(0.5 + level / 2, n - 1)) * sd / math.sqrt(n)
    a, b = m - half, m + half
    if lo is not None:
        a = max(a, lo)
    if hi is not None:
        b = min(b, hi)
    return {"n": n, "mean": m, "sd": sd, "ci": [a, b]}


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Интервал Уилсона для доли k из n."""
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def boot_mean_ci(values: list[float], level: float = 0.95) -> list[float] | None:
    """Bootstrap-перцентильный интервал среднего (по участникам); None — меньше двух значений."""
    if len(values) < 2:
        return None
    import numpy as np

    rng = np.random.default_rng(BOOT_SEED)
    arr = np.asarray(values, dtype=float)
    means = rng.choice(arr, size=(BOOT_N, len(arr)), replace=True).mean(axis=1)
    a = (1 - level) / 2
    return [float(np.quantile(means, a)), float(np.quantile(means, 1 - a))]


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def quartiles(values: list[float]) -> list[float] | None:
    if len(values) < 4:
        return None
    q = statistics.quantiles(values, n=4, method="inclusive")
    return [q[0], q[2]]


def p_at_k(ratings: list[int], threshold: int = 4) -> float | None:
    """Доля оценок не ниже порога среди выставленных (все показанные кандидаты оценены — это проверяет сервис)."""
    return None if not ratings else sum(1 for r in ratings if r >= threshold) / len(ratings)


def share(k: int, n: int) -> dict:
    return {"k": k, "n": n, "share": (k / n if n else None), "ci": wilson(k, n)}
