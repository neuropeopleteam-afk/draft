"""`make validate` — пересчёт метрик страницы /validation («Как мы проверяем себя»).

    cd backend && python -m app.modules.validation [--n 400] [--quick]

Что считается (всё — честно, как получилось; числа пишутся в app/modules/validation/data/report.json,
пары разметки — в docs/validation/matching_pairs.json):
1. Банк: валидатор (детерминизм по seed, ключи, инварианты) — из assessment_bank/BANK_SYNC.json.
2. Калибровка на панели: если есть ../bank/calibration/panel_*/params.json — сводка, иначе «ожидается».
3. Симуляция теста в конфигурации платформы на банке 128 семейств: точность θ и решения по грейду,
   длина и время; сравнение с конфигурацией дня 2 (без контроля частоты и ротации).
4. Стабильность грейда при повторе (другой субпул и другие варианты).
5. Частота показа семейств: Sympson — Hetter + 2 субпула против «без контроля».
6. Утечка части банка: без детектора, с детектором, с карантином субпула.
7. Качество подбора: precision@5 / nDCG на 15 потребностях × 20 кандидатах демо-данных (временная SQLite).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import numpy as np

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
REPO = BACKEND.parent
REPORT = HERE / "data" / "report.json"
PAIRS = REPO / "docs" / "validation" / "matching_pairs.json"


def bank_section() -> dict:
    p = BACKEND / "assessment_bank" / "BANK_SYNC.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    v = (d.get("validation") or {}).get("summary") or {}
    return {"n_families": d.get("n_families"), "content_hash": d.get("content_hash"), "commit": d.get("commit"),
            "synced_at": d.get("synced_at"), "by_direction": d.get("by_direction"),
            "validator": {k: v.get(k) for k in ("n_families", "n_variants_generated", "n_unique_variants", "n_checks",
                                                "n_checks_failed", "status")},
            "note": "Валидатор банка: каждое семейство × 20 seed — генерация детерминирована, ключ проверен "
                    "исполнением эталонного решения, инварианты формата соблюдены. WARN — предупреждения качества "
                    "(например, похожие дистракторы), не ошибки ключа."}


def calibration_section() -> dict:
    bank_dir = Path(os.environ.get("BANK_DIR", REPO.parent / "bank"))
    found = sorted(glob.glob(str(bank_dir / "calibration" / "panel_*" / "params.json")))
    if not found:
        panels = sorted(glob.glob(str(bank_dir / "calibration" / "panel_*")))
        return {"status": "expected", "panels": [Path(p).name for p in panels],
                "note": "Калибровка на панели ответов ещё не завершена: параметры заданий — экспертная предкалибровка. "
                        "Когда появится calibration/panel_*/params.json, `make validate` подхватит её автоматически."}
    p = Path(found[-1])
    d = json.loads(p.read_text(encoding="utf-8"))
    fams = d.get("families") or d.get("params") or d
    n = len(fams) if isinstance(fams, dict) else None
    out = {"status": "ready", "panel": p.parent.name, "file": str(p.relative_to(bank_dir)), "n_families": n,
           "meta": {k: d[k] for k in ("method", "n_respondents", "n_responses", "generated_at") if k in d}}
    return out


def simulation_section(n: int, quick: bool) -> dict:
    from assessment_bank.psychometrics import ExposureControl
    from assessment_bank.simulation import make_population, make_truth

    from app.modules.assessment.exposure import exposure_table
    from app.modules.validation import sim

    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    pool1 = sim.make_pool(1)
    k_all = (exposure_table() or {}).get("k", {})
    out = {"config": {"min_items": cfg.min_items, "max_items": cfg.max_items, "se_target": cfg.se_target,
                      "max_minutes": cfg.max_minutes, "subpools": cfg.subpools, "exposure": cfg.exposure,
                      "max_per_format": cfg.max_per_format},
           "baseline": {"max_items": sim.BASELINE_DAY2.max_items, "max_minutes": sim.BASELINE_DAY2.max_minutes,
                        "subpools": 1, "exposure": False, "max_per_format": {}},
           "population": f"θ ~ N(0, 1), n = {n} на направление; истинные параметры = предкалибровка + ошибка эксперта "
                         "σ = 0,5 (по трудности семейства); время ответа — логнормальная модель банка",
           "directions": {}}
    dirs = sim.DIRECTIONS[:2] if quick else sim.DIRECTIONS
    for i, d in enumerate(dirs):
        t0 = time.time()
        rng = np.random.default_rng(20261006 + i)
        truth = make_truth(pool, rng, misspec=0.5)
        truth1 = {f: t for f, t in truth.items()}
        k = k_all.get(d, {})
        people = make_population(n, rng)
        cnt_app = ExposureControl(0.3)
        r_app = sim.run_population(pool, truth, people, d, cfg, rng, k=k, counter=cnt_app)
        cnt_base = ExposureControl(1.0)
        r_base = sim.run_population(pool1, truth1, people, d, sim.BASELINE_DAY2, rng, counter=cnt_base)
        s_app, s_base = sim.summarize_safe(people, r_app), sim.summarize_safe(people, r_base)
        s_app["ob3_max"] = int(max(r["n_ob3"] for r in r_app))
        s_base["ob3_max"] = int(max(r["n_ob3"] for r in r_base))
        rt_people = make_population(max(150, n // 2), rng)
        rt = sim.retest(pool, truth, rt_people, d, cfg, rng, k)
        # те же люди, но истинные параметры = параметры банка (без ошибки эксперта) — как «чистая» синтетика
        rt["ideal_params"] = sim.retest(pool, make_truth(pool, rng, misspec=0.0), rt_people, d, cfg, rng, k)
        if i == 0:  # «что поможет»: длиннее тест — SE ≤ 0,25, до 30 заданий и 120 минут (одно направление, для оценки)
            long_cfg = sim.AppConfig(min_items=cfg.min_items, max_items=30, se_target=0.25, max_minutes=120,
                                     subpools=cfg.subpools, exposure=cfg.exposure, max_per_format=cfg.max_per_format)
            rt["long_test"] = sim.retest(pool, truth, rt_people, d, long_cfg, rng, k)
        leak = sim.leak_experiment(pool, truth, d, cfg, rng, k, n=max(200, n // 2 if quick else n))
        out["directions"][d] = {
            "app": s_app, "baseline_day2": s_base, "retest": rt,
            "exposure": {"app": sim.exposure_stats(cnt_app, pool, d), "baseline_day2": sim.exposure_stats(cnt_base, pool1, d)},
            "leak": leak, "seconds": round(time.time() - t0, 1)}
        print(f"  симуляция {d}: r={s_app['r_theta']} items={s_app['mean_items']} retest r={rt['r_theta']} "
              f"exposure max {out['directions'][d]['exposure']['app']['max_rate']} ({time.time() - t0:.0f} с)", flush=True)
    keys = ("r_theta", "rmse", "mean_items", "mean_time_min", "grade_exact", "decision_accuracy", "false_confirm_rate",
            "false_reject_rate")
    out["mean"] = {k: round(float(np.mean([v["app"][k] for v in out["directions"].values()])), 3) for k in keys}
    out["mean_baseline"] = {k: round(float(np.mean([v["baseline_day2"][k] for v in out["directions"].values()])), 3)
                            for k in keys}
    return out


def matching_section() -> dict:
    tmp = Path(tempfile.mkdtemp()) / "validate.db"
    url = f"sqlite:///{tmp}"
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    from sqlalchemy.orm import Session

    from app.core.db import init_engine

    from app.modules.demo.seed import NEEDS, seed
    from app.modules.validation.matching_eval import evaluate

    eng = init_engine(url)
    with Session(eng) as db:
        seed(db)
        db.commit()
        res = evaluate(db, [t for _, t in NEEDS])
    eng.dispose()
    PAIRS.parent.mkdir(parents=True, exist_ok=True)
    PAIRS.write_text(json.dumps({"needs": [t for _, t in NEEDS], "pairs": res.pop("pairs"), "method": res["method"]},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_per_direction": a.n,
           "quick": a.quick}
    print("1/4 банк и калибровка", flush=True)
    rep["bank"] = bank_section()
    rep["calibration"] = calibration_section()
    print("2/4 качество подбора (демо-данные, временная SQLite)", flush=True)
    rep["matching"] = matching_section()
    print(f"  precision@5 {rep['matching']['summary']['p@5']}", flush=True)
    print("3/4 симуляция теста", flush=True)
    rep["simulation"] = simulation_section(a.n, a.quick)
    exp = json.loads((BACKEND / "app" / "modules" / "assessment" / "exposure_k.json").read_text(encoding="utf-8"))
    rep["exposure_calibration"] = {k: exp.get(k) for k in ("method", "r_max", "sessions_per_iteration", "iterations",
                                                           "history", "generated_at")}
    rep["seconds"] = round(time.time() - t0, 1)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"4/4 → {REPORT} ({rep['seconds']} с)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
