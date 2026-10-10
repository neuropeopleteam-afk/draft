"""Обоснование порога грейда «Стажёр» на шкале θ симуляцией теста платформы (строительные блоки — validation/sim.py).

Вопрос: где поставить порог intern ниже порога Junior (−1,0), чтобы на текущем банке (лёгких семейств для Стажёра
ещё нет — тест идёт по запасному набору из самых простых семейств Junior, см. assessment/intern_pool.py) тест
* различал «Стажёр подтверждён» и «не подтверждён» (ложные подтверждения ниже порога и ложные отказы выше — малы),
* заканчивался за разумное число заданий (не упирался в исчерпание пула),
* повторялся (согласие решения при повторной попытке),
* и при этом полоса Стажёра [cut, −1) была содержательной (заметная доля начинающих).

Для каждого порога-кандидата (−1,5; −1,75; −2,0; −2,25) прогоняются кандидаты с истинным θ на сетке от −3,0 до −0,5
(заявлен Стажёр), все 5 направлений, движок и настройки платформы: AppCATSession, классификационная остановка у
порогов, дотестирование у ближайшего порога, без ротации субпулов (как у Стажёра в продукте). Истина заданий =
предкалибровка + систематическая ошибка эксперта (как во всей симуляции /validation). Отдельно — тот же прогон
с синтетическими лёгкими семействами (b ≈ −2), чтобы оценить, что даст банк после добавления семейств для Стажёра.

Выбор порога — по правилу в ``choose_cut`` (критерии заданы заранее, цифры — результат прогона): берётся самый
низкий порог, при котором ложные подтверждения (истинное θ ≤ cut − 0,25) ≤ 10 %, ложные отказы (θ ≥ cut + 0,25)
≤ 20 % и доля сессий, упёршихся в исчерпание пула или максимум заданий, ≤ 25 %. Правило применяется к банку
с лёгкими семействами (целевое состояние после потока банка); для текущего банка ошибки показываются честно:
на нём ни один порог правилу не удовлетворяет — у самых простых семейств Junior (b ≥ −0,9) мало информации
при θ ≈ −2, SE не опускается ниже ≈ 0,48, и тест всегда доходит до максимума заданий.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time

import numpy as np
from scipy import stats

from assessment_bank.psychometrics import ExposureControl, PoolItem
from assessment_bank.simulation import Person, make_responder, make_truth

from app.modules.assessment.grades import CONFIRM_LEVEL, UPGRADE_LEVEL
from app.modules.assessment.intern_pool import intern_exclusions
from app.modules.catalog.seed_data import GRADE_CUTS
from app.modules.validation.sim import DIRECTIONS, AppConfig, app_config_from_settings, make_pool, run_session

DATA = Path(__file__).resolve().parent / "data" / "intern_cut.json"
CANDIDATE_CUTS = (-1.5, -1.75, -2.0, -2.25)
THETA_GRID = tuple(round(x, 2) for x in np.arange(-3.0, -0.49, 0.25))
RULE = {"max_false_confirm": 0.10, "max_false_reject": 0.20, "max_exhausted": 0.25, "margin": 0.25}


def _cfg_for_cut(base: AppConfig, cut: float) -> AppConfig:
    cuts = tuple(sorted({cut, *[GRADE_CUTS[g] for g in ("junior", "middle", "senior")]}))
    return replace(base, cuts=cuts, start_theta={**base.start_theta, "intern": round(cut + 0.5, 3)},
                   subpools=1, rotation="subpool")


def _p_at_least(theta: float, se: float, cut: float) -> float:
    return float(stats.norm.sf((cut - theta) / max(se, 1e-6)))


def synthetic_easy_families(pool: list[PoolItem], rng: np.random.Generator, per_block: int = 6) -> list[PoolItem]:
    """Синтетические лёгкие семейства (как попросили у банка): закрытые форматы, b ~ U(−2,5; −1,5), 90–180 с."""
    out = list(pool)
    for block in ("common", *DIRECTIONS):
        for k in range(per_block):
            b = float(rng.uniform(-2.5, -1.5))
            fmt = ("mcq_concept", "predict_output", "find_bug")[k % 3]
            t = float(rng.choice([90.0, 120.0, 150.0, 180.0]))
            out.append(PoolItem(f"synthetic.{block}.easy_{k}", block, fmt, ("intern",), False,
                                np.array([1.0]), np.array([b]), np.array([0.25]), t, float(np.log(0.45 * t))))
    return out


def run_cut(pool, truth, direction: str, cut: float, base: AppConfig, rng: np.random.Generator,
            n_per_theta: int, thetas=THETA_GRID) -> dict:
    cfg = _cfg_for_cut(base, cut)
    excl = intern_exclusions(pool, direction)
    rows = []
    for th in thetas:
        for _ in range(n_per_theta):
            person = Person(theta=float(th), tau=float(rng.normal(0, 0.3)), claimed="intern")
            responder = make_responder(person, truth)
            sess, res = run_session(pool, direction, responder, cfg, ExposureControl(0.3), "intern", None, rng,
                                    exclude=excl)
            p = _p_at_least(res.theta, res.se, cut)
            rows.append({"theta": float(th), "est": res.theta, "se": res.se, "n": res.n_items, "time_s": res.time_used_s,
                         "stop": res.stop_reason, "n_ext": sess.n_ext, "confirmed": p >= CONFIRM_LEVEL,
                         "upgrade": p >= CONFIRM_LEVEL and _p_at_least(res.theta, res.se, -1.0) >= UPGRADE_LEVEL,
                         "families": [a.family_id for a in res.administered if not a.canary]})
    return {"cut": cut, "rows": rows}


def summarize_cut(run: dict, margin: float = RULE["margin"]) -> dict:
    cut, rows = run["cut"], run["rows"]
    th = np.array([r["theta"] for r in rows])
    conf = np.array([r["confirmed"] for r in rows])
    upg = np.array([r["upgrade"] for r in rows])
    stop = np.array([r["stop"] for r in rows])
    below, above = th <= cut - margin, th >= cut + margin
    band = (th >= cut) & (th < -1.0)
    junior_zone = th >= -0.75
    exhausted = np.isin(stop, ["pool_exhausted", "max_items", "extension_pool_exhausted"])
    by_theta = []
    for t in sorted(set(th.tolist())):
        m = th == t
        by_theta.append({"theta": t, "confirm_rate": round(float(conf[m].mean()), 3),
                         "upgrade_rate": round(float(upg[m].mean()), 3),
                         "mean_items": round(float(np.mean([r["n"] for r, k in zip(rows, m) if k])), 1),
                         "mean_se": round(float(np.mean([r["se"] for r, k in zip(rows, m) if k])), 3)})
    return {
        "cut": cut, "n_sessions": len(rows),
        "false_confirm": round(float(conf[below].mean()), 3) if below.any() else None,
        "false_reject": round(float(1 - conf[above].mean()), 3) if above.any() else None,
        "band_confirm": round(float(conf[band].mean()), 3) if band.any() else None,
        "band_upgrade": round(float(upg[band].mean()), 3) if band.any() else None,
        "junior_zone_upgrade": round(float(upg[junior_zone].mean()), 3) if junior_zone.any() else None,
        "mean_items": round(float(np.mean([r["n"] for r in rows])), 2),
        "mean_time_min": round(float(np.mean([r["time_s"] for r in rows]) / 60), 1),
        "mean_se": round(float(np.mean([r["se"] for r in rows])), 3),
        "extension_share": round(float(np.mean([r["n_ext"] > 0 for r in rows])), 3),
        "exhausted_share": round(float(exhausted.mean()), 3),
        "stop_reasons": {k: int(v) for k, v in zip(*np.unique(stop, return_counts=True))},
        "pop_share_band": round(float(stats.norm.cdf(-1.0) - stats.norm.cdf(cut)), 3),
        "pop_share_below": round(float(stats.norm.cdf(cut)), 3),
        "by_theta": by_theta,
    }


def retest_agreement(pool, truth, direction: str, cut: float, base: AppConfig, rng, n: int = 60) -> dict:
    """Повтор: те же люди (θ ~ N(−1,5; 0,5)), вторая попытка без семейств первой в дотестировании."""
    cfg = _cfg_for_cut(base, cut)
    excl = intern_exclusions(pool, direction)
    people = [Person(theta=float(rng.normal(-1.5, 0.5)), tau=float(rng.normal(0, 0.3)), claimed="intern")
              for _ in range(n)]
    c1, c2, t1, t2 = [], [], [], []
    for p in people:
        resp = make_responder(p, truth)
        _, r1 = run_session(pool, direction, resp, cfg, ExposureControl(0.3), "intern", None, rng, exclude=excl)
        fams = {a.family_id for a in r1.administered if not a.canary}
        _, r2 = run_session(pool, direction, resp, cfg, ExposureControl(0.3), "intern", None, rng, exclude=excl,
                            exclude_ext=fams)
        c1.append(_p_at_least(r1.theta, r1.se, cut) >= CONFIRM_LEVEL)
        c2.append(_p_at_least(r2.theta, r2.se, cut) >= CONFIRM_LEVEL)
        t1.append(r1.theta)
        t2.append(r2.theta)
    c1, c2 = np.array(c1), np.array(c2)
    return {"n": n, "decision_agreement": round(float(np.mean(c1 == c2)), 3),
            "r_theta": round(float(np.corrcoef(t1, t2)[0, 1]), 3)}


def pool_information(pool, direction: str, cut: float) -> dict:
    """Запас информации пула Стажёра в точке порога: Σ I(cut) и минимально достижимая SE при всём пуле."""
    excl = set(intern_exclusions(pool, direction))
    items = [i for i in pool if not i.canary and i.block in ("common", direction) and i.family_id not in excl]
    info = float(sum(i.information(cut) for i in items))
    return {"n_families": len(items), "info_at_cut": round(info, 2), "min_se": round(1 / np.sqrt(1 + info), 3)}


def choose_cut(summaries: list[dict], rule: dict = RULE) -> dict:
    ok = [s for s in summaries if (s["false_confirm"] or 0) <= rule["max_false_confirm"]
          and (s["false_reject"] or 0) <= rule["max_false_reject"] and s["exhausted_share"] <= rule["max_exhausted"]]
    if not ok:
        best = min(summaries, key=lambda s: (s["false_confirm"] or 0) + (s["false_reject"] or 0))
        return {"cut": best["cut"], "all_pass": False, "passing": []}
    lowest = min(ok, key=lambda s: s["cut"])
    return {"cut": lowest["cut"], "all_pass": True, "passing": [s["cut"] for s in ok]}


def run(n_per_theta: int = 10, seed: int = 20261007, directions=DIRECTIONS, cuts=CANDIDATE_CUTS,
        synthetic: bool = True, retest_n: int = 40, quick: bool = False) -> dict:
    t0 = time.time()
    base = app_config_from_settings()
    rng = np.random.default_rng(seed)
    pool = make_pool(1)
    truth = make_truth(pool, rng)
    if quick:
        directions, cuts, n_per_theta, retest_n = directions[:1], cuts[1:3], 3, 10
    out: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": seed, "n_per_theta": n_per_theta,
                 "theta_grid": list(THETA_GRID), "candidate_cuts": list(cuts), "rule": RULE,
                 "config": {"min_items": base.min_items, "max_items": base.max_items, "ext_items": base.ext_items,
                            "classify_z": base.classify_z, "confirm_level": CONFIRM_LEVEL, "upgrade_level": UPGRADE_LEVEL},
                 "directions": list(directions), "by_cut": [], "pool": {}, "retest": {}}
    pooled: dict[float, list[dict]] = {c: [] for c in cuts}
    per_dir: dict[str, dict] = {}
    for d in directions:
        per_dir[d] = {}
        for c in cuts:
            r = run_cut(pool, truth, d, c, base, rng, n_per_theta)
            pooled[c].extend(r["rows"])
            per_dir[d][str(c)] = {k: v for k, v in summarize_cut(r).items() if k != "by_theta"}
        out["pool"][d] = {str(c): pool_information(pool, d, c) for c in cuts}
    out["by_cut"] = [summarize_cut({"cut": c, "rows": pooled[c]}) for c in cuts]
    out["by_direction"] = per_dir
    out["current_bank_rule"] = choose_cut(out["by_cut"])
    if synthetic:
        rng2 = np.random.default_rng(seed + 1)
        pool2 = synthetic_easy_families(pool, rng2)
        truth2 = {**truth, **make_truth([i for i in pool2 if i.family_id.startswith("synthetic.")], rng2)}
        easy = []
        for c in cuts:
            rows = []
            for d in directions:
                rows.extend(run_cut(pool2, truth2, d, c, base, rng2, n_per_theta)["rows"])
            easy.append(summarize_cut({"cut": c, "rows": rows}))
        out["with_easy_families"] = {"per_block": 6, "by_cut": easy,
                                     "pool": {d: {str(c): pool_information(pool2, d, c) for c in cuts} for d in directions}}
        out["chosen"] = {**choose_cut(easy), "basis": "with_easy_families"}
    else:
        out["chosen"] = {**out["current_bank_rule"], "basis": "current_bank"}
    chosen = out["chosen"]["cut"]
    for d in directions:
        out["retest"][d] = retest_agreement(pool, truth, d, chosen, base, rng, n=retest_n)
    out["families_used"] = sorted({f for rows in pooled.values() for r in rows for f in r["families"]})
    out["elapsed_s"] = round(time.time() - t0, 1)
    # Я8: подпись расчёта (коммит кода, банк, seed) — для строки происхождения на /validation; на числа не влияет
    from app.modules.validation.signature import signature
    out["signature"] = signature(seed=seed, config={**out["config"], "cuts": list(cuts), "n_per_theta": n_per_theta,
                                                    "synthetic": synthetic, "retest_n": retest_n, "quick": quick},
                                 world="симуляция теста у порога Стажёра: синтетические кандидаты на сетке θ, "
                                       "истина заданий = предкалибровка + ошибка эксперта",
                                 command="make intern-cut", n=n_per_theta * len(THETA_GRID) * len(directions))
    return out


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Симуляция порога грейда «Стажёр» → data/intern_cut.json")
    ap.add_argument("--n", type=int, default=10, help="кандидатов на точку сетки θ (на направление и порог)")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(DATA))
    a = ap.parse_args()
    res = run(n_per_theta=a.n, quick=a.quick)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in res["by_cut"]:
        print(f"cut {s['cut']:+.2f}: ложные подтверждения {s['false_confirm']}, ложные отказы {s['false_reject']}, "
              f"заданий {s['mean_items']}, SE {s['mean_se']}, исчерпание {s['exhausted_share']}, "
              f"полоса {s['pop_share_band']}")
    print("выбран порог:", res["chosen"], "за", res["elapsed_s"], "с")


if __name__ == "__main__":
    main()
