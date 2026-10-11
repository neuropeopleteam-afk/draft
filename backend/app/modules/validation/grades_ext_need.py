"""Что нужно, чтобы тест различал Lead и Principal не хуже остальных уровней (симуляция, модель — не люди).

    make grades-ext-need     # cd backend && GRADES_EXT_ENABLED=1 python -m app.modules.validation.grades_ext_need

Цель (решение владельца 10.10): точно истинный уровень ≥ 64 % отдельно для Lead и для Principal при завышении ≤ 7 %.
Тот же путь кандидата, что в grades_ext_sim / path_retest, на шкале из 6 уровней; меняется только то, что перечислено:

* (а) банк Lead/Principal: число семейств на направление и в общем блоке (кратно ожидаемому: направление — Lead
  1 короткое + 1 развёрнутое, Principal 1 развёрнутое; общий — Lead 2 + 2, Principal 1 + 1), наклон a, трудность
  b ~ U(1,6; 2,4) у Lead и U(2,6; 3,2) у Principal; короткие — расчётные задания (лимит 5–7 мин), развёрнутые —
  архитектурные ответы (20 мин, в основной части теста — не больше одного, как сейчас);
* (б) отдельный адаптивный блок «Lead/Principal» после основной части — тем, кто заявил Lead/Principal, и тем, кто
  подтвердил Senior с θ̂, не исключающим Lead (θ̂ + z·SE ≥ порога Lead): до K коротких трудных заданий за ≤ 25 мин,
  информация — в неопределённом пороге Lead или Principal, остановка, когда оба определены; оценка θ по всем ответам
  с априорным SD 1,5; итог — самый высокий уровень, доказанный с уверенностью confirm (P(θ ≥ порога) ≥ confirm);
* (в) частичный балл 0–4 у развёрнутых архитектурных заданий (рубрика с доказательствами) вместо 0/1: четыре
  ступени b ± 0,25 / 0,75 с наклоном 0,8·a (поправка на зависимость ступеней одного ответа — оценка не завышена
  в пользу варианта);
* (г) сочетания; порог уверенности решения confirm 0,8 (сейчас в продукте) и 0,6 (предложение по точности уровня).

Миры: «верх» θ ~ U(0,5; 3,75) — числа по Senior, Lead, Principal; «популяция» N(0; 1) — общее завышение.
Результат — data/grades_ext_need.json и docs/validation/GRADES_EXT_NEED.md. Тяжёлое — на сервере проверок.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

from app.modules.catalog import seed_data

if not seed_data.GRADES_EXT:
    raise SystemExit("grades_ext_need: запускать с GRADES_EXT_ENABLED=1 (make grades-ext-need)")

from assessment_bank.psychometrics import CanaryDetector, ExposureControl  # noqa: E402
from assessment_bank.simulation import Person, _timed, make_responder, make_truth  # noqa: E402

from app.modules.assessment import grades as grades_mod  # noqa: E402
from app.modules.assessment import rules as rules_mod  # noqa: E402
from app.modules.assessment.bank_engine import stack_excluded  # noqa: E402
from app.modules.assessment.exposure import choose_subpool, exposure_table  # noqa: E402
from app.modules.validation import grades_ext_sim as gx  # noqa: E402
from app.modules.validation import path_retest as pr  # noqa: E402
from app.modules.validation import sim  # noqa: E402
from app.modules.validation.signature import signature  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "grades_ext_need.json"
DOCS_MD = HERE.parents[3] / "docs" / "validation" / "GRADES_EXT_NEED.md"
SEED = 20261011
LEVELS = gx.LEVELS
EXT = seed_data.EXT_GRADE_ORDER
# ожидаемый банк (карточка банка волны 7, состав Я23/Я24): (коротких, развёрнутых) на уровень
BANK_UNIT = {"own": {"lead": (1, 1), "principal": (0, 1)}, "common": {"lead": (2, 2), "principal": (1, 1)}}
B_RANGE = {"lead": (1.6, 2.4), "principal": (2.6, 3.2)}
SHORT_FORMATS = ("choose_fix", "mcq_concept", "find_bug", "predict_output")
BLOCK_ITEM_TIME_S = 420.0

# сценарии: mult — кратность банка, a — наклон, block — заданий в блоке (0 — нет), partial — 0–4 у развёрнутых,
# short_mult — дополнительная кратность только коротких заданий (для блока нужны короткие)
SCENARIOS = {
    "base": dict(mult=1, a=1.5, block=0, partial=False),
    "a_x2": dict(mult=2, a=1.5, block=0, partial=False),
    "a_x3": dict(mult=3, a=1.5, block=0, partial=False),
    "a_x4": dict(mult=4, a=1.5, block=0, partial=False),
    "a_x2_a1.2": dict(mult=2, a=1.2, block=0, partial=False),
    "a_x2_a2.0": dict(mult=2, a=2.0, block=0, partial=False),
    "b_k10_x1": dict(mult=1, a=1.5, block=10, partial=False),
    "b_k15_x2": dict(mult=2, a=1.5, block=15, partial=False),
    "b_k15_x3": dict(mult=3, a=1.5, block=15, partial=False),
    "b_k15_s4": dict(mult=1, a=1.5, block=15, partial=False, short_mult=4),
    "c_x1": dict(mult=1, a=1.5, block=0, partial=True),
    "c_x2": dict(mult=2, a=1.5, block=0, partial=True),
    "d_k15_c_x1": dict(mult=1, a=1.5, block=15, partial=True),
    "d_k15_c_x2": dict(mult=2, a=1.5, block=15, partial=True),
    "d_k15_c_x3": dict(mult=3, a=1.5, block=15, partial=True),
    "d_k15_c_s4": dict(mult=1, a=1.5, block=15, partial=True, short_mult=4),
    "d_k15_c_s6": dict(mult=1, a=1.5, block=15, partial=True, short_mult=6),
    "d_k15_c_x3_a2.0": dict(mult=3, a=2.0, block=15, partial=True),
    # запас на случай, если 15 заданий и ×4 коротких мало: блок 20, коротких ×6–×8
    "b_k20_s8": dict(mult=1, a=1.5, block=20, partial=False, short_mult=8),
    "d_k15_c_s8": dict(mult=1, a=1.5, block=15, partial=True, short_mult=8),
    "d_k20_c_s6": dict(mult=1, a=1.5, block=20, partial=True, short_mult=6),
    "d_k20_c_s8": dict(mult=1, a=1.5, block=20, partial=True, short_mult=8),
    "d_k20_c_x2_s4": dict(mult=2, a=1.5, block=20, partial=True, short_mult=4),
    # после полного прогона 11.10: вклад частичного балла, блок короче, запас по Principal
    "b_k20_x2_s4": dict(mult=2, a=1.5, block=20, partial=False, short_mult=4),
    "d_k15_c_x2_s4": dict(mult=2, a=1.5, block=15, partial=True, short_mult=4),
    "d_k20_c_x3_s4": dict(mult=3, a=1.5, block=20, partial=True, short_mult=4),
    # короткие — только в общем блоке (common_short_mult), у направления — как в банке сейчас (own_short_mult 1);
    # o2 — развёрнутых ×2 (близко к банку Я23/Я24 на 11.10: общий Lead 4 + Principal 2, у направления по 1–2)
    "d_k20_c_cs8": dict(mult=1, a=1.5, block=20, partial=True, common_short_mult=8, own_short_mult=1),
    "d_k20_c_o2_cs8": dict(mult=2, a=1.5, block=20, partial=True, common_short_mult=4, own_short_mult=0.5),
    "d_k20_c_o2_cs8_os4": dict(mult=2, a=1.5, block=20, partial=True, common_short_mult=4, own_short_mult=2),
    "b_k20_o2_cs8": dict(mult=2, a=1.5, block=20, partial=False, common_short_mult=4, own_short_mult=0.5),
}


def _short_mults(s: dict) -> tuple[float, float]:
    """Кратность коротких заданий (сверх mult): (у направления, в общем блоке)."""
    sm = s.get("short_mult", 1)
    return s.get("own_short_mult", sm), s.get("common_short_mult", sm)


def _x(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def scen_text(s: dict) -> str:
    so, sc = _short_mults(s)
    m = s["mult"]
    if so == sc:
        head = f"банк ×{m}" + (f", коротких ×{_x(m * so)}" if so != 1 else "")
    else:
        head = f"развёрнутых ×{m}, коротких: общий ×{_x(m * sc)}, направление ×{_x(m * so)}"
    parts = [head, f"a {s['a']}"]
    parts.append(f"блок {s['block']} заданий" if s["block"] else "без блока")
    parts.append("частичный балл 0–4" if s["partial"] else "развёрнутые 0/1")
    return ", ".join(parts)


def bank_counts(s: dict) -> dict:
    so, sc = _short_mults(s)
    out = {}
    for blk, by in BANK_UNIT.items():
        sm = sc if blk == "common" else so
        out[blk] = {g: (int(round(n_s * s["mult"] * sm)), n_o * s["mult"]) for g, (n_s, n_o) in by.items()}
    return out


# ---------------------------------------------------------------- модельный банк Lead/Principal

def _sources(pool, block: str):
    cand = [p for p in pool if p.block == block and not p.canary]
    short = sorted([p for p in cand if p.format in SHORT_FORMATS and p.time_limit_s <= BLOCK_ITEM_TIME_S],
                   key=lambda p: -float(np.mean(p.b)))[:6]
    opn = [p for p in cand if p.format == "open_answer"] or \
        [p for p in pool if p.format == "open_answer" and not p.canary]
    return short, opn


def model_bank(pool, s: dict, n_subpools: int, rng: np.random.Generator) -> list:
    out = []
    counts = bank_counts(s)
    for block in ("common",) + sim.DIRECTIONS:
        short_src, open_src = _sources(pool, block)
        c = counts["common" if block == "common" else "own"]
        for g in EXT:
            n_s, n_o = c[g]
            for kind, n, src in (("s", n_s, short_src), ("o", n_o, open_src)):
                for k in range(n):
                    base = src[k % len(src)]
                    it = deepcopy(base)
                    target = float(rng.uniform(*B_RANGE[g]))
                    if kind == "o" and s["partial"]:  # 0–4 по рубрике: четыре ступени вокруг трудности ответа
                        it.b = target + np.array([-0.75, -0.25, 0.25, 0.75])
                        it.a = np.full(4, 0.8 * s["a"])
                        it.sigma = np.full(4, float(np.mean(base.sigma)))
                    else:
                        it.b = np.asarray(base.b, dtype=float) - float(np.mean(base.b)) + target
                        it.a = np.full_like(np.asarray(base.a, dtype=float), s["a"])
                    it.family_id = f"model.{g}.{block}.{kind}{k + 1}"
                    it.grades = (g,)
                    it.subpool = k % max(1, n_subpools)
                    out.append(it)
    return out


# ---------------------------------------------------------------- сессия, блок Lead/Principal, путь

def run_session_x(pool, cand, truth, cfg, counter, claimed, history, rng, det, s: dict, confirm: float):
    d = cand.direction
    prev_sp = [h["subpool"] for h in history if h["subpool"] is not None]
    sp = choose_subpool(cfg.subpools, int(rng.integers(2 ** 31)), prev_sp)
    excl = set(stack_excluded(cand.stack))
    seen = {f: age for age, h in reversed(list(enumerate(history))) for f in h["families"]}
    person = Person(cand.theta, cand.tau, claimed)
    responder = make_responder(person, truth)
    sess, res = sim.run_session(pool, d, responder, cfg, counter, claimed, sp, rng, exclude=sorted(excl), seen=seen)
    theta, se = float(res.theta), float(res.se)
    n_block = 0
    block_time = 0.0
    # шкала — общая из 6 уровней (direction=None): в модели у всех направлений есть банк Lead/Principal
    dec = grades_mod.decide_grade(theta, se, claimed, confirm_level=confirm, n_items=int(res.n_items))
    cut_l, cut_p = seed_data.GRADE_CUTS["lead"], seed_data.GRADE_CUTS["principal"]
    z = cfg.classify_z
    trig = s["block"] > 0 and theta + z * se >= cut_l and (claimed in EXT or (claimed == "senior" and dec.confirmed))
    if trig:
        sess.cfg = replace(sess.cfg, prior_sd=1.5)
        sess._update_theta()
        t0 = sess.time_used
        hard = [p for p in pool if p.grades and p.grades[0] in EXT and p.block in ("common", d)
                and p.time_limit_s <= BLOCK_ITEM_TIME_S]
        while n_block < s["block"]:
            unc = [c for c in (cut_l, cut_p) if abs(sess.theta - c) < z * sess.se]
            if not unc:
                break
            target = min(unc, key=lambda c: abs(sess.theta - c))
            left = 25 * 60 - (sess.time_used - t0)
            cands = [p for p in hard if p.family_id not in sess.used and p.family_id not in seen
                     and p.time_limit_s <= left]
            if not cands:
                break
            item = max(cands, key=lambda p: p.information(target))
            x, log_t = responder(item, rng)
            sess.record(item, x, log_t, time_s=float(np.exp(log_t)) if log_t is not None else None)
            n_block += 1
        block_time = sess.time_used - t0
        theta, se = float(sess.theta), float(sess.se)
    clean, canary, idx = _timed(sess, sess.result())
    st = det.statistic(clean, canary)
    if st.flagged:
        mask = det.suspicious_mask(clean, st.tau_clean)
        ex = {idx[i] for i in np.flatnonzero(mask)}
        if ex and len(ex) < len(idx):
            theta, se = (float(v) for v in sess.rescore(ex))
    n_scored = int(sess.n_scored)
    if trig:  # итог блока: самый высокий уровень, доказанный с уверенностью confirm, с потолком полного теста
        lvl = grades_mod.category_level(theta, se, n_scored, confirm)
        block_grade = lvl.grade
    else:
        block_grade = None
    dec = grades_mod.decide_grade(theta, se, claimed, confirm_level=confirm, n_items=n_scored)
    fams = [a.family_id for a in sess.administered if not a.canary]
    history.insert(0, {"subpool": sp, "families": fams})
    rec = {"claimed": claimed, "theta": theta, "se": se, "n_items": n_scored, "time_s": float(sess.time_used),
           "families": fams, "confirmed": bool(dec.confirmed), "n_block": n_block, "block_time_s": block_time,
           "block_grade": block_grade}
    return rec, dec


def run_path_x(pool, cand, truth, cfg, counter, history, rng, det, s: dict, confirm: float) -> dict:
    g = cand.claimed
    tests = []
    final, status = "none", "none"
    for step in range(2):
        rec, dec = run_session_x(pool, cand, truth, cfg, counter, g, history, rng, det, s, confirm)
        tests.append(rec)
        bg = rec["block_grade"]
        if bg is not None and bg != "none" and seed_data.GRADE_LEVEL[bg] >= seed_data.GRADE_LEVEL["senior"]:
            final = bg
            status = "confirmed" if seed_data.GRADE_LEVEL[bg] >= seed_data.GRADE_LEVEL[g] else "accepted_lower"
            break
        if dec.confirmed:
            final, status = g, "confirmed"
            break
        if dec.provisional:
            final, status = "junior", "provisional"
            break
        lower, _ = rules_mod.accept_lower_allowed(None, g, False, dec.probabilities)
        if lower:
            final, status = lower, "accepted_lower"
            break
        if step == 0 and g != "intern":
            g = seed_data.GRADE_ORDER[seed_data.GRADE_ORDER.index(g) - 1]
            continue
        break
    return {"grade": final, "level": LEVELS.index(final), "status": status, "tests": tests,
            "families": sorted({f for t in tests for f in t["families"]})}


def worker(a) -> dict:
    s = SCENARIOS[a.scenario]
    confirm = a.confirm
    gx.patch_ext_sessions(1.5, True)  # как продукт: заявленный Lead/Principal — без ротации, априорное SD 1,5
    # порог уверенности принятия уровня ниже — тот же confirm (как настройка ASSESSMENT_CONFIRM_LEVEL)
    rules_mod.proved_lower = functools.partial(rules_mod.proved_lower, level=confirm)
    cfg = sim.app_config_from_settings()
    base = sim.make_pool(cfg.subpools)
    bseed = [SEED, 7, list(SCENARIOS).index(a.scenario)] + ([a.rep] if a.rep else [])  # rep — другая реализация банка
    extra = model_bank(base, s, cfg.subpools, np.random.default_rng(bseed))
    pool = list(base) + extra
    i = sim.DIRECTIONS.index(a.direction)
    wi = list(gx.WORLDS).index(a.world)
    rng0 = np.random.default_rng([SEED, i, wi])  # те же кандидаты и истина во всех сценариях направления и мира
    truth = make_truth(pool, None, misspec=0.5, seed=SEED)
    cands = gx.make_candidates(a.n, a.direction, a.world, rng0)
    k = (exposure_table() or {}).get("k", {}).get(a.direction, {})
    counter = ExposureControl(0.3, k=dict(k))
    det = CanaryDetector()
    rng = np.random.default_rng([SEED, i, wi, 1])
    rows = []
    for c in cands:
        hist: list[dict] = []
        r1 = run_path_x(pool, c, truth, cfg, counter, hist, rng, det, s, confirm)
        r2 = run_path_x(pool, c, truth, cfg, counter, hist, rng, det, s, confirm)
        rows.append({"theta": c.theta, "true": LEVELS.index(grades_mod.point_grade(c.theta)), "claimed": c.claimed,
                     "l1": r1["level"], "l2": r2["level"], "t1": sum(t["time_s"] for t in r1["tests"]) / 60.0,
                     "block": sum(t["n_block"] for t in r1["tests"]),
                     "block_min": sum(t["block_time_s"] for t in r1["tests"]) / 60.0})
    return {"scenario": a.scenario, "confirm": confirm, "world": a.world, "direction": a.direction, "rows": rows,
            "n_model": len(extra), "rep": a.rep}


def summarize(rows: list[dict]) -> dict:
    true = np.array([r["true"] for r in rows])
    l1, l2 = np.array([r["l1"] for r in rows]), np.array([r["l2"] for r in rows])
    t = np.array([r["t1"] for r in rows])
    out = {"n": len(rows), "exact": round(float(np.mean(l1 == true)), 3), "above": round(float(np.mean(l1 > true)), 3),
           "below": round(float(np.mean((l1 < true) & (l1 > 0))), 3), "none": round(float(np.mean(l1 == 0)), 3),
           "retest_exact": round(float(np.mean(l1 == l2)), 3),
           "minutes_mean": round(float(t.mean()), 1), "minutes_p90": round(float(np.percentile(t, 90)), 1),
           "block_share": round(float(np.mean([r["block"] > 0 for r in rows])), 3)}
    # завышение именно за счёт Lead/Principal: присвоен Lead/Principal выше истинного уровня
    lo = LEVELS.index(EXT[0])
    ext = l1 >= lo
    out["ext_assigned"] = round(float(np.mean(ext)), 3)
    out["above_ext"] = round(float(np.mean(ext & (l1 > true))), 3)
    out["ext_false_share"] = round(float(np.mean(l1[ext] > true[ext])), 3) if ext.any() else None
    by = {}
    for lv, name in enumerate(LEVELS):
        m = true == lv
        if m.sum() < 5:
            continue
        g, tt = l1[m], t[m]
        bm = np.array([r["block_min"] for r, mm in zip(rows, m, strict=True) if mm])
        by[name] = {"n": int(m.sum()), "exact": round(float(np.mean(g == lv)), 3),
                    "above": round(float(np.mean(g > lv)), 3), "below": round(float(np.mean(g < lv)), 3),
                    "minutes_mean": round(float(tt.mean()), 1), "minutes_p90": round(float(np.percentile(tt, 90)), 1),
                    "block_minutes_mean": round(float(bm.mean()), 1)}
    out["by_true_level"] = by
    return out


def _key(sc: str, cf: float, w: str, rep: int) -> str:
    return f"{sc}|{cf}|{w}" + (f"|r{rep}" if rep else "")


def run(n: int, scenarios: list[str], confirms: list[float], worlds: list[str], parallel: int,
        merge: bool, write: bool = True, reps: list[int] | None = None) -> dict:
    t0 = time.time()
    reps = reps or [0]
    jobs = [(sc, cf, w, d, r) for sc in scenarios for cf in confirms for w in worlds for r in reps
            for d in sim.DIRECTIONS]
    tmp = Path(tempfile.mkdtemp(prefix="gneed_"))
    env = {**os.environ, "GRADES_EXT_ENABLED": "1"}
    procs, results, pending = [], [], list(jobs)
    while pending or procs:
        while pending and len(procs) < parallel:
            sc, cf, w, d, r = pending.pop(0)
            out = tmp / f"{sc}_{cf}_{w}_{d}_r{r}.json"
            p = subprocess.Popen([sys.executable, "-m", "app.modules.validation.grades_ext_need", "--worker",
                                  "--scenario", sc, "--confirm", str(cf), "--world", w, "--direction", d,
                                  "--n", str(n), "--rep", str(r), "--out", str(out)], env=env)
            procs.append((p, out))
        time.sleep(0.5)
        for p, out in list(procs):
            if p.poll() is not None:
                procs.remove((p, out))
                if p.returncode != 0:
                    raise SystemExit(f"рабочий процесс упал: {out.name} (код {p.returncode})")
                results.append(json.loads(out.read_text()))
    rep = {"variants": {}}
    for sc in scenarios:
        for cf in confirms:
            for w in worlds:
                for rp in reps:
                    rows = [r for x in results if (x["scenario"], x["confirm"], x["world"], x.get("rep", 0)) ==
                            (sc, cf, w, rp) for r in x["rows"]]
                    rep["variants"][_key(sc, cf, w, rp)] = {
                        "scenario": sc, "confirm": cf, "world": w, "rep": rp,
                        "text": scen_text(SCENARIOS[sc]) + (f" · банк, реализация {rp + 1}" if rp else ""),
                        "bank": bank_counts(SCENARIOS[sc]), **SCENARIOS[sc], **summarize(rows)}
    if merge and OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        rep["variants"] = {**old.get("variants", {}), **rep["variants"]}
    cfg_sig = {"scenarios": {k: SCENARIOS[k] for k in scenarios}, "bank_unit": BANK_UNIT, "b_range": B_RANGE,
               "n_per_direction": n, "confirms": confirms, "worlds": worlds}
    rep["signature"] = signature(seed=SEED, config=cfg_sig, n=n * len(sim.DIRECTIONS),
                                 world="симуляция 6 уровней: модельный банк Lead/Principal, блок Lead/Principal, "
                                       "частичный балл; модель, не люди", command="make grades-ext-need")
    rep["target"] = {"exact_lead": 0.64, "exact_principal": 0.64, "above_max": 0.07}
    rep["seconds"] = round(time.time() - t0, 1)
    if write:
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
    return rep


def _p(v) -> str:
    return "—" if v is None else f"{v * 100:.1f} %".replace(".", ",")


def _n(v) -> str:
    return "—" if v is None else f"{v:.1f}".replace(".", ",")


def markdown(rep: dict) -> str:
    sig = rep["signature"]
    L = ["# Lead и Principal: что нужно для точности не ниже остальных уровней (симуляция)", "",
         "> Модель, не люди: синтетические кандидаты, модельный банк Lead/Principal (параметры, а не задания), ошибка "
         "эксперта в трудности σ = 0,5. Цель — точно истинный уровень ≥ 64 % для Lead и для Principal, завышение "
         "≤ 7 %.", "",
         f"Подпись: {sig.get('world')}; seed {sig.get('seed')}; коммит {sig.get('commit') or '—'}; "
         f"команда `{sig.get('command')}`.", "",
         "Банк ×1 — ожидаемый по карточке банка: направление — Lead 1 короткое + 1 развёрнутое, Principal 1 развёрнутое; "
         "общий блок — Lead 2 + 2, Principal 1 + 1. Блок — до K коротких трудных заданий за ≤ 25 мин после основной "
         "части (тем, кто заявил Lead/Principal, и подтвердившим Senior с θ̂, не исключающим Lead).", "",
         "| Сценарий | confirm | Мир | Lead точно | Principal точно | Senior точно | Выше (все) | "
         "Выше: присвоен Lead/Principal | Ниже (все) | Мин Lead/Principal (ср.) | Блок, мин (ср., Lead) | Цель |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in rep["variants"].values():
        b = v.get("by_true_level", {})
        lead, prc, sen = b.get("lead", {}), b.get("principal", {}), b.get("senior", {})
        ok = (lead.get("exact", 0) >= 0.64 and prc.get("exact", 0) >= 0.64 and v["above"] <= 0.07)
        ok_txt = "да" if ok else ("—" if v["world"] == "pop" else "нет")
        mins = [x.get("minutes_mean") for x in (lead, prc) if x.get("minutes_mean") is not None]
        L.append(f"| {v['text']} | {_n(v['confirm'])} | {v['world']} | {_p(lead.get('exact'))} | {_p(prc.get('exact'))} | "
                 f"{_p(sen.get('exact'))} | {_p(v['above'])} | {_p(v.get('above_ext'))} | {_p(v['below'])} | "
                 f"{_n(np.mean(mins)) if mins else '—'} | {_n(lead.get('block_minutes_mean'))} | {ok_txt} |")
    L += ["", "Семейств Lead/Principal на одно направление (своих) и в общем блоке — по сценарию: "
          "кратность × (короткие, развёрнутые) из строки банка ×1.", ""]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--confirms", default="0.8,0.6")
    ap.add_argument("--worlds", default="top")
    ap.add_argument("--parallel", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--scenario", default="base")
    ap.add_argument("--confirm", type=float, default=0.8)
    ap.add_argument("--world", default="top")
    ap.add_argument("--direction", default="backend")
    ap.add_argument("--out")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--reps", default="0", help="реализации модельного банка: 0,1,2… (0 — как в основном прогоне)")
    a = ap.parse_args()
    if a.worker:
        Path(a.out).write_text(json.dumps(worker(a)), encoding="utf-8")
        return 0
    rep = run(a.n, a.scenarios.split(","), [float(x) for x in a.confirms.split(",")], a.worlds.split(","),
              a.parallel, a.merge, write=not a.no_write, reps=[int(x) for x in a.reps.split(",")])
    for key, v in rep["variants"].items():
        b = v["by_true_level"]
        print(f"{key}: Lead {b.get('lead', {}).get('exact')}, Principal {b.get('principal', {}).get('exact')}, "
              f"Senior {b.get('senior', {}).get('exact')}, выше {v['above']}, мин {v['minutes_mean']}")
    print(f"{rep['seconds']} с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
