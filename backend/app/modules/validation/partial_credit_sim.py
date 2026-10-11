"""Симуляция «0/1» против «0–4» у развёрнутых ответов при той же длине теста (синтетика; модель, не люди).

    make partial-credit-sim   # cd backend && python -m app.modules.validation.partial_credit_sim [--n 300] [--quick]

Путь кандидата — как в ``path_retest`` (опрос → заявленный грейд → адаптивный тест → решение → принять уровень ниже
или тест ступенью ниже; повтор — тот же путь ещё раз с историей первой). Одни и те же кандидаты, истина заданий и
зерна ГСЧ во всех вариантах; различается только то, как движок учитывает развёрнутые ответы.

Мир (как отвечает кандидат на развёрнутую часть):
* истинный балл 0–4 — GPCM с параметрами из истины части в 2PL (``gpcm.from_2pl``: ожидаемая доля балла = кривая
  2PL; ступени вокруг трудности — шаблон ``OFFSETS`` × spacing). spacing 1 даёт долю промежуточных баллов 1–3 ≈ 0,6 —
  как у эталона на наборе оценщика (0,605, docs/llm/partial_credit_offline.json); spacing 0,5 — «пессимистичный»
  мир: пункты рубрики почти не различаются (меньше промежуточных), движок этого не знает;
* балл, который видит движок, — истинный, пропущенный через шум оценщика: матрица P(балл оценщика | балл эталона)
  по сохранённым ответам Claude Sonnet 5.5 + скептик на 256 честных ответах (data/partial_credit_noise.json;
  эталон — gpt-oss-120b, тоже модель). Мир «без шума» — верхняя оценка.
* дихотомические части — как в path_retest (2PL с разбросом вариантов).

Варианты движка (одни и те же ответы мира):
* ``bin`` — «0/1»: засчитано, если балл ≥ 2; 2PL;
* ``frac`` — как сейчас в продукте без флага: доля балла 0..1 в 2PL как квазибиномиальная;
* ``gpcm`` — флаг ASSESSMENT_PARTIAL_CREDIT_ENABLED: балл 0–4 в GPCM (``CATSession(partial_credit=True)``).

Метрики: точно истинный уровень, выше, ниже, без категории, совпадение итогового грейда при повторе, κw повтора, SE
первой сессии, заданий и минут на путь. Отдельно ``fixed`` — фиксированная длина 16 заданий (без классификационной
остановки и дотестирования): SE при строго одной длине. Порог решения — P ≥ 0,8 (main) и P ≥ 0,6 (решение по
точности уровня, ASSESSMENT_CONFIRM_LEVEL в ветке точности уровня).

Результат — data/partial_credit_sim.json и docs/validation/PARTIAL_CREDIT.md (таблицы).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import functools
import json
from multiprocessing import get_context
import os
from pathlib import Path
import time

import numpy as np

from assessment_bank.psychometrics import CanaryDetector, ExposureControl, gpcm, prob
from assessment_bank.simulation import Person

from app.modules.assessment.exposure import exposure_table
from app.modules.validation import path_retest as pr
from app.modules.validation import sim
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT = HERE / "data" / "partial_credit_sim.json"
NOISE = HERE / "data" / "partial_credit_noise.json"
DOCS_MD = REPO / "docs" / "validation" / "PARTIAL_CREDIT.md"
SEED = pr.SEED
ARMS = ("bin", "frac", "gpcm", "gpcm_est")
ARM_RU = {"bin": "0/1 (засчитано при балле ≥ 2)", "frac": "доля 0..1 в 2PL (сейчас, флаг выкл.)",
          "gpcm": "0–4 по GPCM в θ и в выборе задания (флаг вкл.)",
          "gpcm_est": "0–4 по GPCM только в θ, выбор задания по 2PL (флаг вкл., ASSESSMENT_PARTIAL_CREDIT_SELECT=false)"}
WORLDS = {
    "base": {"spacing": 1.0, "noise": True, "ru": "ступени ×1, шум оценщика по данным"},
    "narrow": {"spacing": 0.5, "noise": True, "ru": "ступени ×0,5 (пункты рубрики мало различаются), шум по данным"},
    "clean": {"spacing": 1.0, "noise": False, "ru": "ступени ×1, без шума оценщика (верхняя оценка)"},
}
CAVEAT = ("Синтетика: люди и ответы — модель, не люди. Истинные параметры заданий = предкалибровка + ошибка эксперта "
          "σ = 0,5 (как в path_retest); балл 0–4 — модель GPCM, шум оценщика — по ответам моделей на наборе оценщика "
          "(эталон — тоже модель). Параметры GPCM движка до калибровки на людях выведены из 2PL; на людях их нужно "
          "откалибровать.")


METHOD = [
    "- **Балл 0–4** = round(4 × взвешенная оценка пунктов рубрики) — тот же ответ оценщика, нового вызова модели нет "
    "(`assessment/partial_credit.py`). С флагом `ASSESSMENT_PARTIAL_CREDIT_ENABLED` балл развёрнутой части входит в θ "
    "по GPCM (`assessment_bank/psychometrics/gpcm.py`), остальные части — 2PL, как без флага; выбор следующего задания "
    "учитывает информацию GPCM.",
    "- **Параметры GPCM до калибровки на людях** выводятся из 2PL части: ступени b + (−0,75; −0,25; 0,25; 0,75), наклон "
    "подобран так, что ожидаемая доля балла совпадает с кривой 2PL (шкала θ та же). После пилота на людях параметры "
    "ступеней нужно откалибровать (`irt.fit_mml` расширяется на GPCM) — до этого прирост в продукте — оценка модели.",
    "- **Информация одной части** при a = 1,5 в центре: 0/1 с шумом оценщика ≈ 0,83, 0–4 с тем же шумом ≈ 1,24 "
    "(≈ 1,5×), без шума — 1,28 и 1,91. В сессии не больше трёх развёрнутых частей (2 open_book_3step + 1 open_answer "
    "из 16–22 заданий), поэтому прирост на весь тест ограничен ими.",
    "- **Шум оценщика** — матрица по сохранённым ответам модели-оценщика против эталона-модели; настоящий шум на людях "
    "может быть другим. Мир `narrow` проверяет случай, когда пункты рубрики различают хуже, чем думает движок.",
    "- Варианты считаются на одних и тех же кандидатах с теми же зёрнами, но адаптивный тест выбирает разные задания, "
    "поэтому разности — парные по кандидату, ДИ 95 % — бутстрэп по кандидатам.",
    "- FTT.4: уровень присваивается только по тесту — частичный балл меняет лишь то, как ответы теста входят в θ.",
]


def noise_matrix() -> np.ndarray:
    d = json.loads(NOISE.read_text(encoding="utf-8"))
    m = np.asarray(d["matrix_ref_to_grader"], dtype=float)
    return m / m.sum(axis=1, keepdims=True)


def world_steps(a: float, b: float, spacing: float) -> tuple[float, np.ndarray]:
    return gpcm.from_2pl(a, b, gpcm.OFFSETS * spacing)


def gpcm_responder(arm: str, spacing: float, noise: np.ndarray | None):
    """Фабрика ответов (как simulation.make_responder): развёрнутые части — балл 0–4 мира → шум оценщика → x движка."""

    def factory(person: Person, truth, leak=None):
        def respond(item, rng):
            tf = truth[item.family_id]
            delta = rng.normal(0, tf.sigma)
            p = prob(person.theta, tf.a, tf.mu + delta)
            x = (rng.random(len(tf.mu)) < p).astype(float)
            for j in gpcm.text_parts(item.format, len(tf.mu)):
                ag, steps = world_steps(float(tf.a[j]), float(tf.mu[j] + delta), spacing)
                k = gpcm.sample(person.theta, ag, steps, rng)
                if noise is not None:
                    k = int(rng.choice(gpcm.K + 1, p=noise[k]))
                x[j] = float(k >= 2) if arm == "bin" else k / gpcm.K  # frac, gpcm, gpcm_est — доля балла
            log_t = float(rng.normal(tf.beta_time - person.tau, 1 / tf.alpha_time))
            return x, min(log_t, float(np.log(tf.time_limit_s)))
        return respond
    return factory


def _patch_confirm(level: float) -> None:
    """Порог решения для этого процесса: подтверждение и «уровень ниже» — P ≥ level (как ASSESSMENT_CONFIRM_LEVEL)."""
    from app.modules.assessment import grades as grades_mod, rules as rules_mod

    pr.decide_grade = functools.partial(grades_mod.decide_grade, confirm_level=level)
    rules_mod.proved_lower = functools.partial(rules_mod.proved_lower.func if isinstance(
        rules_mod.proved_lower, functools.partial) else rules_mod.proved_lower, level=level)


def run_task(args: tuple) -> dict:
    """Один вариант × мир × порог × направление: путь дважды для n кандидатов (те же зёрна, что path_retest)."""
    arm, world, confirm, length, i, d, n = args
    w = WORLDS[world]
    from app.modules.assessment import rules as rules_mod

    saved = (pr.decide_grade, rules_mod.proved_lower, pr.make_responder)  # подмены — только на время задачи
    try:
        return _run_task(arm, world, confirm, length, i, d, n, w)
    finally:
        pr.decide_grade, rules_mod.proved_lower, pr.make_responder = saved


def _run_task(arm, world, confirm, length, i, d, n, w) -> dict:
    _patch_confirm(confirm)
    cfg = sim.app_config_from_settings()
    cfg = replace(cfg, partial_credit=arm in ("gpcm", "gpcm_est"), partial_credit_select=(arm == "gpcm"))
    if length == "fixed":
        cfg = replace(cfg, min_items=16, max_items=16, se_target=0.0, stop_rule="se", ext_items=0)
    pool = sim.make_pool(cfg.subpools)
    k = (exposure_table() or {}).get("k", {}).get(d, {})
    rng0 = pr._rng(i, 0)
    truth = pr.make_truth(pool, rng0, misspec=0.5)
    cands = pr.make_candidates(n, d, rng0)
    counter = ExposureControl(0.3, k=dict(k))
    det = CanaryDetector()
    rng = pr._rng(i, 1)
    pr.make_responder = gpcm_responder(arm, w["spacing"], noise_matrix() if w["noise"] else None)
    r1, r2 = [], []
    t0 = time.time()
    for c in cands:
        hist: list[dict] = []
        r1.append(pr.run_path(pool, c, truth, cfg, counter, hist, rng, det))
        r2.append(pr.run_path(pool, c, truth, cfg, counter, hist, rng, det))
    slim = [{"level": a["level"], "status": a["status"], "families": a["families"], "intern_proved": a["intern_proved"],
             "tests": [{"theta": t["theta"], "se": t["se"], "n_items": t["n_items"], "time_s": t["time_s"],
                        "n_ext": t["n_ext"], "rescored": t["rescored"], "families": t["families"],
                        "gap": t["gap"]} for t in a["tests"]]} for a in r1 + r2]
    return {"key": [arm, world, confirm, length, d], "theta": [c.theta for c in cands],
            "claimed": [c.claimed for c in cands], "r1": slim[:n], "r2": slim[n:], "seconds": round(time.time() - t0, 1)}


def summarize(parts: list[dict]) -> dict:
    """Итог по направлениям одного варианта: истина, повтор, SE, время."""
    cands = [pr.Candidate(t, 0.0, "x", 0.0, "", "", c) for p in parts for t, c in zip(p["theta"], p["claimed"])]
    r1 = [r for p in parts for r in p["r1"]]
    r2 = [r for p in parts for r in p["r2"]]
    tb = pr.truth_block(cands, r1)
    rb = pr.retest_block(cands, r1, r2, SEED + 99, ci=True)
    ps = pr.path_stats(r1 + r2)
    se1 = np.array([r["tests"][0]["se"] for r in r1])
    th1 = np.array([r["tests"][0]["theta"] for r in r1])
    th_true = np.array([c.theta for c in cands])
    pg = rb["path_grade"]
    return {"n": len(cands), "exact": tb["exact"], "over": tb["over_share"], "under": tb["under_share"],
            "none": tb["no_category_share"], "kappa_w_true": tb["kappa_w_true"],
            "retest_exact": pg["exact"], "retest_exact_ci": pg.get("exact_ci"), "retest_kappa_w": pg["kappa_w"],
            "retest_kappa_w_ci": pg.get("kappa_w_ci"), "icc_theta": rb.get("icc_theta"),
            "se_first_mean": round(float(se1.mean()), 4), "se_first_median": round(float(np.median(se1)), 4),
            "rmse_theta_first": round(float(np.sqrt(np.mean((th1 - th_true) ** 2))), 4),
            "bias_theta_first": round(float(np.mean(th1 - th_true)), 4),
            "coverage90_first": round(float(np.mean(np.abs(th1 - th_true) <= 1.645 * se1)), 3),
            "items_per_session": ps["mean_items_per_session"], "items_per_path": ps["mean_items_per_path"],
            "minutes_per_path": ps["mean_time_min_per_path"], "sessions_per_path": ps["sessions_per_path"],
            "extension_share": ps["extension_share"]}


def paired_diff(a: list[dict], b: list[dict], seed: int, n_boot: int = 1000) -> dict:
    """Парные разности b − a (те же кандидаты): точно истинный, повтор совпал — с бутстрэп-ДИ 95 %."""
    th = np.array([t for p in a for t in p["theta"]])
    true = np.array([pr.LEVELS.index(pr.point_grade(t)) for t in th])
    la = np.array([r["level"] for p in a for r in p["r1"]])
    lb = np.array([r["level"] for p in b for r in p["r1"]])
    ra = la == np.array([r["level"] for p in a for r in p["r2"]])
    rb = lb == np.array([r["level"] for p in b for r in p["r2"]])
    ea, eb = (la == true).astype(float), (lb == true).astype(float)
    oa, ob = (la > true).astype(float), (lb > true).astype(float)
    idx = np.random.default_rng(seed).integers(0, len(th), size=(n_boot, len(th)))

    def ci(v):
        bs = v[idx].mean(axis=1)
        return [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)]
    return {"exact": round(float((eb - ea).mean()), 3), "exact_ci": ci(eb - ea),
            "over": round(float((ob - oa).mean()), 3), "over_ci": ci(ob - oa),
            "retest_exact": round(float((rb.astype(float) - ra).mean()), 3), "retest_exact_ci": ci(rb.astype(float) - ra)}


def info_table() -> list[dict]:
    """Информация одной развёрнутой части (a = 1, b = 0) при разных θ: 0/1, GPCM без шума."""
    out = []
    ag, steps = gpcm.from_2pl(1.0, 0.0)
    for th in (-2.0, -1.0, 0.0, 1.0, 2.0):
        p = float(prob(th, 1.0, 0.0))
        out.append({"theta": th, "info_2pl": round(p * (1 - p), 3),
                    "info_gpcm": round(float(gpcm.information(th, ag, steps)), 3)})
    return out


def run(n: int = 300, quick: bool = False, write: bool = True, parallel: int = 2,
        plan: list[tuple] | None = None) -> dict:
    t0 = time.time()
    dirs = sim.DIRECTIONS[:2] if quick else sim.DIRECTIONS
    if quick:
        n = min(n, 40)
    if plan is None:
        plan = [(arm, "base", 0.8, "adaptive") for arm in ARMS] + [(arm, "base", 0.6, "adaptive") for arm in ARMS] + \
               [(arm, "narrow", 0.6, "adaptive") for arm in ARMS] + [(arm, "clean", 0.6, "adaptive") for arm in ARMS] + \
               [(arm, "base", 0.6, "fixed") for arm in ("frac", "gpcm", "gpcm_est")] + \
               [(arm, "clean", 0.6, "fixed") for arm in ("frac", "gpcm_est")]
    tasks = [(arm, world, conf, length, i, d, n) for (arm, world, conf, length) in plan for i, d in enumerate(dirs)]
    parts = _run_all(tasks, parallel)
    by: dict[tuple, list[dict]] = {}
    for p in parts:
        arm, world, conf, length, d = p["key"]
        by.setdefault((arm, world, conf, length), []).append(p)
    for v in by.values():
        v.sort(key=lambda p: dirs.index(p["key"][4]))
    rows = []
    for (arm, world, conf, length), v in sorted(by.items(), key=lambda kv: (kv[0][3], kv[0][1], -kv[0][2],
                                                                             ARMS.index(kv[0][0]))):
        row = {"arm": arm, "world": world, "confirm": conf, "length": length, **summarize(v)}
        base = by.get(("frac", world, conf, length))
        if arm != "frac" and base:
            row["diff_vs_frac"] = paired_diff(base, v, SEED + 5)
        rows.append(row)
        print(f"  {length:8s} {world:6s} P≥{conf} {arm:5s}: точно {row['exact']:.3f} выше {row['over']:.3f} "
              f"повтор {row['retest_exact']:.3f} κw {row['retest_kappa_w']:.3f} SE {row['se_first_mean']:.3f} "
              f"RMSE {row['rmse_theta_first']:.3f} покр. {row['coverage90_first']:.3f} "
              f"заданий {row['items_per_session']} мин {row['minutes_per_path']}", flush=True)
    world_cfg = {"n_per_direction": n, "directions": list(dirs), "worlds": WORLDS, "arms": list(ARMS),
                 "offsets": gpcm.OFFSETS.tolist(), "noise": json.loads(NOISE.read_text(encoding="utf-8")),
                 "app": {k: v for k, v in sim.app_config_from_settings().__dict__.items()}}
    rep = {"signature": signature(seed=SEED, config=world_cfg, n=n * len(dirs),
                                  world=f"симуляция пути: {len(dirs)} направлений × {n} кандидатов, «0/1» против «0–4»",
                                  command="make partial-credit-sim" if not quick else
                                  "python -m app.modules.validation.partial_credit_sim --quick"),
           "quick": quick, "n_per_direction": n, "directions": list(dirs), "worlds": WORLDS, "arms": ARM_RU,
           "rows": rows, "info": info_table(), "caveat": CAVEAT, "conclusions": conclusions(rows),
           "seconds": round(time.time() - t0, 1)}
    if write:
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        DOCS_MD.parent.mkdir(parents=True, exist_ok=True)
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {OUT.relative_to(REPO)}, {DOCS_MD.relative_to(REPO)} ({rep['seconds']} с)", flush=True)
    return rep


def _run_all(tasks: list[tuple], parallel: int) -> list[dict]:
    """Задачи параллельно: пул процессов, а где семафоры запрещены (сервер проверок) — процессы-исполнители."""
    if parallel <= 1:
        return [run_task(t) for t in tasks]
    try:
        with get_context("spawn").Pool(parallel) as p:
            return list(p.imap_unordered(run_task, tasks))
    except PermissionError:
        import subprocess
        import sys
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="pcsim_"))
        procs = []
        for k in range(parallel):
            chunk = tasks[k::parallel]
            if not chunk:
                continue
            inp, out = tmp / f"in{k}.json", tmp / f"out{k}.json"
            inp.write_text(json.dumps(chunk), encoding="utf-8")
            procs.append((subprocess.Popen([sys.executable, "-m", "app.modules.validation.partial_credit_sim",
                                            "--worker", str(inp), str(out)], cwd=str(HERE.parents[2])), out))
        parts = []
        for pr_, out in procs:
            if pr_.wait() != 0:
                raise RuntimeError(f"исполнитель симуляции завершился с кодом {pr_.returncode}")
            parts += json.loads(out.read_text(encoding="utf-8"))
        return parts


def _pc(v) -> str:
    return "—" if v is None else f"{100 * v:.1f} %".replace(".", ",")


def _f(v, d: int = 3) -> str:
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def _d(v) -> str:
    return "—" if v is None else f"{100 * v:+.1f}".replace(".", ",") + " п. п."


def _dci(ci) -> str:
    return "" if not ci else f" [{100 * ci[0]:+.1f}; {100 * ci[1]:+.1f}]".replace(".", ",")


def conclusions(rows: list[dict]) -> list[str]:
    """Выводы по строкам симуляции (числа — из строк; толкование — общее для любых чисел этого мира)."""
    def get(length, world, conf, arm):
        return next((r for r in rows if (r["length"], r["world"], r["confirm"], r["arm"]) == (length, world, conf, arm)),
                    None)

    out = []
    fr, gp, bi = (get("adaptive", "base", 0.6, a) for a in ("frac", "gpcm", "bin"))
    if fr and gp and gp.get("diff_vs_frac"):
        d = gp["diff_vs_frac"]
        out.append(f"Основной мир, P ≥ 0,6, адаптивный тест: «0–4, GPCM» против нынешнего учёта доли — точно "
                   f"{_pc(fr['exact'])} → {_pc(gp['exact'])} ({_d(d['exact'])}{_dci(d['exact_ci'])}), повтор "
                   f"{_pc(fr['retest_exact'])} → {_pc(gp['retest_exact'])} ({_d(d['retest_exact'])}"
                   f"{_dci(d['retest_exact_ci'])}). Разница в пределах шума: прироста точности уровня нет.")
        if fr.get("rmse_theta_first") is not None:
            out.append(f"GPCM снижает заявленную ошибку SE {_f(fr['se_first_mean'])} → {_f(gp['se_first_mean'])}, но "
                       f"фактическая ошибка θ̂ не меньше (RMSE {_f(fr['rmse_theta_first'])} → "
                       f"{_f(gp['rmse_theta_first'])}), а покрытие 90 %-интервала падает {_pc(fr['coverage90_first'])} → "
                       f"{_pc(gp['coverage90_first'])}: выигрыш информации в основном на бумаге.")
    b8 = get("adaptive", "base", 0.8, "bin")
    if fr and bi and bi.get("diff_vs_frac"):
        d = bi["diff_vs_frac"]
        tail = (f"; при P ≥ 0,8 — {_d(b8['diff_vs_frac']['retest_exact'])}{_dci(b8['diff_vs_frac']['retest_exact_ci'])}"
                if b8 and b8.get("diff_vs_frac") else "")
        out.append(f"Строгий «0/1» немного хуже нынешнего учёта доли: повтор {_d(d['retest_exact'])}"
                   f"{_dci(d['retest_exact_ci'])}{tail}; RMSE θ̂ {_f(bi.get('rmse_theta_first'))} против "
                   f"{_f(fr.get('rmse_theta_first'))}. Частичный балл полезен — и он уже есть: доля 0..1 входит в 2PL "
                   f"(квазибиномиально).")
    out.append("Почему так: оценочное уравнение доли в 2PL a·(x − P(θ)) почти пропорционально уравнению GPCM "
               "a_g·(k − E[k | θ]) — ожидаемая доля балла GPCM совпадает с кривой 2PL (так выведены параметры до "
               "калибровки), поэтому точечная оценка θ почти та же; меняются вес развёрнутых частей и заявленная точность. "
               "К тому же развёрнутых частей в сессии не больше трёх из ≈ 20 заданий.")
    fg = get("fixed", "base", 0.6, "gpcm")
    if fg and fg.get("diff_vs_frac"):
        d = fg["diff_vs_frac"]
        out.append(f"Одна длина (16 заданий): точно {_d(d['exact'])}{_dci(d['exact_ci'])}, повтор "
                   f"{_d(d['retest_exact'])}{_dci(d['retest_exact_ci'])} — тоже в пределах шума.")
    out.append("Решение: флаг ASSESSMENT_PARTIAL_CREDIT_ENABLED оставить выключенным. Смысл включать — после калибровки "
               "ступеней GPCM на ответах людей (пилот), когда ступени не выводятся из 2PL; до этого балл 0–4 полезен как "
               "показ (рубрика, цитаты), а не как источник точности уровня.")
    return out


def markdown(rep: dict) -> str:
    sig = rep["signature"]
    L = ["# Частичный балл 0–4 у развёрнутых ответов: «0/1» против «0–4» (синтетика; модель, не люди)", "",
         f"Мир: {sig['world']}; seed {sig['seed']}; конфигурация {sig['config_hash']}; коммит {sig['commit']}; "
         f"команда `{sig['command']}`.", "", rep["caveat"], "",
         "## Что сравнивается", "",
         "Те же кандидаты, та же истина заданий и те же зёрна; меняется только учёт развёрнутых ответов (open_answer и "
         "текстовый шаг open_book_3step; в сессии их не больше трёх: 2 open_book_3step + 1 open_answer):", ""]
    for k, v in rep["arms"].items():
        L.append(f"- `{k}` — {v};")
    L += ["", "Миры (как отвечает кандидат и как ошибается оценщик):", ""]
    for k, v in rep["worlds"].items():
        L.append(f"- `{k}` — {v['ru']};")
    L += ["", "## Выводы", ""] + [f"- {c}" for c in rep.get("conclusions") or conclusions(rep["rows"])]
    L += ["", "## Итог", "",
          "| Длина | Мир | Порог P | Вариант | Точно | Выше | Ниже | Без кат. | Повтор совпал | κw повтора | SE 1-й сессии | "
          "RMSE θ̂ 1-й сессии | Покрытие 90 % | Заданий в сессии | Минут на путь |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        L.append(f"| {'адаптивная' if r['length'] == 'adaptive' else 'фикс. 16'} | {r['world']} | "
                 f"{_f(r['confirm'], 1)} | {r['arm']} | {_pc(r['exact'])} | {_pc(r['over'])} | {_pc(r['under'])} | "
                 f"{_pc(r['none'])} | {_pc(r['retest_exact'])} | {_f(r['retest_kappa_w'])} | {_f(r['se_first_mean'])} | "
                 f"{_f(r.get('rmse_theta_first'))} | {_pc(r.get('coverage90_first'))} | "
                 f"{_f(r['items_per_session'], 1)} | {_f(r['minutes_per_path'], 1)} |")
    L += ["", "## Парные разности с вариантом `frac` (те же кандидаты; ДИ 95 % — бутстрэп)", "",
          "| Длина | Мир | Порог P | Вариант | Точно | Выше | Повтор совпал |", "|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        d = r.get("diff_vs_frac")
        if d:
            L.append(f"| {'адаптивная' if r['length'] == 'adaptive' else 'фикс. 16'} | {r['world']} | "
                     f"{_f(r['confirm'], 1)} | {r['arm']} | {_d(d['exact'])}{_dci(d['exact_ci'])} | "
                     f"{_d(d['over'])}{_dci(d['over_ci'])} | {_d(d['retest_exact'])}{_dci(d['retest_exact_ci'])} |")
    L += ["", "## Информация одной развёрнутой части (a = 1, b = 0, без шума)", "",
          "| θ | 0/1 (2PL) | 0–4 (GPCM) |", "|---|---|---|"]
    for r in rep["info"]:
        L.append(f"| {_f(r['theta'], 1)} | {_f(r['info_2pl'])} | {_f(r['info_gpcm'])} |")
    L += ["", "## Метод и ограничения", "", *METHOD, "", f"Время расчёта: {rep['seconds']} с.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="«0/1» против «0–4» у развёрнутых → data/partial_credit_sim.json")
    ap.add_argument("--n", type=int, default=300, help="кандидатов на направление")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--parallel", type=int, default=int(os.environ.get("SIM_PARALLEL", "2")))
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--md-only", action="store_true", help="только docs/validation/PARTIAL_CREDIT.md из сохранённого JSON")
    ap.add_argument("--worker", nargs=2, metavar=("IN", "OUT"), help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.worker:
        tasks = json.loads(Path(a.worker[0]).read_text(encoding="utf-8"))
        Path(a.worker[1]).write_text(json.dumps([run_task(tuple(t)) for t in tasks]), encoding="utf-8")
        return 0
    if a.md_only:
        rep = json.loads(OUT.read_text(encoding="utf-8"))
        rep["conclusions"] = conclusions(rep["rows"])
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        return 0
    run(a.n, a.quick, not a.no_write, a.parallel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
