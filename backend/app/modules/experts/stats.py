"""Статистика экспертной разметки: метрики ранжирования, согласие оценщиков, бутстреп, перевод Ангоффа в θ.

Без внешних пакетов (кроме numpy/scipy, уже стоящих). Все функции детерминированы (зерно бутстрепа фиксировано).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import combinations
import math

import numpy as np

BOOT = 2000
SEED = 20261006


# ------------------------------------------------------------------ ранжирование
def dcg(gains: Sequence[float], k: int) -> float:
    return float(sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(list(gains)[:k])))


def ndcg_at(rels_top: Sequence[float], all_rels: Sequence[float], k: int = 5) -> float:
    ideal = dcg(sorted(all_rels, reverse=True), k)
    return dcg(rels_top, k) / ideal if ideal > 0 else 0.0


def precision_at(rels_top: Sequence[float], k: int = 5, thr: float = 2.0) -> float:
    return sum(1 for r in list(rels_top)[:k] if r >= thr) / k


# ------------------------------------------------------------------ бутстреп
def boot_ci(values: Sequence[float], stat: Callable[[np.ndarray], float] = np.mean, n: int = BOOT,
            seed: int = SEED, alpha: float = 0.05) -> dict:
    """Перцентильный ДИ бутстрепа по единицам (потребностям, объектам)."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if len(v) == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    est = float(stat(v))
    if len(v) == 1:
        return {"mean": round(est, 3), "lo": None, "hi": None, "n": 1}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n, len(v)))
    bs = np.array([stat(v[i]) for i in idx]) if stat is not np.mean else v[idx].mean(axis=1)
    lo, hi = np.quantile(bs, [alpha / 2, 1 - alpha / 2])
    return {"mean": round(est, 3), "lo": round(float(lo), 3), "hi": round(float(hi), 3), "n": int(len(v))}


def cluster_boot_ci(groups: Sequence[Sequence[float]], n: int = BOOT, seed: int = SEED, alpha: float = 0.05) -> dict:
    """Перцентильный ДИ бутстрепа по кластерам (потребностям): кластер — все единицы одной потребности (например, она же
    в пакетах v1 и v2), повторная выборка — кластерами, статистика — среднее по всем единицам выборки. При одной единице
    в кластере совпадает с boot_ci (те же случайные индексы)."""
    gs = [np.asarray([x for x in g if x is not None], dtype=float) for g in groups]
    gs = [g for g in gs if len(g)]
    if not gs:
        return {"mean": None, "lo": None, "hi": None, "n": 0, "clusters": 0}
    sums = np.array([g.sum() for g in gs])
    cnt = np.array([len(g) for g in gs], dtype=float)
    est = float(sums.sum() / cnt.sum())
    if len(gs) == 1:
        return {"mean": round(est, 3), "lo": None, "hi": None, "n": int(cnt.sum()), "clusters": 1}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(gs), size=(n, len(gs)))
    bs = sums[idx].sum(axis=1) / cnt[idx].sum(axis=1)
    lo, hi = np.quantile(bs, [alpha / 2, 1 - alpha / 2])
    return {"mean": round(est, 3), "lo": round(float(lo), 3), "hi": round(float(hi), 3), "n": int(cnt.sum()),
            "clusters": len(gs)}


def wilcoxon_p(diffs: Sequence[float]) -> float | None:
    d = [x for x in diffs if x is not None and abs(x) > 1e-12]
    if len(d) < 5:
        return None
    try:
        from scipy.stats import wilcoxon

        return round(float(wilcoxon(d).pvalue), 4)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ согласие
def weighted_kappa(a: Sequence[float], b: Sequence[float], cats: Sequence[float] = (0, 1, 2, 3)) -> float | None:
    """Квадратично взвешенная каппа Коэна для двух оценщиков на общих объектах."""
    if len(a) < 2:
        return None
    k = len(cats)
    pos = {c: i for i, c in enumerate(cats)}
    o = np.zeros((k, k))
    for x, y in zip(a, b):
        o[pos[_snap(x, cats)], pos[_snap(y, cats)]] += 1
    o /= o.sum()
    e = np.outer(o.sum(axis=1), o.sum(axis=0))
    w = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)], dtype=float) / (k - 1) ** 2
    den = float((w * e).sum())
    if den <= 1e-12:
        return 1.0 if float((w * o).sum()) <= 1e-12 else 0.0
    return round(1 - float((w * o).sum()) / den, 3)


def _snap(x: float, cats: Sequence[float]) -> float:
    return min(cats, key=lambda c: abs(c - float(x)))


