"""Параллельный прогон симуляции продукта: конфигурации × зёрна шардами (отдельные процессы), затем сведение.

Каждый шард — отдельный процесс ``python -m app.modules.validation.product_sim`` с переменными окружения
конфигурации (настройки продукта читаются при импорте приложения, поэтому смешивать конфигурации в одном процессе
нельзя). Шард — одно зерно; сведение — ``product_sim merge`` (метрики пересчитываются по всем строкам). Так одна и та же
команда даёт одинаковый результат на одном ядре и на 16: результат шарда зависит только от зерна и конфигурации.

Запуск (из backend/):
    python -m app.modules.validation.sim_runner --plan plan.json --workers 15 --out-dir /tmp/train
plan.json: {"phase": "train", "n_per_seed": 100, "seeds": [1101, …], "common_args": ["--retest"],
            "configs": {"K1": {"env": {"ASSESSMENT_SUBPOOLS": "1"}, "args": []}, …}}
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _shard(cfg_name: str, cfg: dict, seed: int, plan: dict, out_dir: Path) -> tuple[str, int, int, str]:
    out = out_dir / f"{cfg_name}__{seed}.json"
    if out.exists():
        return cfg_name, seed, 0, str(out)
    env = {**os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
    if cfg.get("module_args"):  # произвольный модуль (боты): один шард, {out} — путь результата
        cmd = [sys.executable, "-m"] + [str(x).replace("{out}", str(out)) for x in cfg["module_args"]]
    else:
        cmd = [sys.executable, "-m", "app.modules.validation.product_sim", "--phase", cfg.get("phase", plan["phase"]),
               "--n", str(cfg.get("n_per_seed", plan["n_per_seed"])), "--seeds", str(seed), "--out", str(out)]
        cmd += list(cfg.get("common_args", plan.get("common_args")) or []) + list(cfg.get("args") or [])
    log = out_dir / f"{cfg_name}__{seed}.log"
    with open(log, "w", encoding="utf-8") as f:
        rc = subprocess.call(cmd, env=env, stdout=f, stderr=subprocess.STDOUT)
    return cfg_name, seed, rc, str(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(c, cfg, s) for c, cfg in plan["configs"].items()
            for s in ([0] if cfg.get("module_args") else cfg.get("seeds", plan["seeds"]))]
    t0 = time.time()
    done: dict[str, list[str]] = {c: [] for c in plan["configs"]}
    fails = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_shard, c, cfg, s, plan, out_dir) for c, cfg, s in jobs]
        for k, f in enumerate(as_completed(futs), 1):
            c, s, rc, out = f.result()
            if rc == 0 and Path(out).exists():
                done[c].append(out)
            else:
                fails.append((c, s, rc))
            print(f"[{k}/{len(jobs)}] {c} seed {s} rc={rc} · {time.time() - t0:.0f} с", flush=True)
    summary = {}
    for c, files in done.items():
        if not files or plan["configs"][c].get("module_args"):
            continue
        merged = out_dir / f"{c}.json"
        subprocess.call([sys.executable, "-m", "app.modules.validation.product_sim", "merge", "--out", str(merged),
                         *sorted(files)])
        d = json.loads(merged.read_text(encoding="utf-8"))
        s = d["summary"]
        pick = ("confident_accuracy_main", "confident_share_main", "confident_accuracy_final", "confident_share_final",
                "false_confirm_all", "false_confirm_among_overclaim", "false_reject_among_true", "exact_grade_final",
                "exact_grade_final_not_underclaim", "within_one_final", "gross_error_2plus", "undecided_final",
                "followup_share", "oral_share", "extended_share", "false_reject_all", "exact_grade_final_5",
                "exact_grade_final_4", "exact_grade_main")
        fc, fr = ((s.get(k) or {}).get("value") for k in ("false_confirm_all", "false_reject_all"))
        summary[c] = {"n": s.get("n"), **{k: (s.get(k) or {}).get("value") for k in pick},
                      # критерий выбора конфигурации на TRAIN (протокол, 2.2б): L = 3 · FC + FR, FC ≤ 2,5 %
                      "loss_3fc_fr": round(3 * fc + fr, 4) if fc is not None and fr is not None else None,
                      "far_exact_grade_final": ((s.get("far_from_cut_0_25") or {}).get("exact_grade_final") or {}).get("value"),
                      "minutes_main": s.get("minutes_main"), "minutes_total": s.get("minutes_total"),
                      "items_main": s.get("items_main"), "retest_kappa_w": (d.get("retest") or {}).get("kappa_w_quadratic"),
                      "retest_exact": ((d.get("retest") or {}).get("exact_agreement") or {}).get("value"),
                      "engine_errors": (d.get("engine_errors") or {}).get("n"),
                      "env": plan["configs"][c].get("env"), "args": plan["configs"][c].get("args")}
    res = {"plan": plan, "summary": summary, "fails": fails, "elapsed_s": round(time.time() - t0, 1)}
    (out_dir / "SUMMARY.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
