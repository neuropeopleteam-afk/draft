#!/usr/bin/env python3
"""Бенчмарк подбора match-v2 на ОТЛОЖЕННЫХ мирах — протокол docs/realdata/bench_holdout2_PROTOCOL.md.

Два шага, порядок обязателен:
  python3 tools/realdata/bench_holdout2.py freeze   # до прогона: SHA-256 протокола, кода, весов и списка зёрен →
                                                    # docs/realdata/bench_holdout2_FREEZE.json (коммит ДО прогона)
  python3 tools/realdata/bench_holdout2.py run      # ОДИН прогон: сверяет хэши с FREEZE, отказывается, если файл
                                                    # результата уже есть; пишет docs/realdata/bench_holdout2.json
Миры (зёрна — только здесь, на разработке не использовались): S-M 77021131, 77021132, 77021135 (+ «идеальный тест»
на тех же зёрнах), жёсткий 77021141, 77021142. Каждый мир — отдельный процесс (tools/realdata/bench2.py).
Сводка: по каждому миру и объединённо по условию; 95 % ДИ — бутстрэп по потребностям (2000 повторов, зерно 7702113),
парные разности match-v2 − база.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FREEZE = ROOT / "docs/realdata/bench_holdout2_FREEZE.json"
RESULT = ROOT / "docs/realdata/bench_holdout2.json"
WORLDS = {"sm": (77021131, 77021132, 77021135), "sm_ideal": (77021131, 77021132, 77021135),
          "sm_s55": (77021131, 77021132, 77021135), "hard": (77021141, 77021142)}
# проверка конвейера до FREEZE — только на мирах разработки (те же, что для обучения весов), результат — во временный файл
DEV_WORLDS = {"sm": (31000001, 31000002), "sm_ideal": (31000001,), "sm_s55": (31000001,), "hard": (31000001,)}
LABELS = ("rel", "l2")
FROZEN_FILES = (
    "docs/realdata/bench_holdout2_PROTOCOL.md",
    "tools/realdata/bench_holdout2.py",
    "tools/realdata/bench2.py",
    "backend/app/modules/matching/ranking.py",
    "backend/app/modules/matching/ltr.py",
    "backend/app/modules/matching/ltr_weights.json",
    "backend/app/modules/matching/need_parser.py",
    "backend/app/modules/matching/grade_above.py",
    "backend/app/modules/matching/fsp_factor.py",
    "backend/app/modules/validation/bench_world.py",
    "backend/app/modules/validation/matching_bench.py",
    "backend/app/modules/catalog/ext.py",
    "backend/app/modules/profiles/facts.py",
)
METHODS = ("match_v2", "match_v2_doz", "match_v2_doz70", "match_v13", "bm25", "words_grade", "tfidf_filter", "random",
           "oracle_pool")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def cmd_freeze(a) -> None:
    files = {f: sha(ROOT / f) for f in FROZEN_FILES}
    doc = {"what": "FREEZE отложенного бенчмарка подбора match-v2 (до прогона)", "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "git_head_before_freeze_commit": git_head(), "worlds": {k: list(v) for k, v in WORLDS.items()},
           "labels": list(LABELS), "methods": list(METHODS), "bootstrap": {"reps": 2000, "seed": 7702113},
           "files_sha256": files, "dev_seeds_never_these": "31000001–31000006, 20261006, 20261007 (обучение весов)",
           "rule": "один прогон: run отказывается при несовпадении любого хэша и при уже существующем результате"}
    FREEZE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    h = sha(FREEZE)
    print(json.dumps({"freeze": str(FREEZE.relative_to(ROOT)), "sha256": h, "files": len(files)}, ensure_ascii=False))


def _world(cond: str, seed: int, tmp: Path) -> dict:
    out = tmp / f"{cond}_{seed}.json"
    env = dict(os.environ, PYTHONHASHSEED="0")
    t0 = time.time()
    subprocess.run([sys.executable, str(HERE / "bench2.py"), "--cond", cond, "--seed", str(seed),
                    "--labels", ",".join(LABELS), "--out", str(out)], check=True, env=env, cwd=str(ROOT))
    r = json.loads(out.read_text(encoding="utf-8"))
    r["seconds"] = round(time.time() - t0, 1)
    return r


def aggregate(worlds: list[dict], label: str) -> dict:
    sys.path.insert(0, str(HERE))
    import bench2

    per = {m: [] for m in METHODS}
    by_world = []
    for w in worlds:
        L = w["labels"][label]
        for m in METHODS:
            per[m] += L["per_need"][m]
        by_world.append({"seed": w["seed"], "digest": w["digest"], "n": w["n"], "m": w["m"], "doz_cost": L.get("doz_cost"),
                         "config": w.get("config"),
                         "summary": {m: L["summary"][m] for m in METHODS},
                         "parse": {"direction_ok": round(sum(x["dir_ok"] for x in L["info"]) / len(L["info"]), 4),
                                   "grade_ok": round(sum(x["grade_ok"] for x in L["info"]) / len(L["info"]), 4)}})
    ci = bench2.bootstrap(per, list(METHODS), base="match_v2")
    ci_doz = bench2.bootstrap(per, ["match_v2_doz", "match_v2"], base="match_v2_doz")
    return {"pooled": ci, "doz_vs_v2": ci_doz["match_v2"], "by_world": by_world, "n_needs": len(per["match_v2"])}


def cmd_run(a) -> None:
    worlds = DEV_WORLDS if a.dev else WORLDS
    if not a.dev:
        if RESULT.exists():
            sys.exit(f"ОТКАЗ: {RESULT.relative_to(ROOT)} уже есть — прогон на отложенных один")
        fr = json.loads(FREEZE.read_text(encoding="utf-8"))
        bad = {f: (h, sha(ROOT / f)) for f, h in fr["files_sha256"].items() if sha(ROOT / f) != h}
        if bad:
            sys.exit("ОТКАЗ: файлы изменены после FREEZE: " + ", ".join(bad))
    tmp = Path(a.tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    jobs = [(c, s) for c, ss in worlds.items() for s in ss]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        res = list(ex.map(lambda cs: _world(cs[0], cs[1], tmp), jobs))
    out = {"what": ("ПРОВЕРКА КОНВЕЙЕРА на мирах разработки (не отчётная цифра)" if a.dev else
                    "Бенчмарк подбора match-v2 на отложенных мирах (один прогон после FREEZE)"),
           "protocol": "docs/realdata/bench_holdout2_PROTOCOL.md", "freeze_sha256": None if a.dev else sha(FREEZE),
           "freeze_files_ok": not a.dev, "git_head": git_head(), "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "seconds": round(time.time() - t0, 1), "worlds": {k: list(v) for k, v in worlds.items()},
           "world_seconds": {f"{r['cond']}_{r['seed']}": r["seconds"] for r in res}, "conditions": {}}
    for cond in worlds:
        ws = [r for r in res if r["cond"] == cond]
        out["conditions"][cond] = {lb: aggregate(ws, lb) for lb in LABELS}
    target = tmp / "dev_check.json" if a.dev else RESULT
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    brief = {c: {lb: {m: v["pooled"][m]["ndcg10"]["mean"] for m in ("match_v2", "match_v2_doz", "match_v13", "bm25")}
                 for lb, v in d.items()} for c, d in out["conditions"].items()}
    print(json.dumps({"result": str(target), "ndcg10": brief}, ensure_ascii=False, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("freeze")
    r = sub.add_parser("run")
    r.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2))))
    r.add_argument("--tmp", default="/tmp/bench_holdout2")
    r.add_argument("--dev", action="store_true", help="проверка конвейера на мирах разработки (без FREEZE, во временный файл)")
    a = ap.parse_args()
    {"freeze": cmd_freeze, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
