"""Добор ступенью выше (Я12б, grade_above, match-v1.3): бенчмарк со скрытой истиной «до/после» в малом и большом пуле.

«До» — match-v1.2 (platform_orders(above=False)), «после» — продукт с добором (above=True). Тот же мир, те же
компоненты скоринга, веса не подбирались. Миры: 200 × 500 (seed 20261006 и 20261007 — в точной категории около 20
кандидатов, как в демо-пуле стенда), 50 × 500 (мир контроля ranking_guard), 60 × 600 (размер анализа
чувствительности) и основной 200 × 2000 (оба seed; около 100 на категорию — правило не включается).
Правило приёмки: P@5, P@10, nDCG@5, nDCG@10 и MRR не ниже «до» ни в одном мире. Покрытие обязательного (T1) у лучшего
из первых пяти и среднее по первым пяти — для справки (в синтетике и на hh.ru считается одинаково).

    cd backend && python ../tools/realdata/grade_above_bench.py [--quick]   # → docs/validation/grade_above.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.matching import grade_above  # noqa: E402
from app.modules.validation.bench_world import BenchConfig, generate  # noqa: E402
from app.modules.validation.matching_bench import COMP_KEYS, _parsed, per_need, platform_orders, score_world  # noqa: E402

OUT = ROOT / "docs/validation/grade_above.json"
METRICS = ("p@5", "p@10", "ndcg@5", "ndcg@10", "mrr")
WORLDS = (("small_1", "200 × 500, seed 20261006", dict(n_needs=200, n_candidates=500, seed=20261006)),
          ("small_2", "200 × 500, seed 20261007", dict(n_needs=200, n_candidates=500, seed=20261007)),
          ("guard_500", "50 × 500 (мир ranking_guard)", dict(n_needs=50, n_candidates=500)),
          ("sens_600", "60 × 600 (размер анализа чувствительности)", dict(n_needs=60, n_candidates=600)),
          ("main_1", "200 × 2000, seed 20261006 (основной мир)", dict(n_needs=200, n_candidates=2000, seed=20261006)),
          ("main_2", "200 × 2000, seed 20261007 (второй мир)", dict(n_needs=200, n_candidates=2000, seed=20261007)))


def coverage(sc: dict, order: np.ndarray) -> dict:
    c = sc["comps"][:, :, COMP_KEYS.index("stack_required")]
    rows = [i for i in range(len(order)) if sc["has_req"][i]]
    top = np.stack([c[i, order[i, :5]] for i in rows])
    return {"best5": round(100 * float(top.max(1).mean()), 1), "mean5": round(100 * float(top.mean(1).mean()), 1)}


def paired_ci(a: np.ndarray, b: np.ndarray, seed: int, n_boot: int = 2000) -> list[float]:
    d = b - a
    idx = np.random.default_rng(seed).integers(0, len(d), size=(n_boot, len(d)))
    m = d[idx].mean(1)
    return [round(float(np.quantile(m, 0.025)), 4), round(float(np.quantile(m, 0.975)), 4)]


def run_world(key: str, title: str, kw: dict) -> dict:
    t0 = time.time()
    cfg = BenchConfig(**kw)
    world = generate(cfg)
    sc = score_world(world, _parsed(world))
    before_o = platform_orders(sc, above=False)
    after_o = platform_orders(sc, above=True)
    pb, pa = per_need(world.rel, before_o), per_need(world.rel, after_o)
    exact = (sc["vis"] == 2).sum(1)
    res = {"title": title, "config": {k: cfg.to_dict()[k] for k in ("seed", "n_needs", "n_candidates")},
           "exact_pool_median": int(np.median(exact)), "applied_needs": int(sc["above_on"].sum()),
           "changed_top10_needs": int(sum(1 for i in range(len(before_o))
                                          if not np.array_equal(before_o[i, :10], after_o[i, :10]))),
           "before": {m: round(float(pb[m].mean()), 4) for m in METRICS},
           "after": {m: round(float(pa[m].mean()), 4) for m in METRICS},
           "delta_ci95": {m: paired_ci(pb[m], pa[m], cfg.seed + 31) for m in ("p@5", "ndcg@10", "mrr")},
           "coverage_before": coverage(sc, before_o), "coverage_after": coverage(sc, after_o),
           "seconds": round(time.time() - t0)}
    res["not_worse"] = all(res["after"][m] >= res["before"][m] for m in METRICS)
    print(f"{key}: применено {res['applied_needs']} из {cfg.n_needs}, до {res['before']}, после {res['after']}, "
          f"покрытие {res['coverage_before']} → {res['coverage_after']}, {res['seconds']} с", flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="только малые миры, без записи")
    a = ap.parse_args()
    worlds = WORLDS[:4] if a.quick else WORLDS
    out = {"rule": {"min_exact": grade_above.MIN_EXACT, "keep": grade_above.KEEP, "algorithm": grade_above.ALGORITHM,
                    "flag": grade_above.FLAG, "enabled_in_product": grade_above.enabled()},
           "acceptance": "P@5, P@10, nDCG@5, nDCG@10, MRR «после» не ниже «до» в каждом мире",
           "no_fitting": True, "worlds": {k: run_world(k, t, kw) for k, t, kw in worlds}}
    out["not_worse_all"] = all(w["not_worse"] for w in out["worlds"].values())
    if not a.quick:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"→ {OUT.relative_to(ROOT)}; не хуже во всех мирах: {out['not_worse_all']}")


if __name__ == "__main__":
    main()
