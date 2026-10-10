"""Я11 (С3-3): A/B весов навыков на бенчмарке со скрытой истиной (мир по умолчанию 200 × 2000 и мир seed+1).

«до» — прежнее правило (NEED_LIST_WEIGHTS=0: 1,0 → 0,6 по порядку упоминания, общий навык ×0,8), «после» — веса по
перечислениям (NEED_LIST_WEIGHTS=1). Порядок — продукт (match-v1.1, ярусы обязательного). Разница по потребностям —
парный бутстреп 2000 повторов, 95 % ДИ. Параметры не подбираются по меткам. Без записи в docs/.

  cd backend && python ../tools/realdata/list_weights_ab.py [--needs 200 --candidates 2000] [--out /tmp/x.json]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.validation.bench_world import BenchConfig, generate  # noqa: E402
from app.modules.validation.matching_bench import _parsed, per_need, platform_orders, score_world  # noqa: E402


def run(world, flag: str) -> dict:
    os.environ["NEED_LIST_WEIGHTS"] = flag
    return per_need(world.rel, platform_orders(score_world(world, _parsed(world)), must_first=True))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--needs", type=int, default=BenchConfig.n_needs)
    ap.add_argument("--candidates", type=int, default=BenchConfig.n_candidates)
    ap.add_argument("--out")
    a = ap.parse_args()
    rng = np.random.default_rng(0)
    out = {}
    for seed in (BenchConfig.seed, BenchConfig.seed + 1):
        world = generate(BenchConfig(seed=seed, n_needs=a.needs, n_candidates=a.candidates))
        old, new = run(world, "0"), run(world, "1")
        res = {}
        for k in old:
            d = np.asarray(new[k]) - np.asarray(old[k])
            boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
            res[k] = {"before": round(float(np.mean(old[k])), 4), "after": round(float(np.mean(new[k])), 4),
                      "delta": round(float(d.mean()), 4),
                      "ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
                      "needs_better": int((d > 1e-9).sum()), "needs_worse": int((d < -1e-9).sum())}
        out[f"seed{seed}_{a.needs}x{a.candidates}"] = res
        print(seed, json.dumps(res, ensure_ascii=False), flush=True)
    os.environ.pop("NEED_LIST_WEIGHTS", None)
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
