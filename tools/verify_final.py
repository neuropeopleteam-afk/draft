"""«Проверь сам»: воспроизвести итоговый прогон FINAL №2 на одном зерне и сверить с опубликованными строками.

    python tools/verify_final.py                    # F_calibrated, зерно 4401 (≈ 300 модельных кандидатов)
    python tools/verify_final.py --config S_T --seed 5501

Что делает (из корня чистого клона, без ключей и сети):
1. Берёт план прогона из docs/validation/final_2110/SUMMARY_main.json (или SUMMARY_b.json) — те же аргументы, что у
   раннера sim_runner, и тот же ожидаемый хэш банка (--expect-bank-hash: прогон не стартует на другом банке).
2. Запускает `python -m app.modules.validation.product_sim` на одном зерне (это повтор опубликованного прогона,
   а не новый: результат шарда зависит только от зерна, конфигурации и банка).
3. Сравнивает строки (каждый модельный кандидат: истинный грейд, заявка, вердикт, итоговый грейд, θ…) с
   docs/validation/final_2110/<config>.rows.jsonl.gz для этого зерна и печатает метрики зерна по обеим сторонам.
Код выхода 0 — все строки совпали; печатает хэш банка (content_hash манифеста), с которым шёл прогон.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "docs" / "validation" / "final_2110"
KEYS = ("n", "confident_accuracy_main", "confident_share_main", "false_confirm_all", "false_reject_all",
        "exact_grade_final", "within_one_final", "undecided_final")


def plan_for(config: str) -> tuple[dict, dict]:
    for name in ("SUMMARY_main.json", "SUMMARY_b.json"):
        p = FINAL / name
        if p.exists():
            plan = json.loads(p.read_text(encoding="utf-8"))["plan"]
            if config in plan["configs"]:
                return plan, plan["configs"][config]
    raise SystemExit(f"конфигурации {config} нет в планах {FINAL}/SUMMARY_*.json")


def canon(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="F_calibrated")
    ap.add_argument("--seed", type=int, default=0, help="зерно из плана (по умолчанию — первое)")
    a = ap.parse_args(argv)
    plan, cfg = plan_for(a.config)
    if cfg.get("module_args"):
        raise SystemExit("боты (B_*) этим скриптом не проверяются — выберите F_* или S_T")
    seeds = cfg.get("seeds", plan["seeds"])
    seed = a.seed or seeds[0]
    if seed not in seeds:
        raise SystemExit(f"зерно {seed} не из плана {a.config}: {seeds}")
    rows_file = FINAL / f"{a.config}.rows.jsonl.gz"
    pub = [json.loads(x) for x in gzip.open(rows_file, "rt", encoding="utf-8")]
    pub = [r for r in pub if int(r.get("seed", -1)) == seed]
    out = Path(tempfile.mkdtemp(prefix="verify_final_")) / f"{a.config}__{seed}.json"
    cmd = [sys.executable, "-m", "app.modules.validation.product_sim", "--phase", cfg.get("phase", plan["phase"]),
           "--n", str(cfg.get("n_per_seed", plan["n_per_seed"])), "--seeds", str(seed), "--out", str(out)]
    cmd += list(cfg.get("common_args", plan.get("common_args")) or []) + list(cfg.get("args") or [])
    env = {**os.environ, "LLM_DISABLED": "true", **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
    print(f"FINAL №2 · {a.config} · зерно {seed} · модельных кандидатов в публикации: {len(pub)}", flush=True)
    print("команда (из backend/):", " ".join(cmd[1:]), flush=True)
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL)
    if rc != 0 or not out.exists():
        print(f"прогон не завершился (код {rc})"); return 2
    d = json.loads(out.read_text(encoding="utf-8"))
    mine = d.get("_raw", {}).get("rows") or d.get("rows") or []
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("LLM_DISABLED", "true")
    from app.modules.assessment.bank_engine import BankEngine  # noqa: E402
    from app.modules.validation.product_sim import summarize  # noqa: E402

    e = BankEngine()
    got = (getattr(e, "manifest", None) or {}).get("content_hash")
    s_pub, s_mine = summarize(pub), summarize(mine)
    print(f"повтор занял {time.time() - t0:.0f} с; банк: content_hash {got} (ожидался {cfg_hash(cfg)}, "
          f"семейств {len(getattr(e, 'families', None) or getattr(e, 'specs', None) or [])})")
    print(f"{'метрика':34} {'опубликовано':>13} {'повтор':>10}")
    for k in KEYS:
        v1 = s_pub.get(k, {}).get("value") if isinstance(s_pub.get(k), dict) else s_pub.get(k)
        v2 = s_mine.get(k, {}).get("value") if isinstance(s_mine.get(k), dict) else s_mine.get(k)
        print(f"{k:34} {str(v1):>13} {str(v2):>10}{'' if v1 == v2 else '   ≠'}")
    a_set, b_set = sorted(map(canon, pub)), sorted(map(canon, mine))
    same = a_set == b_set
    diff = len(set(a_set) ^ set(b_set))
    print(f"строки: опубликовано {len(pub)}, повтор {len(mine)}, расхождений {diff} → {'СОВПАДАЕТ' if same else 'НЕ СОВПАДАЕТ'}")
    return 0 if same else 1


def cfg_hash(cfg: dict) -> str:
    args = list(cfg.get("args") or [])
    return args[args.index("--expect-bank-hash") + 1] if "--expect-bank-hash" in args else "?"


if __name__ == "__main__":
    sys.exit(main())
