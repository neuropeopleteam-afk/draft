"""Бенчмарк подбора на ОТЛОЖЕННЫХ мирах (21.10.2026): новые seed, которые не использовались ни при выборе весов,
ни при настройке правил подбора (веса продукта выбраны на мирах 20261006/20261007 — matching_bench.heldout).

Порядок, который нельзя нарушать:
  1. freeze — записать seed отложенных миров, конфиг и коммит кода в docs/realdata/bench_holdout_FREEZE.json и
     ЗАКОММИТИТЬ до прогона (seed выбраны до прогона и нигде в репозитории не встречались);
  2. run    — один прогон: тот же генератор мира (bench_world), тот же разбор потребностей и то же ранжирование, что
     в продукте (validation.matching_bench.run_methods → ranking.score_candidate); повторный прогон запрещён.

Синтетика проверяет механику подбора (истина известна), а не реальный рынок — подпись «модели, не люди».

  cd backend && python ../tools/realdata/bench_holdout.py freeze && git commit … && python ../tools/realdata/bench_holdout.py run
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

FREEZE = ROOT / "docs/realdata/bench_holdout_FREEZE.json"
OUT = ROOT / "docs/realdata/bench_holdout.json"
SEEDS = (77021021, 77021022)  # выбраны 21.10 до прогона; в репозитории раньше не встречались
NEEDS, CANDS = 200, 2000
METHODS = ("platform", "no_fsp", "no_test", "keywords_grade", "bm25", "random")


def git_head() -> str:
    if os.environ.get("CODE_COMMIT"):  # прогон на копии без .git (сервер «Москва»): коммит передаётся явно
        return os.environ["CODE_COMMIT"]
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def freeze() -> None:
    if FREEZE.exists():
        sys.exit("уже заморожено — новый отложенный прогон = новые seed и новый файл")
    from app.modules.matching.ranking import WEIGHTS, algorithm
    from app.modules.validation.bench_world import BenchConfig

    cfgs = [BenchConfig(seed=s, n_needs=NEEDS, n_candidates=CANDS).to_dict() for s in SEEDS]
    FREEZE.write_text(json.dumps({
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": list(SEEDS),
        "configs": cfgs, "weights": WEIGHTS, "algorithm": algorithm(), "code_before_run": git_head(),
        "methods": list(METHODS),
        "rule": "Seed выбраны до прогона и раньше не использовались; прогон один; веса и правила подбора после "
                "прогона на этих мирах не настраиваются."}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("заморожено:", SEEDS)


def run() -> None:
    if OUT.exists():
        sys.exit(f"{OUT.relative_to(ROOT)} уже есть — отложенные миры использованы")
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    from app.modules.matching.ranking import WEIGHTS, algorithm
    from app.modules.validation.bench_world import BenchConfig, bank_blocks, generate
    from app.modules.validation.matching_bench import _parsed, run_methods, summarize

    if list(SEEDS) != fz["seeds"] or WEIGHTS != fz["weights"]:
        sys.exit("seed или веса отличаются от замороженных")
    blocks = bank_blocks()
    worlds = []
    t0 = time.time()
    for s in SEEDS:
        cfg = BenchConfig(seed=s, n_needs=NEEDS, n_candidates=CANDS)
        w = generate(cfg, blocks)
        r = run_methods(w, _parsed(w), s, METHODS)
        sm = summarize(w, r, s)
        worlds.append({"seed": s, "n_needs": NEEDS, "n_candidates": CANDS, "metrics": sm["metrics"],
                       "paired_platform_minus": sm["paired_platform_minus"], "cpu_seconds": r["cpu_seconds"]})
        print(s, "P@5", sm["metrics"]["platform"]["p@5"], "MRR", sm["metrics"]["platform"]["mrr"], flush=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "freeze": fz, "code": git_head(),
        "algorithm": algorithm(), "weights": WEIGHTS, "worlds": worlds, "seconds": round(time.time() - t0, 1),
        "what": "Бенчмарк подбора на двух отложенных синтетических мирах (200 потребностей × 2000 модельных "
                "кандидатов, истина известна; модели, не люди). P@5 — доля релевантных (метка ≥ 2) в первой пятёрке, "
                "MRR — 1/место первого релевантного; 95 % ДИ — бутстреп по потребностям.",
        "recompute": "cd backend && python ../tools/realdata/bench_holdout.py run (один раз; новые seed — новый freeze)"},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("записано:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("freeze", "run"))
    {"freeze": freeze, "run": run}[ap.parse_args().cmd]()
