#!/usr/bin/env python3
"""Обучение весов match-v2 — ТОЛЬКО на мирах разработки (оба условия: S-M и жёсткий); отложенные зёрна не читаются.

Модель — линейная (балл «из 100» раскладывается на вклады признаков для HR), обучение — попарная логистическая
регрессия: пары «лучше — хуже» внутри одного пула подборки и одного яруса фильтра стека, вес пары — разность
выигрышей 2^метка − 1 (как в nDCG). Знаки ограничены по смыслу (ltr.POSITIVE ≥ 0, ltr.NEGATIVE ≤ 0); признак
«тест выше порога следующего грейда» (over) — без ограничения знака: что лучше для работодателя — решают данные
разработки обоих условий (в S-M «сильнее запроса» — метка 2, в жёстком — 3). Условия входят с равным весом.

  python3 tools/realdata/ltr_train.py --feats sm=/tmp/b2/f_sm.npz,hard=/tmp/b2/f_hard.npz \
      --out backend/app/modules/matching/ltr_weights.json
Признаки — tools/realdata/bench2_feats.py (зёрна разработки 31000001–31000006, 20261006, 20261007).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import bench2_diag as dg

DEV_SEEDS = ("31000001", "31000002", "31000003", "31000004", "31000005", "31000006", "20261006", "20261007")
HOLDOUT_SEEDS = ("77021131", "77021132", "77021133", "77021134", "77021135", "77021141", "77021142")


def fit_joint(Ws: dict[str, dict], seeds: dict[str, list[str]], mode: str = "cascade", l2: float = 1e-3) -> dict:
    from scipy.optimize import minimize

    Ds, wts = [], []
    for cond, W in Ws.items():
        D, wt = dg.pairs(W, seeds[cond], mode)
        wt = wt / wt.sum()  # равный вес условий
        Ds.append(D)
        wts.append(wt)
    D = np.concatenate(Ds)
    wt = np.concatenate(wts)
    wt = wt / wt.mean()
    bounds = []
    for k in dg.LIN_FEATS:
        sg = dg.SIGNS[k]
        bounds.append((0.0, None) if sg > 0 else (None, 0.0) if sg < 0 else (None, None))

    def f(v):
        z = D @ v
        sig = 1 / (1 + np.exp(np.clip(z, -50, 50)))
        return float((wt * np.logaddexp(0, -z)).mean() + l2 * (v @ v)), \
            -(D * (wt * sig)[:, None]).mean(axis=0) + 2 * l2 * v

    v0 = np.array([dg.FALLBACK.get(k, 0.0) for k in dg.LIN_FEATS]) * 5
    r = minimize(f, v0, jac=True, method="L-BFGS-B", bounds=bounds)
    v = r.x
    pos = sum(v[j] for j, k in enumerate(dg.LIN_FEATS) if v[j] > 0 and dg.SIGNS[k] >= 0) or 1.0
    return {k: round(float(v[j] / pos), 4) for j, k in enumerate(dg.LIN_FEATS)}


def evaluate(Ws: dict, seeds: dict, wts: dict, mode: str = "cascade") -> dict:
    """По условиям и состояниям: «без дозапроса» (запросы < 100000) и «после дозапроса» (если есть)."""
    out = {}
    for c, W in Ws.items():
        has_doz = any(bool((W[s]["qid"] >= 100000).any()) for s in seeds[c])
        out[c] = dg.eval_scores(W, seeds[c], dg.lin_scorer(wts), mode, state=0)
        if has_doz:
            out[c + "_doz"] = dg.eval_scores(W, seeds[c], dg.lin_scorer(wts), mode, state=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feats", required=True, help="cond=path,...")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--lin", default=None, help="признаки линейной модели через запятую (по умолчанию bench2_diag.LIN_FEATS)")
    a = ap.parse_args()
    if a.lin:
        dg.LIN_FEATS = tuple(a.lin.split(","))
    paths = dict(x.split("=", 1) for x in a.feats.split(","))  # «sm=путь» или «sm:l2=путь» (шкала 0–2)
    Ws = {c.split(":")[0]: dg.load(p, c.split(":")[1] if ":" in c else "rel") for c, p in paths.items()}
    labels = {c.split(":")[0]: (c.split(":")[1] if ":" in c else "rel") for c in paths}
    paths = {c.split(":")[0]: p for c, p in paths.items()}
    for c, W in Ws.items():
        bad = set(W) & set(HOLDOUT_SEEDS)
        assert not bad, f"в признаках {c} есть отложенные зёрна {bad}"
        assert set(W) <= set(DEV_SEEDS), f"{c}: неизвестные зёрна {set(W) - set(DEV_SEEDS)}"
    seeds = {c: sorted(W) for c, W in Ws.items()}
    # перекрёстная проверка по мирам (половины зёрен) — оценка обобщения до финальной подгонки на всех мирах
    half = {c: (s[: len(s) // 2], s[len(s) // 2:]) for c, s in seeds.items()}
    cv = {"joint_cascade": [], "now_threshold": []}
    for f in (0, 1):
        tr = {c: half[c][f] for c in seeds}
        te = {c: half[c][1 - f] for c in seeds}
        w = fit_joint(Ws, tr)
        cv["joint_cascade"].append(evaluate(Ws, te, w))
        cv["now_threshold"].append(evaluate(Ws, te, dg.FALLBACK, "threshold"))
    cv_mean = {k: {c: {m: round(float(np.mean([p[c][m] for p in v])), 4) for m in v[0][c]} for c in v[0]}
               for k, v in cv.items()}
    final = fit_joint(Ws, seeds)
    on_dev = evaluate(Ws, seeds, final)
    h = hashlib.sha256()
    for c in sorted(paths):
        h.update(Path(paths[c]).read_bytes())
    meta = {"source": "tools/realdata/ltr_train.py", "version": "match-v2", "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dev_seeds": {c: seeds[c] for c in seeds}, "holdout_seeds_not_used": list(HOLDOUT_SEEDS),
            "conditions": sorted(seeds), "labels": labels, "features": list(dg.LIN_FEATS),
            "features_sha256": h.hexdigest(), "filter": "каскад стека (ltr.THRESHOLDS)",
            "objective": "попарная логистическая, вес пары — разность 2^метка − 1, условия с равным весом, L2 1e-3",
            "cv_by_worlds": cv_mean, "fit_on_all_dev": on_dev}
    out = {"weights": final, "meta": meta}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"weights": final, "cv": cv_mean}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
