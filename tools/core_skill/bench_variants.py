"""Я1: выбор политики признака «ядро роли» на бенчмарке со скрытой истиной (тот же мир, что make bench).

    cd backend && LLM_DISABLED=1 ../../../.venv/bin/python ../tools/core_skill/bench_variants.py [--needs 200 --candidates 2000]

Сравнивает порядок продукта без признака (флаг выкл.) и с признаком при политиках group / within / cap / penalty на
основном мире (seed 20261006) и втором мире (seed + 1). Парный бутстреп по потребностям. Результат —
docs/core_skill/bench_variants.json. Ничего не подбирается по истине автоматически: таблица — для решения человека.
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

from app.modules.matching import core_skill  # noqa: E402
from app.modules.validation.bench_world import BenchConfig, bank_blocks, generate  # noqa: E402
from app.modules.validation.matching_bench import (_ci, _parsed, boot_idx, per_need, platform_orders,  # noqa: E402
                                                   score_world)

VARIANTS = [("group", None), ("within", None), ("cap", 5), ("cap", 10), ("penalty", 0.1), ("penalty", 0.2),
            ("penalty", 0.3)]


def evaluate(world, sc, seed: int) -> dict:
    idx = boot_idx(len(world.needs), seed + 41)
    has_core = (sc["core_state"] >= 0).any(1)
    active = sc["core_absent"].any(1)
    base_o = platform_orders(sc, core=False)
    base = per_need(world.rel, base_o)
    out = {"needs": len(world.needs), "needs_with_core": int(has_core.sum()), "needs_active": int(active.sum()),
           "off": {m: _ci(base[m], idx) for m in ("p@5", "ndcg@10", "mrr")}}
    out["off"]["top5_core_absent"] = round(float(np.mean([sc["core_absent"][i, base_o[i, :5]].mean()
                                                          for i in range(len(base_o)) if active[i]] or [0])), 4)
    for pol, val in VARIANTS:
        name = pol if val is None else f"{pol}_{val}"
        old = (core_skill.CAP_PLACE, core_skill.PENALTY)
        if pol == "cap":
            core_skill.CAP_PLACE = val
        if pol == "penalty":
            core_skill.PENALTY = val
        o = platform_orders(sc, core=True, core_policy=pol)
        core_skill.CAP_PLACE, core_skill.PENALTY = old
        pn = per_need(world.rel, o)
        res = {m: _ci(pn[m], idx) for m in ("p@5", "ndcg@10", "mrr")}
        res["diff"] = {m: _ci(pn[m] - base[m], idx) for m in ("p@5", "ndcg@10", "mrr")}
        act = np.where(active)[0]
        res["diff_active_needs"] = {m: round(float((pn[m] - base[m])[act].mean()), 4) for m in ("p@5", "ndcg@10")}
        res["top5_core_absent"] = round(float(np.mean([sc["core_absent"][i, o[i, :5]].mean() for i in act] or [0])), 4)
        res["needs_changed_top10"] = int(sum(1 for i in range(len(o)) if not np.array_equal(o[i, :10], base_o[i, :10])))
        out[name] = res
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--needs", type=int, default=200)
    ap.add_argument("--candidates", type=int, default=2000)
    ap.add_argument("--out", default=str(ROOT / "docs/core_skill/bench_variants.json"))
    a = ap.parse_args()
    t0 = time.time()
    blocks = bank_blocks()
    res = {"config": {"needs": a.needs, "candidates": a.candidates}}
    for name, seed in (("world", 20261006), ("world2", 20261007)):
        cfg = BenchConfig(seed=seed, n_needs=a.needs, n_candidates=a.candidates)
        w = generate(cfg, blocks)
        sc = score_world(w, _parsed(w))
        res[name] = evaluate(w, sc, seed)
        print(name, json.dumps({k: (v["diff"]["ndcg@10"]["mean"], v["diff"]["p@5"]["mean"]) if isinstance(v, dict) and "diff" in v
                                else v for k, v in res[name].items() if k not in ("off",)}, ensure_ascii=False), flush=True)
        print("   off", res[name]["off"]["ndcg@10"]["mean"], res[name]["off"]["p@5"]["mean"], flush=True)
    res["seconds"] = round(time.time() - t0, 1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("→", a.out, res["seconds"], "с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
