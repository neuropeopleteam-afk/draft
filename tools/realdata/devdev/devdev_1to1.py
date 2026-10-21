"""«Один в один» на открытом генераторе Dev_dev: FREEZE до прогона и один прогон (как bench_holdout2).

Их генератор и их метки не меняются (их репозиторий на зафиксированном коммите, MIT). На каждом зерне: их мир, их тест,
их три выдачи (IT Match, по резюме, случайный — их числа воспроизводятся до знака) и наша выдача четвёртой в той же
процедуре (rank_ours.py). Строки протокола (DEVDEV_PROTOCOL.md):
  main  — конфигурация финального стенда (match-v2 + расширение каталога + Lead), выбор работодателя по умолчанию;
  exact — то же + выбор работодателя «строго запрошенный грейд» (filters.grade_exact) — отдельной строкой;
  base  — без расширения каталога (справочно).
Отложенные зёрна: 2026 (их опубликованный отчёт) и 5 свежих. Зёрна разработки адаптера: 1, 2, 3.
Доверительные интервалы — бутстрэп по вакансиям (2000 повторов), разность «мы − IT Match» парная по вакансии.

  python3 tools/realdata/devdev/devdev_1to1.py dev    --their <repo>/backend --py <их python>   # зёрна 1–3, в /tmp
  python3 tools/realdata/devdev/devdev_1to1.py freeze --their <repo>/backend
  python3 tools/realdata/devdev/devdev_1to1.py run    --their <repo>/backend --py <их python>   # ОДИН раз
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "docs/realdata/devdev_1to1.json"
FREEZE = ROOT / "docs/realdata/devdev_1to1_FREEZE.json"
PROTOCOL = ROOT / "docs/realdata/DEVDEV_PROTOCOL.md"
THEIR_COMMIT = "dec3f95449d2f89972bd99f5b6fb661ddd836cea"
THEIR_REPO = "https://github.com/LaimOr127/Digital-platform-aggregator-of-IT-vacancies-FSP-"
HOLDOUT_SEEDS = (2026, 77021161, 77021162, 77021163, 77021164, 77021165)
DEV_SEEDS = (1, 2, 3)
ROWS = {"main": {"config": "final", "mode": "default"}, "exact": {"config": "final", "mode": "grade_exact"},
        "base": {"config": "base", "mode": "default"}}
THETA = "last"
METRICS = ("p5", "p10", "ndcg10", "rr", "overrated10")
BOOT = {"reps": 2000, "seed": 7702116}
FROZEN_FILES = ("tools/realdata/devdev/export_world.py", "tools/realdata/devdev/rank_ours.py",
                "tools/realdata/devdev/devdev_1to1.py", "tools/realdata/bench2.py",
                "docs/realdata/DEVDEV_PROTOCOL.md")
FROZEN_DIRS = ("backend/app/modules/matching", "backend/app/modules/catalog", "backend/app/modules/profiles",
               "backend/app/modules/fsp", "backend/app/modules/validation/bench_world.py")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha_path(rel: str) -> str:
    base = ROOT / rel
    if base.is_file():
        return sha(base)
    h = hashlib.sha256()
    for f in sorted(x for x in base.rglob("*") if x.is_file() and "__pycache__" not in x.parts and x.suffix != ".pyc"):
        h.update(str(f.relative_to(base)).encode())
        h.update(sha(f).encode())
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def their_head(their: str) -> str:
    return subprocess.check_output(["git", "-C", their, "rev-parse", "HEAD"], text=True).strip()


def export(seed: int, their: str, py: str, tmp: Path) -> Path:
    out = tmp / f"dd_{seed}.json"
    subprocess.run([py, str(HERE / "export_world.py"), "--seed", str(seed), "--out", str(out)], cwd=their, check=True,
                   stdout=subprocess.DEVNULL)
    return out


def rank(world: Path, row: str, tmp: Path) -> dict:
    out = tmp / f"{world.stem}_{row}.json"
    r = ROWS[row]
    subprocess.run([sys.executable, str(HERE / "rank_ours.py"), "--world", str(world), "--config", r["config"],
                    "--mode", r["mode"], "--theta", THETA, "--out", str(out)], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return json.loads(out.read_text(encoding="utf-8"))


def boot(ours: list[dict], theirs: list[dict]) -> dict:
    rng = random.Random(BOOT["seed"])
    n = len(ours)
    res = {}
    for m in METRICS:
        a = [x[m] for x in ours]
        b = [x[m] for x in theirs]
        da, dd = [], []
        for _ in range(BOOT["reps"]):
            idx = [rng.randrange(n) for _ in range(n)]
            da.append(statistics.fmean(a[i] for i in idx))
            dd.append(statistics.fmean(a[i] - b[i] for i in idx))
        da.sort()
        dd.sort()
        q = lambda v, p: v[int(p * (len(v) - 1))]  # noqa: E731
        res[m] = {"ours": round(statistics.fmean(a), 4), "ours_ci": [round(q(da, .025), 4), round(q(da, .975), 4)],
                  "it_match": round(statistics.fmean(b), 4),
                  "diff": round(statistics.fmean(x - y for x, y in zip(a, b)), 4),
                  "diff_ci": [round(q(dd, .025), 4), round(q(dd, .975), 4)]}
    return res


def evaluate(seeds, their: str, py: str, tmp: Path) -> dict:
    per_seed, pooled = {}, {r: [] for r in ROWS}
    pooled_their = []
    for s in seeds:
        w = export(s, their, py, tmp)
        world = json.loads(w.read_text(encoding="utf-8"))
        theirs_v = world["their_per_vacancy"]["IT Match"]
        pooled_their += theirs_v
        per_seed[str(s)] = {"their": world["their_metrics"]}
        for row in ROWS:
            r = rank(w, row, tmp)
            ours_v = [{"p5": x["p5"], "p10": x["p10"], "ndcg10": x["ndcg10"], "rr": x["rr"],
                       "overrated10": x["overrated10"]} for x in r["per_vacancy"]]
            pooled[row] += ours_v
            per_seed[str(s)][row] = {"ours": {k: round(v, 4) for k, v in r["ours"].items()},
                                     "parse_ok_share": r["parse_ok_share"],
                                     "candidates_in_catalog": r["candidates_in_catalog"],
                                     "per_vacancy": r["per_vacancy"]}
    return {"per_seed": per_seed, "pooled": {row: boot(pooled[row], pooled_their) for row in ROWS},
            "n_vacancies": len(pooled_their)}


def cmd_dev(a) -> None:
    with tempfile.TemporaryDirectory() as t:
        res = evaluate(DEV_SEEDS, a.their, a.py, Path(t))
    print(json.dumps({"dev_seeds": DEV_SEEDS, "pooled": res["pooled"]}, ensure_ascii=False, indent=1))


def cmd_freeze(a) -> None:
    head = their_head(a.their)
    assert head == THEIR_COMMIT, f"их репозиторий не на зафиксированном коммите: {head}"
    doc = {"what": "FREEZE сравнения «один в один» на генераторе Dev_dev (до прогона)",
           "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "git_head_before_freeze_commit": git_head(), "their_repo": THEIR_REPO, "their_commit": THEIR_COMMIT,
           "holdout_seeds": list(HOLDOUT_SEEDS), "dev_seeds_never_these": list(DEV_SEEDS), "rows": ROWS,
           "theta": THETA, "metrics": list(METRICS), "bootstrap": BOOT,
           "files_sha256": {f: sha_path(f) for f in FROZEN_FILES}, "dirs_sha256": {d: sha_path(d) for d in FROZEN_DIRS},
           "rule": "один прогон: run отказывается при несовпадении любого хэша и при уже существующем результате"}
    FREEZE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"freeze": str(FREEZE.relative_to(ROOT)), "sha256": sha(FREEZE)}, ensure_ascii=False))


def cmd_run(a) -> None:
    if OUT.exists():
        sys.exit("результат уже есть — повторный прогон запрещён (новый прогон — новые зёрна и новый FREEZE)")
    fr = json.loads(FREEZE.read_text(encoding="utf-8"))
    bad = [f for f, h in fr["files_sha256"].items() if sha_path(f) != h] + \
          [d for d, h in fr["dirs_sha256"].items() if sha_path(d) != h]
    if bad:
        sys.exit(f"не совпадают хэши FREEZE: {bad}")
    assert their_head(a.their) == fr["their_commit"]
    t0 = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as t:
        res = evaluate(tuple(fr["holdout_seeds"]), a.their, a.py, Path(t))
    doc = {"what": "Сравнение «один в один» на открытом генераторе Dev_dev (MIT): их мир, их тест, их метки; наш подбор "
                   "четвёртой выдачей в их процедуре оценки. Синтетика (модель), не люди.",
           "protocol": str(PROTOCOL.relative_to(ROOT)), "freeze_sha256": sha(FREEZE), "git_head": git_head(),
           "their_repo": fr["their_repo"], "their_commit": fr["their_commit"], "run_at": t0.isoformat(timespec="seconds"),
           "seeds": fr["holdout_seeds"], "rows": fr["rows"], "theta": fr["theta"], **res,
           "recompute": "python3 tools/realdata/devdev/devdev_1to1.py run --their <их repo>/backend --py <python с их "
                        "зависимостями> (один раз; повтор — новые зёрна и новый FREEZE)"}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT.relative_to(ROOT)), "pooled": res["pooled"]["main"]}, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("dev", "freeze", "run"))
    ap.add_argument("--their", required=True, help="каталог backend их репозитория на коммите THEIR_COMMIT")
    ap.add_argument("--py", default="python3", help="python с их зависимостями (requirements.txt)")
    a = ap.parse_args()
    {"dev": cmd_dev, "freeze": cmd_freeze, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
