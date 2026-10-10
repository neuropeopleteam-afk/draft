"""`make validate` — пересчёт метрик страницы /validation («Как мы проверяем себя»).

    cd backend && python -m app.modules.validation [--n 400] [--quick]

Что считается (всё — честно, как получилось; числа пишутся в app/modules/validation/data/report.json,
пары разметки — в docs/validation/matching_pairs.json):
1. Банк: валидатор (детерминизм по seed, ключи, инварианты) — из assessment_bank/BANK_SYNC.json.
2. Калибровка на панели: если есть ../bank/calibration/panel_*/params.json — сводка, иначе «ожидается».
3. Симуляция теста в конфигурации платформы на банке (165 семейств на 09.10): точность θ и решения по грейду, κ с истиной,
   длина и время; сравнение с механикой до 06.10 (те же seed) и с конфигурацией дня 2.
4. Стабильность грейда при повторе (другой субпул и другие варианты): κ, точное совпадение, ±1, ICC по θ, потолок
   при данной погрешности; до/после; без ошибки параметров; абляция «априорное по заявленному грейду».
5. Частота показа семейств: Sympson — Hetter + 2 субпула, до/после, против «без контроля».
6. Утечка части банка: без детектора, с детектором, с карантином субпула; таблица по доле слитых вариантов;
   атака завышением заявленного грейда.
7. Прогон «в условиях конкурентов»: 20 заданий, ошибка параметров b + N(0; 0,35), a · LogN(0; 0,2).
8. Качество подбора: precision@5 / nDCG на 15 потребностях × 20 кандидатах демо-данных (временная SQLite).
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


def _rng(i: int, tag: int) -> np.random.Generator:
    """Отдельный поток случайных чисел на (направление, блок): «до» и «после» получают одинаковые seed."""
    return np.random.default_rng([20261006, i, tag])


def _mean(rows: list[dict], keys) -> dict:
    out = {}
    for k in keys:
        vals = [r.get(k) for r in rows if isinstance(r.get(k), (int, float))]
        out[k] = round(float(np.mean(vals)), 3) if vals else None
    return out


RT_KEYS = ("r_theta", "icc_theta", "grade_exact_agreement", "grade_within_1", "grade_two_step_change",
           "grade_kappa_quadratic", "decision_agreement", "mean_diff_theta", "loa_theta", "mean_items", "max_items",
           "mean_time_min", "extension_share", "mean_ext_items", "mean_se", "rms_se")


def _rt_mean(rts: list[dict]) -> dict:
    m = _mean(rts, RT_KEYS)
    m["ceiling"] = _mean([r["ceiling"] for r in rts], ("grade_exact_agreement", "grade_within_1", "grade_kappa_quadratic"))
    return m


def simulation_section(n: int, quick: bool) -> dict:
    from dataclasses import asdict, replace

    from assessment_bank.psychometrics import ExposureControl
    from assessment_bank.simulation import make_population, make_truth

    from app.modules.assessment.exposure import exposure_table
    from app.modules.validation import sim

    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    pool1 = sim.make_pool(1)
    table = exposure_table() or {}
    k_all, k_leg_all = table.get("k", {}), table.get("k_legacy") or table.get("k", {})
    n_rt = n if not quick else max(150, n // 2)
    n_leak, n_tab, n_comp, n_oc = max(200, n // 2 if quick else n), max(150, n // 2 if quick else 300), \
        max(200, n // 2 if quick else n), max(200, n // 2 if quick else 300)

    def conf(c) -> dict:
        d = asdict(c)
        return {k: d[k] for k in ("min_items", "max_items", "se_target", "max_minutes", "subpools", "exposure",
                                  "max_per_format", "stop_rule", "classify_z", "select_at", "ext_items", "ext_minutes",
                                  "ext_own_first", "legacy_ext", "rotation")}

    out = {"config": conf(cfg),
           "legacy": conf(sim.LEGACY),
           "baseline": {"max_items": sim.BASELINE_DAY2.max_items, "max_minutes": sim.BASELINE_DAY2.max_minutes,
                        "subpools": 1, "exposure": False, "max_per_format": {}},
           "population": f"θ ~ N(0, 1), n = {n} на направление; истинные параметры = предкалибровка + ошибка эксперта "
                         "σ = 0,5 (по трудности семейства); время ответа — логнормальная модель банка",
           "conditions": {"n_per_direction": n, "n_retest_pairs": n_rt, "n_leak": n_leak, "n_leak_table": n_tab,
                          "n_competitor": n_comp, "n_overclaim": n_oc, "param_error_b_sd": 0.5,
                          "param_error_note": "сдвиг трудности семейства N(0; 0,5) + N(0; 0,15) по шагам, a × LogN(0; 0,25)",
                          "seeds": "numpy default_rng([20261006, направление, блок]) — одинаковые для «до» и «после»"},
           "policies": {
               "app": "сейчас: классификационная остановка (порог вне θ̂ ± 1,28·SE), выбор у неопределённого порога, "
                      "дотестирование до 6 коротких заданий у ближайшего порога (сначала из своего субпула)",
               "legacy": "до 06.10 в продукте: остановка по SE ≤ 0,35, выбор в θ̂, при |θ̂ − порог заявленного| < SE "
                         "ещё 3 задания из всего банка",
               "legacy_sim": "до 06.10 на /validation: та же механика, но без дотестирования (симуляция его не моделировала)"},
           "ceiling_curve": sim.ceiling_curve(),
           "directions": {}}
    dirs = sim.DIRECTIONS[:2] if quick else sim.DIRECTIONS
    for i, d in enumerate(dirs):
        t0 = time.time()
        rng0 = _rng(i, 0)
        truth = make_truth(pool, rng0, misspec=0.5)
        people = make_population(n, rng0)
        rt_people = make_population(n_rt, rng0)
        truth_ideal = make_truth(pool, rng0, misspec=0.0)
        k, k_leg = k_all.get(d, {}), k_leg_all.get(d, {})
        # 1. точность и частота показа: сейчас / до / день 2 (одни и те же люди и seed)
        cnt_app, cnt_leg, cnt_base = ExposureControl(0.3), ExposureControl(0.3), ExposureControl(1.0)
        r_app = sim.run_population(pool, truth, people, d, cfg, _rng(i, 1), k=k, counter=cnt_app)
        r_leg = sim.run_population(pool, truth, people, d, sim.LEGACY, _rng(i, 1), k=k_leg, counter=cnt_leg)
        r_base = sim.run_population(pool1, truth, people, d, sim.BASELINE_DAY2, _rng(i, 1), counter=cnt_base)
        acc = {}
        for name, r in (("app", r_app), ("legacy", r_leg), ("baseline_day2", r_base)):
            s_ = sim.summarize_safe(people, r)
            s_.update({k_: v for k_, v in sim.truth_metrics(people, r).items() if k_ in ("kappa_true",)})
            s_["ob3_max"] = int(max(x["n_ob3"] for x in r))
            s_["extension_share"] = round(float(np.mean([x.get("n_ext", 0) > 0 for x in r])), 3)
            s_["max_items"] = int(max(x["n_items"] for x in r))
            acc[name] = s_
        # 2. повтор: сейчас / до (в продукте) / до (как считалось) / без ошибки параметров / абляция «априорное по
        # заявленному грейду»
        rt = sim.retest(pool, truth, rt_people, d, cfg, _rng(i, 2), k)
        rt_leg = sim.retest(pool, truth, rt_people, d, sim.LEGACY, _rng(i, 2), k_leg)
        rt_leg_sim = sim.retest(pool, truth, rt_people, d, sim.LEGACY_SIM, _rng(i, 2), k_leg)
        rt["ideal_params"] = sim.retest(pool, truth_ideal, rt_people, d, cfg, _rng(i, 3), k)
        rt_prior = sim.retest(pool, truth, rt_people, d, replace(cfg, claim_prior=True), _rng(i, 2), k)
        # 3. атака завышением заявленного грейда (проверка, что досрочная остановка не завышает грейд)
        oc = {"app": sim.overclaim_attack(pool, truth, d, cfg, _rng(i, 4), k, n_oc),
              "legacy": sim.overclaim_attack(pool, truth, d, sim.LEGACY, _rng(i, 4), k_leg, n_oc),
              "claim_prior": sim.overclaim_attack(pool, truth, d, replace(cfg, claim_prior=True), _rng(i, 4), k, n_oc)}
        # 4. утечка 30 %: сейчас и до
        leak = sim.leak_experiment(pool, truth, d, cfg, _rng(i, 5), k, n=n_leak)
        leak_leg = sim.leak_experiment(pool, truth, d, sim.LEGACY, _rng(i, 5), k_leg, n=n_leak)
        # 5. атака по доле слитых вариантов
        ltab = sim.leak_share_table(pool, truth, d, cfg, _rng(i, 6), k, n=n_tab)
        # 6. «в условиях конкурентов»: 20 заданий, ошибка параметров b + N(0; 0,35), a · LogN(0; 0,2)
        comp = sim.competitor_run(pool1, d, _rng(i, 7), k, n_comp)
        out["directions"][d] = {
            "app": acc["app"], "legacy": acc["legacy"], "baseline_day2": acc["baseline_day2"],
            "retest": rt, "retest_legacy": rt_leg, "retest_legacy_sim": rt_leg_sim, "retest_claim_prior": rt_prior,
            "overclaim": oc,
            "exposure": {"app": sim.exposure_stats(cnt_app, pool, d), "legacy": sim.exposure_stats(cnt_leg, pool, d),
                         "baseline_day2": sim.exposure_stats(cnt_base, pool1, d)},
            "leak": leak,
            "leak_legacy": {"attack_success_rate": leak_leg["attack_success_rate"],
                            "n_unqualified_cheaters": leak_leg["n_unqualified_cheaters"],
                            "detector_tpr": leak_leg["leak_detector"].get("detector_tpr"),
                            "detector_fpr": leak_leg["leak_detector"].get("detector_fpr")},
            "leak_table": ltab, "competitor_like": comp, "seconds": round(time.time() - t0, 1)}
        if i == 0:
            # чувствительность к дискриминации заданий: a × 1,37 (медиана панели LLM) — только для объяснения разницы
            # с конкурентами, не заголовочная цифра
            pool_a = sim.make_pool(cfg.subpools)
            for it in pool_a:
                it.a = it.a * 1.37
            rng_a = _rng(i, 8)
            truth_a = make_truth(pool_a, rng_a, misspec=0.5)
            ppl_a = make_population(n_rt, rng_a)
            out["sensitivity_a"] = {"direction": d, "a_scale": 1.37,
                                    "app": sim.retest(pool_a, truth_a, ppl_a, d, cfg, _rng(i, 9), k),
                                    "legacy": sim.retest(pool_a, truth_a, ppl_a, d, sim.LEGACY, _rng(i, 9), k_leg)}
        print(f"  симуляция {d}: κ повтора {rt_leg['grade_kappa_quadratic']} → {rt['grade_kappa_quadratic']} "
              f"(потолок {rt['ceiling']['grade_kappa_quadratic']}), заданий {rt_leg['mean_items']} → {rt['mean_items']}, "
              f"ASR 30 % {leak_leg['attack_success_rate']['leak_detector']} → {leak['attack_success_rate']['leak_detector']}, "
              f"частота макс. {out['directions'][d]['exposure']['legacy']['max_rate']} → "
              f"{out['directions'][d]['exposure']['app']['max_rate']} ({time.time() - t0:.0f} с)", flush=True)
    D = out["directions"].values()
    keys = ("r_theta", "rmse", "mean_items", "mean_time_min", "grade_exact", "grade_within_1", "kappa_true",
            "decision_accuracy", "false_confirm_rate", "false_reject_rate", "extension_share")
    out["mean"] = _mean([v["app"] for v in D], keys)
    out["mean_legacy"] = _mean([v["legacy"] for v in D], keys)
    out["mean_baseline"] = _mean([v["baseline_day2"] for v in D], keys)
    out["retest_mean"] = {"app": _rt_mean([v["retest"] for v in D]), "legacy": _rt_mean([v["retest_legacy"] for v in D]),
                          "legacy_sim": _rt_mean([v["retest_legacy_sim"] for v in D]),
                          "ideal_params": _rt_mean([v["retest"]["ideal_params"] for v in D]),
                          "claim_prior": _rt_mean([v["retest_claim_prior"] for v in D])}
    out["overclaim_mean"] = {k_: _mean([v["overclaim"][k_] for v in D], ("false_confirm",))["false_confirm"]
                             for k_ in ("app", "legacy", "claim_prior")}
    asr_keys = ("no_leak", "leak_no_detector", "leak_detector", "leak_detector_rotation", "fixed_no_leak", "fixed_leak",
                "fixed_full_leak")
    out["asr_mean"] = {"app": _mean([v["leak"]["attack_success_rate"] for v in D], asr_keys),
                       "legacy": _mean([v["leak_legacy"]["attack_success_rate"] for v in D], asr_keys),
                       "detector_fpr": {"app": _mean([v["leak"]["leak_detector"] for v in D], ("detector_fpr",))["detector_fpr"],
                                        "legacy": _mean([v["leak_legacy"] for v in D], ("detector_fpr",))["detector_fpr"]}}
    shares = [r["leak_share"] for r in next(iter(D))["leak_table"]["rows"]]
    out["leak_table_mean"] = {"n_per_direction": n_tab, "cheater_share": 0.25, "rows": [
        {"leak_share": sh, **_mean([next(r for r in v["leak_table"]["rows"] if r["leak_share"] == sh) for v in D],
                                   ("fixed_form", "no_detector", "detector", "detector_quarantine", "detector_tpr",
                                    "detector_fpr"))} for sh in shares]}
    out["exposure_mean"] = {k_: _mean([v["exposure"][k_] for v in D], ("max_rate", "mean_rate", "share_over_rmax",
                                                                       "unused_share")) for k_ in ("app", "legacy")}
    out["competitor_like"] = {"config": conf(sim.COMPETITOR_LIKE), "error": sim.COMPETITOR_ERROR, "n_per_direction": n_comp,
                              "truth": _mean([v["competitor_like"]["truth"] for v in D],
                                             ("grade_exact", "grade_within_1", "kappa_true", "r_theta", "mean_items",
                                              "mean_time_min")),
                              "retest": _rt_mean([v["competitor_like"]["retest"] for v in D]),
                              # цифры из README/отчётов конкурентов (spectrek/intel/competitors.md, raw/0610)
                              "reference": {"miliantr/fsp-talent": {"grade_exact": 0.805, "kappa_true": 0.898,
                                                                    "grade_within_1": 0.999, "r_theta_retest": 0.866,
                                                                    "decision_kappa_retest": 0.54, "length": 20,
                                                                    "n": 1600, "param_error": "b + N(0; 0,35), a · LogN(0; 0,2)"},
                                            "Izymka/fsp-job-board": {"kappa_retest": 0.86,
                                                                     "param_error": "не опубликована"}}}
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
    # Я8: подпись расчёта, как у остальных JSON /validation — коммит кода, банк, seed, конфигурация (только метаданные)
    from app.modules.validation.signature import signature
    rep["signature"] = signature(
        seed=20261006, config={"n": a.n, "quick": a.quick, "simulation": rep["simulation"].get("config"),
                               "exposure_k_generated_at": exp.get("generated_at")},
        world="симуляция теста на синтетических кандидатах (θ ~ N(0; 1), истина заданий = предкалибровка + ошибка "
              "эксперта) и подбор на демо-данных (метки правилами)", command="make validate", n=a.n)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"4/4 → {REPORT} ({rep['seconds']} с)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
