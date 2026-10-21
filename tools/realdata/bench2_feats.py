#!/usr/bin/env python3
"""Признаки пар «потребность × кандидат пула» для обучения и диагностики match-v2 (только миры разработки).

Строка = кандидат из пула подборки потребности (как build_selection, до фильтра стека). Признаки двух видов:
  разрешённые в балле (тест, ФСП, задания, навыки, подтверждённые тестом) и фильтр стека (доля обязательных навыков,
  заявленных или подтверждённых тестом — только как фильтр/ярус, не как балл);
  диагностические «запрещённые» (самоописание: число заявленных навыков, заявленный грейд, опыт, BM25 по резюме) —
  только для оценки потолка мира «по всем наблюдаемым признакам», в продукт не идут.

  python3 tools/realdata/bench2_feats.py --cond sm --seeds 31000001,31000002 --out /tmp/f_sm.npz
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench2  # noqa: E402

ALLOWED = ("test", "margin", "fsp", "required", "desired", "probe", "failed", "provisional", "theta_cut", "theta_next",
           "se", "tier", "above", "stack_cov", "n_req")
FORBIDDEN = ("n_declared", "decl_grade_diff", "years", "bm25", "decl_cov_raw")
COLS = ALLOWED + FORBIDDEN


def world_rows(w, doz: bool = False) -> dict:
    from app.modules.catalog.seed_data import GRADE_CUTS, GRADE_LEVEL, GRADE_ORDER
    from app.modules.matching import ltr, ranking
    from app.modules.validation.matching_bench import BM25Matrix

    os.environ["MATCH_V2"] = "1"
    bundles = bench2.bundles_of(w)
    reqs = bench2.parse(w)
    bm = BM25Matrix([c.obs.resume_text for c in w.cands])
    X, y, y2, qid, cidx = [], [], [], [], []
    jobs = []
    for i, (n, req) in enumerate(zip(w.needs, reqs, strict=True)):
        idx, above_id = bench2.pool_for(bundles, req)
        jobs.append((i, n, req, idx, above_id, {}))
        if doz:  # состояние «после дозапроса»: топ-K текущего порядка продукта получили задания (qid + 100000)
            order, _, _ = bench2.order_v2(bundles, idx, req, above_id)
            jobs.append((i + 100000, n, req, idx, above_id, bench2.dozapros_plan(w, bundles, i, req, order)))
    for qi, n, req, idx, above_id, plan in jobs:
        i = qi % 100000
        with bench2.applied(bundles, plan):
            tags = ltr.required_tags(req)
            g = req.get("grade") or n.grade
            gi = GRADE_ORDER.index(g) if g in GRADE_ORDER else None
            nxt = GRADE_ORDER[gi + 1] if gi is not None and gi + 1 < len(GRADE_ORDER) else None
            bms = bm.scores(n.text)
            for k in idx:
                b = bundles[k]
                _s, comps, _r = ranking.score_candidate(b, req, None)
                t = b.test.value if b.test else {}
                th = t.get("theta")
                o = w.cands[k].obs
                decl = set(o.stack_declared)
                row = {
                    "test": comps.get("test", 0.0), "margin": comps.get("margin", 0.0), "fsp": comps.get("fsp", 0.0),
                    "required": comps.get("required", 0.0), "desired": comps.get("desired", 0.0),
                    "probe": comps.get("probe_v2", comps.get("probe", 0.0)), "failed": comps.get("failed", 0.0),
                    "provisional": 1.0 if b.provisional else 0.0,
                    "theta_cut": (th - GRADE_CUTS[g]) if (th is not None and not b.unconfirmed and g in GRADE_CUTS) else -3.0,
                    "theta_next": (th - GRADE_CUTS[nxt]) if (th is not None and nxt and not b.unconfirmed) else -3.0,
                    "se": float(t.get("se") or 0.6), "tier": float(ranking.tier(b)),
                    "above": 1.0 if (above_id and b.profile.current_category_id == above_id) else 0.0,
                    "stack_cov": ltr.stack_coverage(b, tags), "n_req": float(len(tags)),
                    "n_declared": float(len(decl)),
                    "decl_grade_diff": float(GRADE_LEVEL[o.grade_declared] - GRADE_LEVEL.get(g, 1)),
                    "years": float(o.experience_years), "bm25": float(bms[k]),
                    "decl_cov_raw": (len(set(tags) & decl) / len(tags)) if tags else 1.0,
                }
                X.append([float(row[c]) for c in COLS])
                y.append(int(w.rel[i][k]))
                y2.append(int(w.rel_l2[i][k]))
                qid.append(qi)
                cidx.append(k)
    # идеал по всему миру (для nDCG с идеалом «по всем кандидатам»)
    disc = 1 / np.log2(np.arange(2, 12))
    idcg = [float(((2.0 ** np.sort(w.rel[i].astype(float))[::-1][:10] - 1) * disc).sum()) for i in range(len(w.needs))]
    nrel = [int((w.rel[i] >= 2).sum()) for i in range(len(w.needs))]
    idcg2 = [float(((2.0 ** np.sort(w.rel_l2[i].astype(float))[::-1][:10] - 1) * disc).sum()) for i in range(len(w.needs))]
    nrel2 = [int((w.rel_l2[i] >= 2).sum()) for i in range(len(w.needs))]
    return {"X": np.asarray(X, dtype=float), "y": np.asarray(y), "y2": np.asarray(y2), "qid": np.asarray(qid),
            "cidx": np.asarray(cidx), "idcg": np.asarray(idcg), "nrel": np.asarray(nrel),
            "idcg2": np.asarray(idcg2), "nrel2": np.asarray(nrel2)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", required=True, choices=bench2.CONDS)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--doz", action="store_true", help="добавить состояние «после дозапроса» (qid + 100000)")
    a = ap.parse_args()
    bench2.init(a.cond)
    parts = {}
    for s in [int(x) for x in a.seeds.split(",")]:
        w = bench2.make_world(a.cond, s)
        r = world_rows(w, doz=a.doz)
        for k, v in r.items():
            parts[f"{s}_{k}"] = v
        print(s, w.digest()[:12], r["X"].shape, flush=True)
    np.savez_compressed(a.out, cols=np.array(COLS), **parts)
