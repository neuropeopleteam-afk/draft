#!/usr/bin/env python3
"""Калибровка коэффициентов Sympson — Hetter K_f для конфигурации теста платформы.

Для каждого направления: n_sessions симулированных сессий × iterations итераций (Sympson & Hetter, 1985):
K_f = r_max / P(выбор f), если P > r_max. Пишет backend/app/modules/assessment/exposure_k.json
(его читает движок, см. app/modules/assessment/exposure.py). Пересчитывать после изменения банка:

    cd backend && python ../tools/calibrate_exposure.py [--r-max 0.3] [--sessions 300] [--iterations 6]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.modules.assessment.bank_engine import bank_manifest  # noqa: E402
from app.modules.validation.sim import DIRECTIONS, AppConfig, calibrate_k, make_pool  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r-max", type=float, default=0.3)
    ap.add_argument("--sessions", type=int, default=300)
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261005)
    a = ap.parse_args()
    cfg = AppConfig()
    pool = make_pool(cfg.subpools)
    out = {"method": "Sympson-Hetter (безусловный), калибровка симуляцией", "r_max": a.r_max,
           "sessions_per_iteration": a.sessions, "iterations": a.iterations, "seed": a.seed,
           "config": {"max_items": cfg.max_items, "max_minutes": cfg.max_minutes, "subpools": cfg.subpools,
                      "max_per_format": cfg.max_per_format},
           "bank": {k: bank_manifest().get(k) for k in ("content_hash", "n_families", "commit")},
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "k": {}, "history": {}}
    for i, d in enumerate(DIRECTIONS):
        t0 = time.time()
        k, hist = calibrate_k(pool, d, cfg, a.r_max, a.sessions, a.iterations, a.seed + i)
        out["k"][d], out["history"][d] = k, hist
        print(f"{d}: K<1 у {len(k)} семейств, макс. частота по итерациям {hist}, {time.time() - t0:.0f} с", flush=True)
    dst = BACKEND / "app" / "modules" / "assessment" / "exposure_k.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
