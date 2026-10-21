"""«Решатель без знаний» по семействам (А3, 21.10.2026): какие семейства дают хвост угадываемости.

Использует ту же эвристику, что tools/bank_audit.py (`_guess`), но печатает точность каждой эвристики по
каждому семейству группы (other — без `_solve_`/`_fwd_` в id; inverse; forward; all). Лучшая эвристика на одном
семействе завышена (максимум из 9 на N зёрнах), поэтому смотреть сумму по группе, а не отдельные семейства.

Запуск из backend:
    PYTHONPATH=. python3 ../tools/bank_guess_by_family.py --seeds 40 --group other --top 25 [--out файл.json]
    # зёрна разработки (не те, на которых отчёт) и случайные зёрна как у кандидатов:
    PYTHONPATH=. python3 ../tools/bank_guess_by_family.py --seeds 400 --seed-start 1001 --group other
    PYTHONPATH=. python3 ../tools/bank_guess_by_family.py --seeds 400 --seed-mode random --seed-start 7 --group other
Печатает и ранг ключа по величине среди вариантов («r/k»: r ловушек меньше ключа из k вариантов) — при равномерном
ранге позиционные эвристики (медиана, минимум, максимум) дают уровень случайного выбора.
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


def _seed_list(n: int, start: int, mode: str) -> list[int]:
    """Зёрна: подряд start..start+n−1 (как в отчётах банка) или случайные из диапазона выдачи кандидатам
    (bank_engine: 10 000 000 … 2³¹ − 1; ГСЧ с фиксированным ключом ``start`` — повторяемо)."""
    if mode == "random":
        import random
        r = random.Random(f"bank_guess:{start}")
        return [10_000_000 + r.randrange(2 ** 31 - 1 - 10_000_000) for _ in range(n)]
    return list(range(start, start + n))


def _rank(v) -> int | None:
    """Ранг ключа по величине среди вариантов (0 — наименьший); None — варианты не числовые."""
    vals = [bank_audit._num(o.text) for o in v.options or []]
    if not vals or any(x is None for x in vals):
        return None
    kv = next((x for o, x in zip(v.options, vals) if o.id == v.answer_key.value), None)
    return None if kv is None else sum(1 for x in vals if x < kv)


def _one(args):
    fid, seeds = args
    from assessment_bank.registry import generate
    gs, ranks = [], []
    for s in seeds:
        try:
            v = generate(fid, s)
            g = bank_audit._guess(v)
        except Exception:  # noqa: BLE001
            g, v = None, None
        if g:
            gs.append(g)
            r = _rank(v)
            if r is not None:
                ranks.append((r, len(v.options)))
    return fid, gs, ranks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--seed-start", type=int, default=1, help="первое зерно (по умолчанию 1, как в отчётах)")
    ap.add_argument("--seed-mode", default="range", choices=["range", "random"],
                    help="range — подряд; random — случайные зёрна диапазона выдачи (ключ ГСЧ = --seed-start)")
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
        seeds = _seed_list(a.seeds, a.seed_start, a.seed_mode)
        res = pool.map(_one, [(f, seeds) for f in fids], chunksize=8)
    allg = collections.defaultdict(list)
    rows = []
    for fid, gs, ranks in res:
        if not gs:
            continue
        per = {h: statistics.mean(g[h] for g in gs) for h in gs[0]}
        for g in gs:
            for h, x in g.items():
                allg[h].append(x)
        best = max((h for h in per if h != "chance"), key=lambda h: per[h])
        rows.append({"family_id": fid, "n": len(gs), "chance": round(per["chance"], 3), "best": best,
                     "best_acc": round(per[best], 3), "excess": round(per[best] - per["chance"], 3),
                     "by_heuristic": {h: round(x, 3) for h, x in per.items()},
                     "key_rank": dict(sorted(collections.Counter(f"{r}/{k}" for r, k in ranks).items()))})
    rows.sort(key=lambda r: -r["excess"])
    summ = {h: round(statistics.mean(xs), 4) for h, xs in allg.items()}
    print(json.dumps({"group": a.group, "n_families": len(rows), "n_variants": len(allg.get("chance", [])),
                      "seeds": f"{a.seed_mode}:{a.seed_start}+{a.seeds}", "summary": summ}, ensure_ascii=False))
    for r in rows[:a.top]:
        print(f"{r['excess']:+.3f} {r['best_acc']:.3f} ({r['best']}) шанс {r['chance']:.3f}  {r['family_id']}"
              f"  ранг ключа {r['key_rank']}")
    if a.out:
        Path(a.out).write_text(json.dumps({"command": " ".join(sys.argv), "seeds": f"{a.seed_mode}:{a.seed_start}+{a.seeds}",
                                           "summary": summ, "families": rows},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
