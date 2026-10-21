"""«Решатель без знаний» по семействам (А3, 21.10.2026): какие семейства дают хвост угадываемости.

Использует ту же эвристику, что tools/bank_audit.py (`_guess`), но печатает точность каждой эвристики по
каждому семейству группы (other — без `_solve_`/`_fwd_` в id; inverse; forward; all). Лучшая эвристика на одном
семействе завышена (максимум из 9 на N зёрнах), поэтому смотреть сумму по группе, а не отдельные семейства.

Запуск из backend:
    PYTHONPATH=. python3 ../tools/bank_guess_by_family.py --seeds 40 --group other --top 25 [--out файл.json]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import multiprocessing as mp
import statistics
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("bank_audit", Path(__file__).with_name("bank_audit.py"))
bank_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bank_audit)  # type: ignore[union-attr]


def _kind(fid: str) -> str:
    return "inverse" if "_solve_" in fid else ("forward" if "_fwd_" in fid else "other")


def _one(args):
    fid, seeds = args
    from assessment_bank.registry import generate
    gs = []
    for s in range(1, seeds + 1):
        try:
            g = bank_audit._guess(generate(fid, s))
        except Exception:  # noqa: BLE001
            g = None
        if g:
            gs.append(g)
    return fid, gs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--group", default="other", choices=["other", "inverse", "forward", "all"])
    ap.add_argument("--families", nargs="*")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out")
    a = ap.parse_args()
    from assessment_bank.registry import load_specs
    specs = load_specs()
    fids = a.families or [f for f, s in sorted(specs.items()) if s.format == "mcq_concept"
                          and (a.group == "all" or _kind(f) == a.group)]
    with mp.Pool(a.jobs) as pool:
        res = pool.map(_one, [(f, a.seeds) for f in fids], chunksize=8)
    allg = collections.defaultdict(list)
    rows = []
    for fid, gs in res:
        if not gs:
            continue
        per = {h: statistics.mean(g[h] for g in gs) for h in gs[0]}
        for g in gs:
            for h, x in g.items():
                allg[h].append(x)
        best = max((h for h in per if h != "chance"), key=lambda h: per[h])
        rows.append({"family_id": fid, "n": len(gs), "chance": round(per["chance"], 3), "best": best,
                     "best_acc": round(per[best], 3), "excess": round(per[best] - per["chance"], 3),
                     "by_heuristic": {h: round(x, 3) for h, x in per.items()}})
    rows.sort(key=lambda r: -r["excess"])
    summ = {h: round(statistics.mean(xs), 4) for h, xs in allg.items()}
    print(json.dumps({"group": a.group, "n_families": len(rows), "n_variants": len(allg.get("chance", [])),
                      "summary": summ}, ensure_ascii=False))
    for r in rows[:a.top]:
        print(f"{r['excess']:+.3f} {r['best_acc']:.3f} ({r['best']}) шанс {r['chance']:.3f}  {r['family_id']}")
    if a.out:
        Path(a.out).write_text(json.dumps({"command": " ".join(sys.argv), "summary": summ, "families": rows},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
