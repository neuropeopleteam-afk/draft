#!/usr/bin/env python3
"""Диагностика потолка мира и разложение потерь match-v2 — ТОЛЬКО миры разработки (отложенные не читаются).

Вход — признаки tools/realdata/bench2_feats.py. Перекрёстная проверка по мирам: обучение на половине зёрен,
оценка на другой половине и наоборот. Строки:
  product_now        — продукт как сейчас: фильтр стека с порогом (ltr.stack_filter), балл — текущие веса;
  cascade_now        — те же веса, но фильтр стека каскадом: сначала все обязательные, затем частично (никого не прячем);
  lin_allowed        — линейная модель (попарная логистическая, знаки весов ограничены) на разрешённых признаках + каскад;
  gbm_allowed        — LambdaMART (LightGBM lambdarank) на разрешённых признаках (без самоописания) + каскад;
  gbm_all            — потолок «по всем наблюдаемым признакам» (в т.ч. самоописание и BM25) — в продукт нельзя;
  oracle_pool        — пул подборки, упорядоченный по истинной метке: потолок при данном пуле;
nDCG@10: выигрыш 2^метка − 1, идеал — по всем кандидатам мира.

  python3 tools/realdata/bench2_diag.py --feats /tmp/b2/f_sm.npz --out /tmp/b2/diag_sm.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

THRESHOLDS = (1.0, 2 / 3, 1 / 2, 1 / 3, 0.0)
K_MIN = 10
FALLBACK = {"test": 0.45, "margin": 0.20, "fsp": 0.15, "required": 0.0, "desired": 0.05, "probe": 0.15,
            "failed": -0.45, "provisional": -0.05}
LIN_FEATS = ("test", "margin", "fsp", "required", "desired", "probe", "failed", "provisional", "over")
SIGNS = {"test": 1, "margin": 1, "fsp": 1, "required": 1, "desired": 1, "probe": 1, "failed": -1, "provisional": -1,
         "over": 0}
GBM_ALLOWED = ("test", "margin", "fsp", "required", "desired", "probe", "failed", "provisional", "theta_cut",
               "theta_next", "se", "above", "n_req")
GBM_ALL = GBM_ALLOWED + ("stack_cov", "n_declared", "decl_grade_diff", "years", "bm25", "decl_cov_raw")


def load(path: str, label: str = "rel") -> dict:
    z = np.load(path, allow_pickle=False)
    cols = [str(c) for c in z["cols"]]
    seeds = sorted({k.split("_")[0] for k in z.files if k != "cols"})
    W = {}
    for s in seeds:
        X = z[f"{s}_X"]
        d = {c: X[:, j] for j, c in enumerate(cols)}
        d["over"] = 1 / (1 + np.exp(-1.7 * d["theta_next"]))
        d["over"][d["theta_next"] <= -2.999] = 0.0
        if label == "l2":  # шкала 0–2 (сверка определений с соперником): релевантен = 2
            W[s] = {"F": d, "y": z[f"{s}_y2"], "qid": z[f"{s}_qid"], "idcg": z[f"{s}_idcg2"], "nrel": z[f"{s}_nrel2"]}
        else:
            W[s] = {"F": d, "y": z[f"{s}_y"], "qid": z[f"{s}_qid"], "idcg": z[f"{s}_idcg"], "nrel": z[f"{s}_nrel"]}
    return W


def bucket(cov: np.ndarray) -> np.ndarray:
    """Ярус фильтра стека: 0 — все обязательные, 1 — ≥ 2/3, 2 — ≥ 1/2, 3 — ≥ 1/3, 4 — меньше."""
    b = np.full(len(cov), 4)
    for j, t in enumerate(THRESHOLDS[:-1][::-1]):
        pass
    for j, t in enumerate(THRESHOLDS):
        b = np.where((cov >= t - 1e-9) & (b == 4) & (j < 4), j, b)
    return b


def order_query(score: np.ndarray, tier: np.ndarray, cov: np.ndarray, mode: str) -> np.ndarray:
    """Порядок внутри одного пула: индексы строк. mode: threshold — фильтр с порогом (как ltr.stack_filter),
    cascade — ярусы по порогам без скрытия, none — без фильтра стека."""
    n = len(score)
    if mode == "threshold":
        keep = np.ones(n, bool)
        for t in THRESHOLDS:
            k = cov >= t - 1e-9
            if t == 0.0 or int((k & (tier == 0)).sum()) >= K_MIN:
                keep = k
                break
        idx = np.nonzero(keep)[0]
        return idx[np.lexsort((-score[idx], tier[idx]))]
    if mode == "cascade":
        bk = bucket(cov)
        return np.lexsort((-score, bk, tier))
    return np.lexsort((-score, tier))


def metrics(y: np.ndarray, order: np.ndarray, idcg: float, nrel: int) -> dict:
    g = y[order].astype(float)
    disc = 1 / np.log2(np.arange(2, 12))
    g10 = np.zeros(10)
    g10[: min(10, len(g))] = g[:10]
    hit = np.nonzero(g >= 2)[0]
    return {"ndcg10": float(((2 ** g10 - 1) * disc).sum() / idcg) if idcg > 0 else 0.0,
            "p5": float((g[:5] >= 2).sum() / 5), "p10": float((g[:10] >= 2).sum() / 10),
            "mrr": float(1 / (hit[0] + 1)) if len(hit) else 0.0,
            "pool_rel_share": float((y >= 2).sum() / nrel) if nrel else 0.0}


def eval_scores(W: dict, seeds: list[str], scorer, mode: str) -> dict:
    rows = []
    for s in seeds:
        w = W[s]
        F, y, q = w["F"], w["y"], w["qid"]
        sc = scorer(F)
        for i in np.unique(q):
            m = q == i
            o = order_query(sc[m], F["tier"][m], F["stack_cov"][m], mode)
            rows.append(metrics(y[m], o, float(w["idcg"][i]), int(w["nrel"][i])))
    return {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0]}


def lin_scorer(wts: dict):
    return lambda F: sum(wts.get(k, 0.0) * F[k] for k in LIN_FEATS)


def pairs(W: dict, seeds: list[str], mode: str, max_pairs: int = 400000, seed: int = 1):
    """Пары (лучше, хуже) внутри пула и одного яруса (тот же ярус выдачи и фильтра стека)."""
    rng = np.random.default_rng(seed)
    D, wt = [], []
    for s in seeds:
        w = W[s]
        F, y, q = w["F"], w["y"], w["qid"]
        X = np.stack([F[k] for k in LIN_FEATS], axis=1)
        bk = bucket(F["stack_cov"]) if mode == "cascade" else np.zeros(len(y), int)
        for i in np.unique(q):
            m = np.nonzero((q == i) & (F["tier"] == 0))[0]
            for b in np.unique(bk[m]):
                mm = m[bk[m] == b]
                yy = y[mm]
                hi, lo = np.nonzero(yy[:, None] > yy[None, :])
                if len(hi) == 0:
                    continue
                D.append(X[mm[hi]] - X[mm[lo]])
                gain = (2.0 ** yy[hi] - 1) - (2.0 ** yy[lo] - 1)
                wt.append(gain)
    D = np.concatenate(D)
    wt = np.concatenate(wt)
    if len(D) > max_pairs:
        k = rng.choice(len(D), max_pairs, replace=False)
        D, wt = D[k], wt[k]
    return D, wt


def fit_linear(W: dict, seeds: list[str], mode: str, l2: float = 1e-3) -> dict:
    from scipy.optimize import minimize

    D, wt = pairs(W, seeds, mode)
    wt = wt / wt.mean()
    bounds = []
    for k in LIN_FEATS:
        sg = SIGNS[k]
        bounds.append((0.0, None) if sg > 0 else (None, 0.0) if sg < 0 else (None, None))

    def f(v):
        z = D @ v
        loss = np.logaddexp(0, -z)
        sig = 1 / (1 + np.exp(np.clip(z, -50, 50)))
        return float((wt * loss).mean() + l2 * (v @ v)), -(D * (wt * sig)[:, None]).mean(axis=0) + 2 * l2 * v

    v0 = np.array([FALLBACK.get(k, 0.0) for k in LIN_FEATS]) * 5
    r = minimize(f, v0, jac=True, method="L-BFGS-B", bounds=bounds)
    v = r.x
    pos = sum(max(0.0, v[j]) for j, k in enumerate(LIN_FEATS) if SIGNS[k] >= 0 and v[j] > 0) or 1.0
    return {k: round(float(v[j] / pos), 4) for j, k in enumerate(LIN_FEATS)}


def fit_gbm(W: dict, seeds: list[str], feats: tuple, mono: dict | None = None):
    import lightgbm as lgb

    X, y, grp = [], [], []
    for s in seeds:
        w = W[s]
        F, q = w["F"], w["qid"]
        X.append(np.stack([F[k] for k in feats], axis=1))
        y.append(w["y"])
        grp += [int((q == i).sum()) for i in np.unique(q)]
    X = np.concatenate(X)
    y = np.concatenate(y)
    params = dict(objective="lambdarank", n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=30,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.9, lambdarank_truncation_level=20,
                  label_gain=[0, 1, 3, 7], verbose=-1, random_state=7)
    if mono:
        params["monotone_constraints"] = [mono.get(k, 0) for k in feats]
    m = lgb.LGBMRanker(**params)
    # группы должны идти подряд: строки уже упорядочены по (мир, потребность)
    m.fit(X, y, group=grp)
    return lambda F: m.predict(np.stack([F[k] for k in feats], axis=1))


def run(path: str, label: str = "rel") -> dict:
    W = load(path, label)
    seeds = sorted(W)
    half = len(seeds) // 2
    folds = [(seeds[:half], seeds[half:]), (seeds[half:], seeds[:half])]
    res: dict = {"seeds": seeds, "rows": {}}

    def cv(name, make):
        parts = []
        for tr, te in folds:
            scorer, mode = make(tr)
            parts.append(eval_scores(W, te, scorer, mode))
        res["rows"][name] = {k: round(float(np.mean([p[k] for p in parts])), 4) for k in parts[0]}
        print(name, res["rows"][name], flush=True)

    cv("product_now", lambda tr: (lin_scorer(FALLBACK), "threshold"))
    cv("cascade_now", lambda tr: (lin_scorer(FALLBACK), "cascade"))
    cv("nofilter_now", lambda tr: (lin_scorer(FALLBACK), "none"))
    lin = {}

    def mk_lin(tr, mode):
        wts = fit_linear(W, tr, mode)
        lin.setdefault(mode, []).append(wts)
        return lin_scorer(wts), mode

    cv("lin_threshold", lambda tr: mk_lin(tr, "threshold"))
    cv("lin_cascade", lambda tr: mk_lin(tr, "cascade"))
    res["lin_weights"] = lin
    mono = {"test": 1, "margin": 0, "fsp": 1, "required": 1, "desired": 1, "probe": 1, "failed": -1, "provisional": -1}
    cv("gbm_allowed_cascade", lambda tr: (fit_gbm(W, tr, GBM_ALLOWED, mono), "cascade"))
    cv("gbm_allowed_threshold", lambda tr: (fit_gbm(W, tr, GBM_ALLOWED, mono), "threshold"))
    cv("gbm_all_ceiling", lambda tr: (fit_gbm(W, tr, GBM_ALL), "none"))

    def oracle(tr):
        return None, "oracle"

    # оракул пула (весь пул подборки до фильтра стека, по истинной метке)
    rows = []
    for s in seeds:
        w = W[s]
        for i in np.unique(w["qid"]):
            m = w["qid"] == i
            y = w["y"][m]
            rows.append(metrics(y, np.argsort(-y, kind="stable"), float(w["idcg"][i]), int(w["nrel"][i])))
    res["rows"]["oracle_pool"] = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0]}
    print("oracle_pool", res["rows"]["oracle_pool"], flush=True)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--feats", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="rel", choices=("rel", "l2"))
    a = ap.parse_args()
    r = run(a.feats, a.label)
    Path(a.out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
