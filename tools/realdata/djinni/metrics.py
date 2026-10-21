"""Метрики ранжирования и бутстреп-ДИ по вакансиям (без зависимостей от продукта)."""
from __future__ import annotations

import math
import random


def dcg(rels: list[int], k: int) -> float:
    return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def ndcg(ranked_rels: list[int], all_rels: list[int], k: int = 10) -> float:
    ideal = dcg(sorted(all_rels, reverse=True), k)
    return dcg(ranked_rels, k) / ideal if ideal > 0 else 0.0


def precision(ranked_rels: list[int], k: int, thr: int) -> float:
    """P@k с постоянным знаменателем k: пустые места (выдача короче k) — нерелевантны."""
    return sum(1 for r in ranked_rels[:k] if r >= thr) / k


def rr(ranked_rels: list[int], thr: int, cutoff: int = 50) -> float:
    return next((1.0 / i for i, r in enumerate(ranked_rels[:cutoff], 1) if r >= thr), 0.0)


def per_vacancy(ranked_rels: list[int], all_rels: list[int]) -> dict:
    return {"ndcg@10": ndcg(ranked_rels, all_rels, 10),
            "mrr_rel1": rr(ranked_rels, 1), "mrr_rel2": rr(ranked_rels, 2),
            "p@5_rel1": precision(ranked_rels, 5, 1), "p@5_rel2": precision(ranked_rels, 5, 2)}


KEYS = ("ndcg@10", "mrr_rel1", "mrr_rel2", "p@5_rel1", "p@5_rel2")


def summarize(rows: list[dict], seed: str, n_boot: int = 10000) -> dict:
    """Среднее по вакансиям и 95 % перцентильный бутстреп-ДИ (выборка вакансий с возвращением)."""
    n = len(rows)
    rng = random.Random(seed)
    idx = [[rng.randrange(n) for _ in range(n)] for _ in range(n_boot)]
    out = {}
    for k in KEYS:
        vals = [r[k] for r in rows]
        means = sorted(sum(vals[i] for i in s) / n for s in idx)
        out[k] = {"mean": round(sum(vals) / n, 4), "ci95": [round(means[int(0.025 * n_boot)], 4),
                                                            round(means[int(0.975 * n_boot) - 1], 4)]}
    return out


def paired_diff(a: list[dict], b: list[dict], seed: str, n_boot: int = 10000) -> dict:
    """Разность «a − b» по одним и тем же вакансиям с парным бутстреп-ДИ."""
    n = len(a)
    rng = random.Random(seed)
    idx = [[rng.randrange(n) for _ in range(n)] for _ in range(n_boot)]
    out = {}
    for k in KEYS:
        d = [x[k] - y[k] for x, y in zip(a, b)]
        means = sorted(sum(d[i] for i in s) / n for s in idx)
        out[k] = {"diff": round(sum(d) / n, 4), "ci95": [round(means[int(0.025 * n_boot)], 4),
                                                         round(means[int(0.975 * n_boot) - 1], 4)]}
    return out