def krippendorff_alpha(units: dict, level: str = "ordinal") -> float | None:
    """Альфа Криппендорфа. units: {объект: [оценки разных экспертов]} (неполный план допустим).

    level: ordinal (порядковая метрика по частотам рангов) | interval (квадрат разности).
    """
    vals = {u: [float(x) for x in v if x is not None] for u, v in units.items()}
    vals = {u: v for u, v in vals.items() if len(v) >= 2}
    if not vals:
        return None
    cats = sorted({x for v in vals.values() for x in v})
    if len(cats) == 1:
        return 1.0
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    o = np.zeros((k, k))
    for v in vals.values():
        m = len(v)
        for i, j in ((i, j) for i in range(m) for j in range(m) if i != j):
            o[idx[v[i]], idx[v[j]]] += 1.0 / (m - 1)
    n_c = o.sum(axis=1)
    n = n_c.sum()
    if level == "interval":
        d2 = np.array([[(ci - ck) ** 2 for ck in cats] for ci in cats])
    else:
        d2 = np.zeros((k, k))
        for a in range(k):
            for b in range(k):
                lo, hi = min(a, b), max(a, b)
                d2[a, b] = (n_c[lo:hi + 1].sum() - (n_c[a] + n_c[b]) / 2) ** 2
    d_o = float((o * d2).sum())
    d_e = float((np.outer(n_c, n_c) * d2).sum()) / (n - 1)
    if d_e <= 1e-12:
        return None
    return round(1 - d_o / d_e, 3)


def pairwise(ratings: dict[str, dict], cats: Sequence[float] = (0, 1, 2, 3), min_common: int = 3) -> list[dict]:
    """Попарное согласие экспертов: {эксперт: {объект: оценка}} → κ (квадр.), доля точных совпадений и ±1."""
    out = []
    for e1, e2 in combinations(sorted(ratings), 2):
        common = sorted(set(ratings[e1]) & set(ratings[e2]))
        if len(common) < min_common:
            continue
        a = [ratings[e1][u] for u in common]
        b = [ratings[e2][u] for u in common]
        out.append({"pair": f"{e1}–{e2}", "n": len(common), "kappa": weighted_kappa(a, b, cats),
                    "exact": round(sum(1 for x, y in zip(a, b) if abs(x - y) < 1e-9) / len(common), 3),
                    "within1": round(sum(1 for x, y in zip(a, b) if abs(x - y) <= 1 + 1e-9) / len(common), 3),
                    "kappa_ci": _kappa_ci(a, b, cats)})
    return out


def _kappa_ci(a, b, cats, n: int = 1000) -> dict | None:
    if len(a) < 8:
        return None
    rng = np.random.default_rng(SEED)
    a, b = np.asarray(a, float), np.asarray(b, float)
    bs = []
    for _ in range(n):
        i = rng.integers(0, len(a), len(a))
        v = weighted_kappa(a[i], b[i], cats)
        if v is not None:
            bs.append(v)
    if not bs:
        return None
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"lo": round(float(lo), 3), "hi": round(float(hi), 3)}


def alpha_ci(units: dict, level: str = "ordinal", n: int = 1000) -> dict | None:
    keys = [u for u, v in units.items() if len([x for x in v if x is not None]) >= 2]
    if len(keys) < 8:
        return None
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(n):
        pick = rng.integers(0, len(keys), len(keys))
        v = krippendorff_alpha({i: units[keys[j]] for i, j in enumerate(pick)}, level)
        if v is not None:
            bs.append(v)
    if not bs:
        return None
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"lo": round(float(lo), 3), "hi": round(float(hi), 3)}


def landis_koch(k: float | None) -> str | None:
    if k is None:
        return None
    for thr, t in ((0.81, "почти полное"), (0.61, "существенное"), (0.41, "умеренное"), (0.21, "слабое"),
                   (0.0, "незначительное")):
        if k >= thr:
            return t
    return "хуже случайного"


# ------------------------------------------------------------------ Ангофф
def expected_share(theta: float, a: Sequence[float], b: Sequence[float]) -> float:
    """Ожидаемая доля максимального балла семейства при θ (2PL по частям, как в движке теста)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return float(np.mean(1 / (1 + np.exp(-a * (theta - b)))))


def solve_theta(target: float, params: list[tuple[Sequence[float], Sequence[float]]], lo: float = -4.0,
                hi: float = 4.0) -> float:
    """θ, при котором сумма ожидаемых долей по семействам равна target (характеристическая функция теста)."""
    if not params:
        return float("nan")
    f = lambda t: sum(expected_share(t, a, b) for a, b in params) - target  # noqa: E731
    if f(lo) >= 0:
        return lo
    if f(hi) <= 0:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
