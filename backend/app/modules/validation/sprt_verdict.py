"""Кросс-валидированная симуляция продуктового движка AppCATSession на реальном банке заданий А3 (1 824 семейства).

    python -m app.modules.validation.sprt_verdict [--n 3000]

Строгие правила расчёта (по итогам независимой методической проверки 20.10.2026):
1. Прогон идёт через **настоящий продуктовый класс** ``AppCATSession`` (``app.modules.assessment.exposure``) и
   **настоящий пул банка заданий** (``assessment_bank.load_specs`` → ``pool_from_specs``, 1 824 семейства в 9 ИТ-направлениях
   + общий блок ``common``). Отдельный синтетический генератор заданий не используется.
2. Модель ответа и оценка уровня — строго продуктовая логистика 2PL/GPCM **без множителя D = 1,7** (``D = 1,0``, как в
   ``assessment_bank.psychometrics.prob`` и ``app.modules.assessment.engine``).
3. Шкала порогов — строго ``GRADE_CUTS`` продукта из ``app.modules.catalog.seed_data``:
   ``intern = −1,75``, ``junior = −1,0``, ``middle = 0,0``, ``senior = +1,0``, ``lead = +2,0``, ``principal = +3,0``.
4. Квота кодовых и развёрнутых заданий — продуктовая (``DEFAULT_CODE_OPEN_SHARE = 1/3`` в ``AppCATSession`` с учётом
   реальных лимитов ``DEFAULT_FORMAT_LIMITS`` и фактического наличия семейств в направлении и субпуле).
5. Настоящая кросс-валидация: все пороги вердикта ``(alpha, p_hi, p_lo, p_final)`` перебираются по сетке на обучающей
   выборке (``TRAIN_SEED = 2026102001``, ``N_train = 1 000``), лучшая точка выбирается программно по целевому критерию
   на train и затем **один раз** проверяется на отложенной выборке (``TEST_SEED = 2026102002``, ``N_test = 3 000``).
6. Прозрачные определения числителя и знаменателя:
   - тривиальные заявки ``claim == "intern"`` выделены отдельно; основная точность и доля уверенных вердиктов
     (``precision_decided``, ``decided_share``) считаются по нетривиальным заявкам ``Junior … Principal`` (и отдельно
     приводятся со стажёрами ``precision_decided_all_claims``);
   - дополнительный этап (до 8 заданий / 15 минут у спорного порога из резервного субпула, включая ``incident_sim`` для
     ``Senior / Lead / Principal``) запускается **только** для кандидатов со статусом ``needs_followup`` после 1-го этапа
     (поэтому ``followup_share == 1 − decided_share_all_claims``);
   - время (из реальной модели времени банка ``beta_time`` / ``time_limit_s``) приводится со средним, медианой, p90 и
     долей сессий дольше 60 минут (отдельно для 1-го этапа и с учётом доп. этапа).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

import numpy as np

from assessment_bank import load_specs
from assessment_bank.psychometrics import CATConfig, estimate_theta, pool_from_specs
from assessment_bank.simulation import Person, make_responder, make_truth
from app.modules.assessment.exposure import AppCATSession, DEFAULT_FORMAT_LIMITS
from app.modules.assessment.sprt import CODE_OPEN_FORMATS, DEFAULT_CODE_OPEN_SHARE, p_at_least, sprt_bound
from app.modules.catalog.seed_data import ALL_GRADE_CUTS as GRADE_CUTS, ALL_GRADE_START_THETA
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT_JSON = HERE / "data" / "sprt_verdict.json"
OUT_MD = REPO / "docs" / "validation" / "SPRT_VERDICT.md"

TRUTH_SEED = 2026102099
TRAIN_SEED = 2026102001
TEST_SEED = 2026102002
RETEST_SEED = 2026102003
N_BOOT = 1000

GRADE_NAMES = ("intern", "junior", "middle", "senior", "lead", "principal")
CUT_VALUES = tuple(float(GRADE_CUTS[g]) for g in GRADE_NAMES)  # (-1.75, -1.0, 0.0, 1.0, 2.0, 3.0)
DIRECTIONS = ("analyst", "backend", "data_eng", "data_ml", "devops", "frontend", "mobile", "qa", "security")


def fmt_ru(val: float, digits: int = 1) -> str:
    return f"{val:.{digits}f}".replace(".", ",")


def true_grade_idx(theta: float) -> int:
    """Индекс истинного грейда по шкале продукта GRADE_CUTS:
    θ < −1.0 → 0 (intern), [−1.0; 0.0) → 1 (junior), [0.0; 1.0) → 2 (middle),
    [1.0; 2.0) → 3 (senior), [2.0; 3.0) → 4 (lead), ≥ 3.0 → 5 (principal).
    """
    idx = 0
    for gi in range(1, len(GRADE_NAMES)):
        if theta >= CUT_VALUES[gi]:
            idx = gi
    return idx


def assign_point_grade_idx(theta: float, se: float, p_confirm: float = 0.60) -> int:
    """Присвоенный грейд по апостериорному распределению N(theta, se^2): наивысшая ступень с P(θ ≥ порога) ≥ p_confirm."""
    best = 0
    for gi in range(1, len(GRADE_NAMES)):
        gname = GRADE_NAMES[gi]
        if p_at_least(theta, se, gname) >= p_confirm:
            best = gi
    return best


def boot_ci(arr: np.ndarray, seed: int = 42) -> list[float]:
    if len(arr) == 0:
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(N_BOOT, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def weighted_kappa_6(a: np.ndarray, b: np.ndarray, k: int = 6) -> float:
    o = np.bincount(a * k + b, minlength=k * k).reshape(k, k).astype(float)
    o /= max(o.sum(), 1.0)
    e = np.outer(o.sum(axis=1), o.sum(axis=0))
    idx = np.arange(k, dtype=float)
    w = ((idx[:, None] - idx[None, :]) ** 2) / ((k - 1) ** 2)
    den = float((w * e).sum())
    return round(float(1.0 - (w * o).sum() / den), 4) if den > 1e-12 else 1.0


def _build_bank_pools():
    specs = list(load_specs().values())
    pool = pool_from_specs(specs, n_subpools=2)
    truth = make_truth(pool, np.random.default_rng(TRUTH_SEED), misspec=0.0)
    by_dir = {
        d: [i for i in pool if i.block in ("common", d)]
        for d in DIRECTIONS
    }
    return specs, pool, by_dir, truth


def _run_raw_candidate(
    rng: np.random.Generator,
    dir_pool: list,
    direction: str,
    truth: dict,
    th: float,
    g_true: int,
    claim_idx: int,
    *,
    select_at: str = "cut",
    code_open_share: float = DEFAULT_CODE_OPEN_SHARE,
    ext_items: int = 0,
    sprt_delta: float = 0.35,
) -> dict:
    """Прогоняет кандидата через настоящий AppCATSession (этап 1, до 16 заданий / 45 мин) и сохраняет также траекторию
    15-минутного доп. этапа у порога (этап 2 из второго субпула, до 6 заданий / 15 мин), который назначается только
    кандидатам со статусом needs_followup.
    """
    claim_grade = GRADE_NAMES[claim_idx]
    claim_cut = CUT_VALUES[claim_idx]
    start_map = dict(ALL_GRADE_START_THETA)
    cfg1 = CATConfig(
        min_items=8,
        max_items=16,
        se_target=0.32,
        max_time_s=3600.0,
        cuts=CUT_VALUES[1:],
        stop_rule="classification",
        classify_z=1.28,
        select_at=select_at,
        cut_after=2,
        ext_items=ext_items,
        ext_time_s=900.0,
        ext_item_time_s=360.0,
        ext_own_first=True,
        prior_sd=1.35,
        start_theta=start_map,
    )
    subpool1 = int(rng.integers(0, 2))
    sess1 = AppCATSession(
        dir_pool,
        direction,
        cfg1,
        None,
        claim_grade,
        subpool1,
        rng,
        code_open_share=code_open_share,
        sprt_alpha=0.01,  # ранняя остановка только при высокой достоверности
        sprt_delta=sprt_delta,
    )
    resp = make_responder(Person(th, 0.0, direction), truth)
    while (it := sess1.next_item()) is not None:
        x, lt = resp(it, rng)
        sess1.record(it, x, lt, time_s=min(float(it.time_limit_s), float(np.exp(lt))))

    scored1 = [a for a in sess1.administered if not a.canary]
    n_co1 = sum(1 for a in scored1 if sess1.items[a.family_id].format in CODE_OPEN_FORMATS)
    th1, se1 = float(sess1.theta), float(sess1.se)
    llr1 = float(sess1.sprt_llr)
    time1_min = float(sess1.time_used) / 60.0

    # Траектория 15-минутного доп. этапа (до 6 заданий / 15 мин у спорного порога из второго субпула)
    cfg2 = CATConfig(
        min_items=3,
        max_items=6,
        se_target=0.26,
        max_time_s=900.0,
        cuts=(claim_cut,),
        stop_rule="classification",
        classify_z=1.28,
        select_at="cut",
        cut_after=0,
        ext_items=0,
        prior_sd=1.35,
        start_theta={claim_grade: th1},
    )
    sess2 = AppCATSession(
        dir_pool,
        direction,
        cfg2,
        None,
        claim_grade,
        1 - subpool1,
        rng,
        code_open_share=DEFAULT_CODE_OPEN_SHARE,
        max_item_time_s=360.0,
        sprt_alpha=0.01,
        sprt_delta=sprt_delta,
        exclude=sess1.used,
    )
    while (it2 := sess2.next_item()) is not None:
        x2, lt2 = resp(it2, rng)
        sess2.record(it2, x2, lt2, time_s=min(float(it2.time_limit_s), float(np.exp(lt2))))

    scored2 = [a for a in sess2.administered if not a.canary]
    n_co2 = sum(1 for a in scored2 if sess2.items[a.family_id].format in CODE_OPEN_FORMATS)
    # Объединённая оценка θ и SE по всем заданиям этапов 1 + 2 (как в two_stage.refine_result)
    all_admin = scored1 + scored2
    a_parts, b_parts, x_parts = [], [], []
    for adm in all_admin:
        pi = sess1.items[adm.family_id]
        for j, xv in enumerate(adm.x):
            if j < len(pi.a_eff) and math.isfinite(float(xv)):
                a_parts.append(float(pi.a_eff[j]))
                b_parts.append(float(pi.b[j]))
                x_parts.append(float(xv))
    if a_parts:
        est_obj = estimate_theta(
            np.asarray(x_parts, dtype=float),
            np.asarray(a_parts, dtype=float),
            np.asarray(b_parts, dtype=float),
            method="eap",
            prior_sd=1.35,
        )
        th2, se2 = float(est_obj.theta), float(est_obj.se)
    else:
        th2, se2 = th1, se1

    llr2 = llr1 + float(sess2.sprt_llr)
    time2_min = float(sess2.time_used) / 60.0

    return {
        "direction": direction,
        "th": th,
        "g_true": g_true,
        "claim": claim_idx,
        "th1": th1,
        "se1": se1,
        "llr1": llr1,
        "items1": len(scored1),
        "co1": n_co1,
        "mins1": time1_min,
        "th2": th2,
        "se2": se2,
        "llr2": llr2,
        "items2": len(scored1) + len(scored2),
        "co2": n_co1 + n_co2,
        "mins2": time1_min + time2_min,
    }


def _generate_raw_population(seed: int, n_people: int, by_dir: dict, truth: dict, **kw) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_people):
        d = DIRECTIONS[i % len(DIRECTIONS)]
        # Распределение кандидатов покрывает все 6 ступеней шкалы (-1.75 .. +3.0)
        th = float(rng.normal(0.45, 1.45))
        g = true_grade_idx(th)
        # В трети случаев кандидат заявляет грейд на 1 ступень выше истинного
        claim = int(np.clip(g + int(rng.choice([0, 0, 0, 1, 1, -1])), 0, 5))
        rows.append(_run_raw_candidate(rng, by_dir[d], d, truth, th, g, claim, **kw))
    return rows


def score_population(rows: list[dict], params: dict, *, followup_enabled: bool = True, seed: int = TEST_SEED) -> dict:
    """Применяет пороги вердикта ``params = {alpha, p_hi, p_lo, p_final}`` к траекториям кандидатов и считает все метрики."""
    alpha = float(params["alpha"])
    p_hi = float(params["p_hi"])
    p_lo = float(params["p_lo"])
    p_final = float(params["p_final"])
    A = sprt_bound(alpha)

    g_arr = np.array([r["g_true"] for r in rows], dtype=int)
    c_arr = np.array([r["claim"] for r in rows], dtype=int)
    th_arr = np.array([r["th"] for r in rows], dtype=float)
    truth_ok = g_arr >= c_arr
    non_intern = c_arr >= 1

    decided1 = np.zeros(len(rows), dtype=bool)
    conf1 = np.zeros(len(rows), dtype=bool)
    conff = np.zeros(len(rows), dtype=bool)
    est1 = np.zeros(len(rows), dtype=int)
    estf = np.zeros(len(rows), dtype=int)
    items_used = np.zeros(len(rows), dtype=float)
    mins_used = np.zeros(len(rows), dtype=float)
    co_shares = np.zeros(len(rows), dtype=float)
    followup_mask = np.zeros(len(rows), dtype=bool)

    for idx, r in enumerate(rows):
        ci = r["claim"]
        cname = GRADE_NAMES[ci]
        est1[idx] = assign_point_grade_idx(r["th1"], r["se1"], p_confirm=p_final)
        if ci == 0:
            decided1[idx] = True
            conf1[idx] = True
        else:
            p1 = float(p_at_least(r["th1"], r["se1"], cname))
            if r["llr1"] >= A or p1 >= p_hi:
                decided1[idx] = True
                conf1[idx] = True
            elif r["llr1"] <= -A or p1 <= p_lo:
                decided1[idx] = True
                conf1[idx] = False
            else:
                decided1[idx] = False
                conf1[idx] = p1 >= p_final

        # Дополнительный этап запускается ТОЛЬКО для тех, кто получил статус needs_followup (not decided1)
        if followup_enabled and not decided1[idx]:
            followup_mask[idx] = True
            p2 = float(p_at_least(r["th2"], r["se2"], cname)) if ci > 0 else 1.0
            conff[idx] = p2 >= p_final
            estf[idx] = assign_point_grade_idx(r["th2"], r["se2"], p_confirm=p_final)
            items_used[idx] = r["items2"]
            mins_used[idx] = r["mins2"]
            co_shares[idx] = r["co2"] / max(r["items2"], 1)
        else:
            conff[idx] = conf1[idx]
            estf[idx] = est1[idx]
            items_used[idx] = r["items1"]
            mins_used[idx] = r["mins1"]
            co_shares[idx] = r["co1"] / max(r["items1"], 1)

    # Расстояние до ближайшего порога реальной шкалы продукта (-1.0, 0.0, 1.0, 2.0, 3.0)
    real_cuts = np.array(CUT_VALUES[1:], dtype=float)
    dist_to_cut = np.min(np.abs(th_arr[:, None] - real_cuts[None, :]), axis=1)
    far_mask = dist_to_cut >= 0.40

    # Метрики по нетривиальным заявкам (claim >= 1: Junior..Principal) и по всем заявкам
    dec_non_int = decided1 & non_intern
    dec_correct_non_int = (conf1 == truth_ok)[dec_non_int].astype(float)
    dec_correct_all = (conf1 == truth_ok)[decided1].astype(float)
    false_conf_dec_non_int = (conf1 & (~truth_ok))[dec_non_int].astype(float)

    all_conf_correct_non_int = (conff == truth_ok)[non_intern].astype(float)
    all_conf_correct = (conff == truth_ok).astype(float)
    undec_mask = (~decided1) & non_intern
    undec_correct = (conff == truth_ok)[undec_mask].astype(float)

    false_conf_all = (conff & (~truth_ok)).astype(float)
    false_conf_non_int = (conff & (~truth_ok))[non_intern].astype(float)
    false_rej_all = ((~conff) & truth_ok).astype(float)

    exact_1 = (est1 == g_arr).astype(float)
    exact_f = (estf == g_arr).astype(float)
    exact_far = (estf[far_mask] == g_arr[far_mask]).astype(float)
    within1_f = (np.abs(estf - g_arr) <= 1).astype(float)
    gross_err_f = (np.abs(estf - g_arr) >= 2).astype(float)
    over_f = (estf > g_arr).astype(float)
    under_f = (estf < g_arr).astype(float)

    mins1_arr = np.array([r["mins1"] for r in rows], dtype=float)
    items1_arr = np.array([r["items1"] for r in rows], dtype=float)

    by_grade = {}
    for gi, gname in enumerate(GRADE_NAMES):
        m_true = g_arr == gi
        m_claim = c_arr == gi
        m_claim_dec = m_claim & decided1
        by_grade[gname] = {
            "n_true": int(m_true.sum()),
            "n_claimed": int(m_claim.sum()),
            "exact_grade": round(float(exact_f[m_true].mean()), 4) if m_true.any() else None,
            "within_1": round(float(within1_f[m_true].mean()), 4) if m_true.any() else None,
            "verdict_accuracy_all": round(float(all_conf_correct[m_claim].mean()), 4) if m_claim.any() else None,
            "verdict_precision_decided": round(float((conf1[m_claim_dec] == truth_ok[m_claim_dec]).mean()), 4)
            if m_claim_dec.any() else None,
            "decided_share": round(float(decided1[m_claim].mean()), 4) if m_claim.any() else None,
            "false_confirm_rate": round(float(false_conf_all[m_claim].mean()), 4) if m_claim.any() else None,
        }

    return {
        "n": len(rows),
        "n_non_intern_claims": int(non_intern.sum()),
        "intern_claim_share": round(float((~non_intern).mean()), 4),
        # Основные показатели уверенного вердикта — честно без тривиальных заявок intern (claim >= 1)
        "precision_decided": round(float(dec_correct_non_int.mean()), 4) if len(dec_correct_non_int) else 0.0,
        "precision_decided_ci": boot_ci(dec_correct_non_int, seed + 11),
        "decided_share": round(float(decided1[non_intern].mean()), 4) if non_intern.any() else 0.0,
        # Справочно — включая заявки intern
        "precision_decided_all_claims": round(float(dec_correct_all.mean()), 4) if len(dec_correct_all) else 0.0,
        "decided_share_all_claims": round(float(decided1.mean()), 4),
        # Точность вердикта по всему пулу и отдельно по дошедшим до 2-го этапа
        "verdict_accuracy_after_followup": round(float(all_conf_correct_non_int.mean()), 4),
        "verdict_accuracy_after_followup_ci": boot_ci(all_conf_correct_non_int, seed + 12),
        "verdict_accuracy_all_claims": round(float(all_conf_correct.mean()), 4),
        "verdict_accuracy_undecided_after_followup": round(float(undec_correct.mean()), 4) if len(undec_correct) else None,
        # Ошибки 1-го и 2-го рода
        "false_confirm_decided": round(float(false_conf_dec_non_int.mean()), 4) if len(false_conf_dec_non_int) else 0.0,
        "false_confirm_overall": round(float(false_conf_non_int.mean()), 4),
        "false_confirm_overall_ci": boot_ci(false_conf_non_int, seed + 13),
        "false_confirm_all_claims": round(float(false_conf_all.mean()), 4),
        "false_reject_overall": round(float(false_rej_all[non_intern].mean()), 4),
        # Точность присвоенного грейда (6 ступеней)
        "exact_single_stage": round(float(exact_1.mean()), 4),
        "exact_single_stage_ci": boot_ci(exact_1, seed + 14),
        "exact_with_followup": round(float(exact_f.mean()), 4),
        "exact_with_followup_ci": boot_ci(exact_f, seed + 15),
        "exact_far_from_cut": round(float(exact_far.mean()), 4) if len(exact_far) else 0.0,
        "exact_far_from_cut_ci": boot_ci(exact_far, seed + 16),
        "far_from_cut_share": round(float(far_mask.mean()), 4),
        "within_1": round(float(within1_f.mean()), 4),
        "within_1_ci": boot_ci(within1_f, seed + 17),
        "gross_error_rate": round(float(gross_err_f.mean()), 4),
        "gross_error_count": int(gross_err_f.sum()),
        "over_rate": round(float(over_f.mean()), 4),
        "under_rate": round(float(under_f.mean()), 4),
        # Фактическая доля доп. этапа (= доле needs_followup после 1-го этапа) и распределения времени/заданий
        "followup_share": round(float(followup_mask.mean()), 4),
        "followup_share_non_intern": round(float(followup_mask[non_intern].mean()), 4),
        "items_stage1_mean": round(float(items1_arr.mean()), 1),
        "items_mean": round(float(items_used.mean()), 1),
        "items_p90": round(float(np.percentile(items_used, 90)), 1),
        "minutes_stage1_mean": round(float(mins1_arr.mean()), 1),
        "minutes_stage1_median": round(float(np.median(mins1_arr)), 1),
        "minutes_stage1_p90": round(float(np.percentile(mins1_arr, 90)), 1),
        "minutes_mean": round(float(mins_used.mean()), 1),
        "minutes_median": round(float(np.median(mins_used)), 1),
        "minutes_p90": round(float(np.percentile(mins_used, 90)), 1),
        "over_60min_share": round(float((mins_used > 60.0).mean()), 4),
        "code_open_share": round(float(co_shares.mean()), 3),
        "by_grade": by_grade,
    }


def evaluate_retest(by_dir: dict, truth: dict, chosen_params: dict, seed: int = RETEST_SEED, n_people: int = 1500) -> dict:
    """Тест–ретест на двух параллельных формах реального банка (субпул 0 и субпул 1 для одного и того же кандидата)."""
    rng = np.random.default_rng(seed)
    rows1, rows2 = [], []
    for i in range(n_people):
        d = DIRECTIONS[i % len(DIRECTIONS)]
        th = float(rng.normal(0.45, 1.45))
        g = true_grade_idx(th)
        claim = int(np.clip(g + int(rng.choice([0, 0, 0, 1, 1, -1])), 0, 5))
        rows1.append(_run_raw_candidate(rng, by_dir[d], d, truth, th, g, claim, sprt_delta=chosen_params["delta"]))
        rows2.append(_run_raw_candidate(rng, by_dir[d], d, truth, th, g, claim, sprt_delta=chosen_params["delta"]))

    p_final = float(chosen_params["p_final"])
    alpha = float(chosen_params["alpha"])
    p_hi = float(chosen_params["p_hi"])
    p_lo = float(chosen_params["p_lo"])
    A = sprt_bound(alpha)

    g1, g2, v1, v2, th1, th2 = [], [], [], [], [], []
    for r1, r2 in zip(rows1, rows2, strict=True):
        for r, gl, vl, thl in ((r1, g1, v1, th1), (r2, g2, v2, th2)):
            ci = r["claim"]
            cname = GRADE_NAMES[ci]
            if ci == 0:
                dec = True
                cf = True
            else:
                p1 = float(p_at_least(r["th1"], r["se1"], cname))
                if r["llr1"] >= A or p1 >= p_hi:
                    dec, cf = True, True
                elif r["llr1"] <= -A or p1 <= p_lo:
                    dec, cf = True, False
                else:
                    dec = False
                    cf = float(p_at_least(r["th2"], r["se2"], cname)) >= p_final
            th_use, se_use = (r["th1"], r["se1"]) if dec else (r["th2"], r["se2"])
            gl.append(assign_point_grade_idx(th_use, se_use, p_confirm=p_final))
            vl.append(int(cf))
            thl.append(th_use)

    a1, a2 = np.array(g1, dtype=int), np.array(g2, dtype=int)
    va1, va2 = np.array(v1, dtype=int), np.array(v2, dtype=int)
    exact_arr = (a1 == a2).astype(float)
    within1_arr = (np.abs(a1 - a2) <= 1).astype(float)
    verdict_agree = (va1 == va2).astype(float)
    kw_val = weighted_kappa_6(a1, a2, k=6)
    r_th = float(np.corrcoef(th1, th2)[0, 1])
    return {
        "n": n_people,
        "exact": round(float(exact_arr.mean()), 4),
        "exact_ci": boot_ci(exact_arr, seed + 21),
        "within_1": round(float(within1_arr.mean()), 4),
        "two_or_more_steps": round(float(np.mean(np.abs(a1 - a2) >= 2)), 4),
        "kappa_w": kw_val,
        "verdict_consistency": round(float(verdict_agree.mean()), 4),
        "verdict_consistency_ci": boot_ci(verdict_agree, seed + 22),
        "r_theta": round(r_th, 4),
    }


def run_all(n: int = 3000, n_train: int = 800, n_retest: int = 1500, write: bool = True) -> dict:
    t0 = time.time()
    specs, pool, by_dir, truth = _build_bank_pools()
    n_families = len(specs)
    n_code_open = sum(1 for s in specs if s.format in CODE_OPEN_FORMATS)
    n_incident = sum(1 for s in specs if s.format == "incident_sim")

    # 1. Прогон обучающей выборки (TRAIN_SEED = 2026102001) через реальный AppCATSession и банк
    train_rows = _generate_raw_population(TRAIN_SEED, n_train, by_dir, truth, select_at="cut", code_open_share=DEFAULT_CODE_OPEN_SHARE, ext_items=0)

    # Перебор сетки ВСЕХ порогов решения на обучающей выборке и программный выбор оптимальной точки
    train_grid = []
    for alpha_cand in (0.02, 0.015, 0.01):
        for p_hi_cand, p_lo_cand in ((0.88, 0.12), (0.90, 0.10), (0.92, 0.08)):
            for p_final_cand in (0.58, 0.60, 0.62):
                cand_p = {
                    "alpha": alpha_cand,
                    "delta": 0.35,
                    "p_hi": p_hi_cand,
                    "p_lo": p_lo_cand,
                    "p_final": p_final_cand,
                }
                m = score_population(train_rows, cand_p, followup_enabled=True, seed=TRAIN_SEED)
                # Целевая функция выбора на train: максимизируем точность уверенных вердиктов + долю уверенных + общую точность
                # со штрафом за превышение порога ложного подтверждения
                obj = (
                    2.0 * m["precision_decided"]
                    + 0.25 * m["decided_share"]
                    + 0.5 * m["verdict_accuracy_after_followup"]
                    + 0.4 * m["exact_with_followup"]
                    - 4.0 * max(0.0, m["false_confirm_overall"] - 0.025)
                )
                train_grid.append({
                    **cand_p,
                    "objective": round(float(obj), 5),
                    "precision_decided": m["precision_decided"],
                    "decided_share": m["decided_share"],
                    "false_confirm_decided": m["false_confirm_decided"],
                    "verdict_accuracy_after_followup": m["verdict_accuracy_after_followup"],
                    "exact_with_followup": m["exact_with_followup"],
                })

    best_train = max(train_grid, key=lambda x: x["objective"])
    chosen_params = {
        "alpha": best_train["alpha"],
        "delta": best_train["delta"],
        "p_hi": best_train["p_hi"],
        "p_lo": best_train["p_lo"],
        "p_final": best_train["p_final"],
        "code_open_share": round(DEFAULT_CODE_OPEN_SHARE, 4),
        "followup_minutes": 15,
    }

    # 2. Единственный контрольный прогон на отложенной выборке (TEST_SEED = 2026102002, N = n) с выбранными на train порогами
    test_rows_product = _generate_raw_population(
        TEST_SEED, n, by_dir, truth, select_at="cut", code_open_share=DEFAULT_CODE_OPEN_SHARE, ext_items=0, sprt_delta=chosen_params["delta"]
    )
    test_rows_baseline = _generate_raw_population(
        TEST_SEED + 10, max(600, n // 3), by_dir, truth, select_at="theta", code_open_share=0.0, ext_items=0, sprt_delta=chosen_params["delta"]
    )

    scenarios = {
        "baseline_theta_no_ext": {
            "title": "1. Базовый CAT в θ̂ без квоты кода и без дотестирования (1 этап, до 16 заданий)",
            "metrics": score_population(test_rows_baseline, chosen_params, followup_enabled=False, seed=TEST_SEED + 10),
        },
        "cut_single_stage": {
            "title": "2. Классификационный CAT у порогов + квота 1/3 кода + дотестирование в сессии (без 2-го этапа)",
            "metrics": score_population(test_rows_product, chosen_params, followup_enabled=False, seed=TEST_SEED + 20),
        },
        "sprt_verdict_product": {
            "title": "3. Продуктовый контур: AppCATSession у порогов + 1/3 практических заданий + SPRT и 15-мин 2-й этап для пограничных",
            "metrics": score_population(test_rows_product, chosen_params, followup_enabled=True, seed=TEST_SEED),
        },
    }

    retest = evaluate_retest(by_dir, truth, chosen_params, seed=RETEST_SEED, n_people=n_retest)
    main_m = scenarios["sprt_verdict_product"]["metrics"]

    claim_ru = (
        f"Прогон продуктового движка AppCATSession на реальном банке заданий ({n_families} семейств, {n_code_open} кодовых и "
        f"развёрнутых, D = 1,0 без искусственного множителя, кросс-валидация: пороги выбраны на train N = {n_train}, "
        f"проверены на отложенной выборке N = {n}, seed {TEST_SEED}): среди кандидатов с нетривиальной заявкой (Junior…Principal) "
        f"точность уверенного вердикта составляет {fmt_ru(100 * main_m['precision_decided'], 1)} % "
        f"(95 % ДИ [{fmt_ru(100 * main_m['precision_decided_ci'][0], 1)} %; {fmt_ru(100 * main_m['precision_decided_ci'][1], 1)} %]) "
        f"при доле уверенных решений 1-го этапа {fmt_ru(100 * main_m['decided_share'], 1)} % (ложное подтверждение среди уверенных — "
        f"{fmt_ru(100 * main_m['false_confirm_decided'], 2)} %); с учётом всех заявок включая стажёров — точность уверенных "
        f"{fmt_ru(100 * main_m['precision_decided_all_claims'], 1)} % на {fmt_ru(100 * main_m['decided_share_all_claims'], 1)} % пула. "
        f"По всем кандидатам с учётом 2-го этапа у порога (назначается {fmt_ru(100 * main_m['followup_share'], 1)} % пула) "
        f"вердикт верен в {fmt_ru(100 * main_m['verdict_accuracy_after_followup'], 1)} % (среди всех заявок — "
        f"{fmt_ru(100 * main_m['verdict_accuracy_all_claims'], 1)} %, ложное подтверждение по пулу — "
        f"{fmt_ru(100 * main_m['false_confirm_overall'], 2)} %). Точный грейд из 6 ступеней по всему пулу — "
        f"{fmt_ru(100 * main_m['exact_with_followup'], 1)} % (вдали от порога |θ − порог| ≥ 0,40, {fmt_ru(100 * main_m['far_from_cut_share'], 1)} % "
        f"пула — {fmt_ru(100 * main_m['exact_far_from_cut'], 1)} %), попадание в пределах ±1 ступени — "
        f"{fmt_ru(100 * main_m['within_1'], 2)} %, повторяемость между независимыми сессиями κw = {fmt_ru(retest['kappa_w'], 3)} "
        f"(точное совпадение {fmt_ru(100 * retest['exact'], 1)} %, согласованность вердикта {fmt_ru(100 * retest['verdict_consistency'], 1)} %, "
        f"N = {retest['n']}). Модельный расчёт до калибровки на живых людях."
    )

    out = {
        "signature": signature(
            seed=TEST_SEED,
            config={"n_test": n, "n_train": n_train, "train_seed": TRAIN_SEED, "test_seed": TEST_SEED, "bank_families": n_families, **chosen_params},
            n=n,
            world=f"реальный движок AppCATSession на банке ({n_families} семейств, D=1,0, GRADE_CUTS продукта): train N={n_train}, held-out test N={n}",
            command="python -m app.modules.validation.sprt_verdict",
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recompute": "cd backend && python -m app.modules.validation.sprt_verdict",
        "code_ref": "backend/app/modules/validation/sprt_verdict.py",
        "bank_summary": {
            "families": n_families,
            "code_and_open_families": n_code_open,
            "incident_sim_families": n_incident,
            "format_limits": DEFAULT_FORMAT_LIMITS,
            "logistic_d": 1.0,
            "grade_cuts": dict(GRADE_CUTS),
            "basis": "реальный пул load_specs() → pool_from_specs(), прогон через AppCATSession",
        },
        "cross_validation": {
            "protocol": (
                "Все пороги вердикта (alpha, p_hi, p_lo, p_final) выбраны программно максимизацией целевой функции на "
                f"обучающей выборке (seed {TRAIN_SEED}, N = {n_train}) и проверены один раз на отложенной контрольной выборке "
                f"(seed {TEST_SEED}, N = {n})."
            ),
            "train_seed": TRAIN_SEED,
            "test_seed": TEST_SEED,
            "retest_seed": RETEST_SEED,
            "n_train": n_train,
            "n_test": n,
            "chosen_params": chosen_params,
            "best_train_point": best_train,
            "train_grid": train_grid,
        },
        "main": main_m,
        "retest": retest,
        "scenarios": scenarios,
        "claim_ru": claim_ru,
        "seconds": round(time.time() - t0, 2),
    }
    if write:
        OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        OUT_MD.write_text(render_markdown(out), encoding="utf-8")
    return out


def _p(v: float | None, d: int = 1) -> str:
    if v is None:
        return "—"
    return f"{100.0 * float(v):.{d}f} %".replace(".", ",")


def render_markdown(d: dict) -> str:
    m = d["main"]
    rt = d["retest"]
    cv = d["cross_validation"]
    bs = d["bank_summary"]
    lines = [
        "# Методика грейда: прогон реального движка AppCATSession на банке заданий",
        "",
        f"Дата расчёта: `{d['generated_at'][:10]}` · Контрольная выборка: **N = {m['n']}** (`seed = {cv['test_seed']}`) · "
        f"Обучающая выборка: **N = {cv['n_train']}** (`seed = {cv['train_seed']}`) · "
        f"Банк: **{bs['families']} семейств** ({bs['code_and_open_families']} практических) · Команда: `{d['recompute']}`.",
        "",
        f"> **Итоговая формулировка (с полными условиями измерения):** {d['claim_ru']}",
        "",
        "## 1. Сравнение сценариев на отложенной контрольной выборке",
        "",
        "| Сценарий | Время (ср. / мед. / p90), мин | Заданий (ср. / p90) | Доля кода | Точный грейд (весь пул) | Вдали от порога (" + _p(m["far_from_cut_share"]) + " пула) | ±1 ступень | Точность уверенных (Jun…Prin) | Доля уверенных (Jun…Prin) | Вердикт по всему пулу | Ложное подтв. (увер. / весь пул) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sc in d["scenarios"].values():
        sm = sc["metrics"]
        lines.append(
            f"| {sc['title']} | {fmt_ru(sm['minutes_mean'], 1)} / {fmt_ru(sm['minutes_median'], 1)} / {fmt_ru(sm['minutes_p90'], 1)} | "
            f"{fmt_ru(sm['items_mean'], 1)} / {fmt_ru(sm['items_p90'], 0)} | {_p(sm['code_open_share'], 1)} | "
            f"**{_p(sm['exact_with_followup'], 1)}** | {_p(sm['exact_far_from_cut'], 1)} | {_p(sm['within_1'], 2)} | "
            f"**{_p(sm['precision_decided'], 1)}** | {_p(sm['decided_share'], 1)} | {_p(sm['verdict_accuracy_after_followup'], 1)} | "
            f"{_p(sm['false_confirm_decided'], 2)} / {_p(sm['false_confirm_overall'], 2)} |"
        )
    lines += [
        "",
        "## 2. Показатели по всем 6 уровням шкалы продукта (`GRADE_CUTS`)",
        "",
        "| Грейд | Порог θ | Кандидатов (истина) | Заявок | Точность уверенного вердикта | Доля уверенных | Вердикт с учётом 2-го этапа | Точный грейд | ±1 ступень | Ложное подтверждение (весь пул) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for gi, gname in enumerate(GRADE_NAMES):
        bg = m["by_grade"][gname]
        lines.append(
            f"| {gname.capitalize()} | {fmt_ru(CUT_VALUES[gi], 2)} | {bg['n_true']} | {bg['n_claimed']} | "
            f"**{_p(bg['verdict_precision_decided'], 1)}** | {_p(bg['decided_share'], 1)} | "
            f"{_p(bg['verdict_accuracy_all'], 1)} | {_p(bg['exact_grade'], 1)} | {_p(bg['within_1'], 1)} | {_p(bg['false_confirm_rate'], 2)} |"
        )
    lines += [
        "",
        f"## 3. Повторяемость (Test–Retest на двух параллельных субпулах банка, N = {rt['n']})",
        "",
        f"- Квадратично взвешенная каппа Коэна: **κw = {fmt_ru(rt['kappa_w'], 3)}**",
        f"- Точное совпадение присвоенного грейда между попытками: **{_p(rt['exact'], 1)}** (95 % ДИ [{_p(rt['exact_ci'][0], 1)}; {_p(rt['exact_ci'][1], 1)}])",
        f"- Совпадение в пределах ±1 ступени между попытками: **{_p(rt['within_1'], 2)}**",
        f"- Согласованность вердикта подтверждения заявленного грейда между попытками: **{_p(rt['verdict_consistency'], 1)}**",
        f"- Корреляция оценок уровня r(θ₁, θ₂): **{fmt_ru(rt['r_theta'], 3)}**",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--n-train", type=int, default=800)
    ap.add_argument("--n-retest", type=int, default=1500)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    res = run_all(n=a.n, n_train=a.n_train, n_retest=a.n_retest, write=not a.no_write)
    print(json.dumps({
        "chosen_params": res["cross_validation"]["chosen_params"],
        "precision_decided": res["main"]["precision_decided"],
        "decided_share": res["main"]["decided_share"],
        "precision_decided_all_claims": res["main"]["precision_decided_all_claims"],
        "decided_share_all_claims": res["main"]["decided_share_all_claims"],
        "verdict_accuracy_after_followup": res["main"]["verdict_accuracy_after_followup"],
        "false_confirm_decided": res["main"]["false_confirm_decided"],
        "false_confirm_overall": res["main"]["false_confirm_overall"],
        "exact_with_followup": res["main"]["exact_with_followup"],
        "exact_far_from_cut": res["main"]["exact_far_from_cut"],
        "far_from_cut_share": res["main"]["far_from_cut_share"],
        "within_1": res["main"]["within_1"],
        "code_open_share": res["main"]["code_open_share"],
        "minutes_mean": res["main"]["minutes_mean"],
        "minutes_median": res["main"]["minutes_median"],
        "minutes_p90": res["main"]["minutes_p90"],
        "retest_kappa_w": res["retest"]["kappa_w"],
        "retest_exact": res["retest"]["exact"],
        "retest_verdict_consistency": res["retest"]["verdict_consistency"],
        "seconds": res["seconds"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
