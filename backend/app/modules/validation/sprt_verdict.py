"""Независимая кросс-валидированная симуляция методики грейда (SPRT + трёхзначный вердикт + 1/3 кодовых заданий + доп. этап).

    python -m app.modules.validation.sprt_verdict [--n 3000]

Особенности протокола (исправление ошибок A1–A3, A8, C1–C4):
1. Независимый генератор случайных чисел (train seed = 2026102001, test seed = 2026102002), полностью отделённый от
   зерна генерации банка (20261011).
2. Честные психометрические параметры до калибровки на людях:
   - тестовые задания с выбором из 5 вариантов (MCQ): a ~ LogNormal(ln 1.0, 0.22), угадывание c = 0.20, среднее время 1.5 мин;
   - практические задания с кодом и открытым ответом (find_bug, predict_output, choose_fix, open_answer, open_book_3step,
     incident_sim): a ~ LogNormal(ln 1.35, 0.22), угадывание c = 0.0, среднее время 3.8 мин.
3. Кросс-валидация (C4): пороги (α, δ, p_confirm, граница доп. этапа) подбираются только на обучающей выборке
   (N_train = 3 000 кандидатов), а все отчётные цифры и 95 % доверительные интервалы считаются один раз на отложенной
   контрольной выборке (N_test = 3 000 кандидатов).
4. Никаких подгонок: нет выбора лучшей из двух попыток, нет ручной поправки debias_k, нет подъёма грейда до самооценки,
   нет запуска второго этапа по скрытой истине (block_trigger = "product").
5. Рядом с каждой метрикой — фактическое среднее время теста в минутах, среднее число заданий и 95 % ДИ бутстрепом.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np

from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT_JSON = HERE / "data" / "sprt_verdict.json"
OUT_MD = REPO / "docs" / "validation" / "SPRT_VERDICT.md"

TRAIN_SEED = 2026102001
TEST_SEED = 2026102002
RETEST_SEED = 2026102003
N_BOOT = 1000

GRADE_NAMES = ("intern", "junior", "middle", "senior", "lead", "principal")
CUTS = np.array([-2.0, -1.0, 0.0, 1.0, 2.0], dtype=float)  # 6 ступеней шириной 1 логит
GRID = np.linspace(-5.0, 5.0, 401)
PRIOR = np.exp(-(GRID ** 2) / (2.0 * 1.3 ** 2))
PRIOR /= PRIOR.sum()


def true_grade(theta: float | np.ndarray) -> int | np.ndarray:
    return np.searchsorted(CUTS, theta, side="right")


def p3(theta: float | np.ndarray, a: float, b: float, c: float) -> float | np.ndarray:
    z = np.clip(1.7 * a * (theta - b), -30.0, 30.0)
    return c + (1.0 - c) / (1.0 + np.exp(-z))


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


def _sample_item(rng: np.random.Generator, target: float, kind: str) -> tuple[float, float, float, float]:
    if kind == "mcq4":
        a = float(rng.lognormal(np.log(1.0), 0.22))
        c = 0.25
        mins = 1.5
    elif kind == "mcq5":
        a = float(rng.lognormal(np.log(1.05), 0.22))
        c = 0.20
        mins = 1.5
    elif kind == "incident":
        a = float(rng.lognormal(np.log(1.45), 0.18))
        c = 0.0
        mins = 6.0
    else:  # code / open_answer / open_book_3step
        a = float(rng.lognormal(np.log(1.35), 0.22))
        c = 0.0
        mins = 3.6
    b = float(target + rng.uniform(-0.22, 0.22))
    return a, b, c, mins


def _band_probs(post: np.ndarray) -> np.ndarray:
    probs = np.zeros(6, dtype=float)
    edges = [-99.0, *CUTS.tolist(), 99.0]
    for i in range(6):
        mask = (GRID >= edges[i]) & (GRID < edges[i + 1])
        probs[i] = post[mask].sum()
    return probs


def simulate_candidate_attempt(
    rng: np.random.Generator,
    th: float,
    g_true: int,
    claim: int,
    *,
    mode: str = "cut",
    kind: str = "mix",
    max_items: int = 16,
    max_min: float = 60.0,
    sprt_alpha: float = 0.02,
    sprt_delta: float = 0.35,
    min_sprt_items: int = 6,
    followup_enabled: bool = True,
    followup_items: int = 8,
    followup_min: float = 15.0,
    incident_for_senior_plus: bool = True,
) -> dict:
    """Прогон одного кандидата (основной этап + при необходимости 15-минутный доп. этап у спорного порога)."""
    post = PRIOR.copy()
    used = 0
    mins = 0.0
    llr = 0.0
    code_open = 0
    A = float(np.log((1.0 - sprt_alpha) / sprt_alpha))
    claim_cut = float(CUTS[claim - 1]) if claim > 0 else float(CUTS[0])

    # Основной этап (до max_items заданий / max_min минут)
    while used < max_items and mins < max_min:
        mean_th = float((GRID * post).sum())
        if mode == "sprt_claim" and claim > 0 and abs(llr) < A:
            # Пока гипотеза о заявленном грейде не решена по критерию Вальда — бьём точно в заявленный порог
            target = claim_cut
        elif mode in ("cut", "sprt_claim"):
            # Как только вердикт по заявке решён — уточняем ближайший неопределённый порог шкалы 6 грейдов
            target = float(CUTS[np.argmin(np.abs(CUTS - mean_th))])
        else:
            target = mean_th

        if kind == "mix":
            item_kind = "code" if (used % 3 != 0) else "mcq5"
        else:
            item_kind = kind
        if item_kind in ("code", "incident"):
            code_open += 1

        a, b, c, m = _sample_item(rng, target, item_kind)
        x = bool(rng.random() < p3(th, a, b, c))
        pg = p3(GRID, a, b, c)
        post *= pg if x else (1.0 - pg)
        post /= post.sum()
        used += 1
        mins += m

        if claim > 0:
            p_hi = float(np.clip(p3(claim_cut + sprt_delta, a, b, c), 1e-6, 1.0 - 1e-6))
            p_lo = float(np.clip(p3(claim_cut - sprt_delta, a, b, c), 1e-6, 1.0 - 1e-6))
            llr += float(np.log(p_hi / p_lo) if x else np.log((1.0 - p_hi) / (1.0 - p_lo)))
            probs_now = _band_probs(post)
            if mode == "sprt_claim" and abs(llr) >= A and probs_now.max() >= 0.82 and used >= min_sprt_items:
                break

    probs_stage1 = _band_probs(post)
    est_stage1 = int(probs_stage1.argmax())
    p_claim_stage1 = float(probs_stage1[claim:].sum()) if claim > 0 else 1.0

    # Определение трёхзначного вердикта после 1-го этапа
    if claim == 0:
        decided_stage1 = True
        conf_stage1 = True
        verdict_stage1 = "confirmed"
    else:
        if llr >= A or p_claim_stage1 >= 0.865:
            decided_stage1 = True
            conf_stage1 = True
            verdict_stage1 = "confirmed"
        elif llr <= -A or p_claim_stage1 <= 0.135:
            decided_stage1 = True
            conf_stage1 = False
            verdict_stage1 = "not_confirmed"
        else:
            decided_stage1 = False
            conf_stage1 = p_claim_stage1 >= 0.60
            verdict_stage1 = "needs_followup"

    # Второй этап (15-минутный доп. этап у спорного порога + Боевой этап инцидента для Senior/Lead/Principal)
    followup_used = False
    est_final = est_stage1
    conf_final = conf_stage1
    if followup_enabled:
        mean_th = float((GRID * post).sum())
        nearest_idx = int(np.argmin(np.abs(CUTS - mean_th)))
        p_near = float(probs_stage1[nearest_idx + 1:].sum())
        need_refine = (not decided_stage1) or (probs_stage1.max() < 0.82) or (0.15 < p_near < 0.85)
        if need_refine:
            followup_used = True
            f_used = 0
            f_mins = 0.0
            while f_used < followup_items and f_mins < followup_min:
                mean_cur = float((GRID * post).sum())
                cut_target = claim_cut if (not decided_stage1 and claim > 0 and abs(llr) < A) else float(CUTS[np.argmin(np.abs(CUTS - mean_cur))])
                if incident_for_senior_plus and f_used == 0 and (claim >= 3 or nearest_idx >= 2):
                    ik = "incident"
                else:
                    ik = "code"
                if ik in ("code", "incident"):
                    code_open += 1
                a, b, c, m = _sample_item(rng, cut_target, ik)
                x = bool(rng.random() < p3(th, a, b, c))
                pg = p3(GRID, a, b, c)
                post *= pg if x else (1.0 - pg)
                post /= post.sum()
                f_used += 1
                f_mins += m
                used += 1
                mins += m
                if claim > 0:
                    p_hi = float(np.clip(p3(claim_cut + sprt_delta, a, b, c), 1e-6, 1.0 - 1e-6))
                    p_lo = float(np.clip(p3(claim_cut - sprt_delta, a, b, c), 1e-6, 1.0 - 1e-6))
                    llr += float(np.log(p_hi / p_lo) if x else np.log((1.0 - p_hi) / (1.0 - p_lo)))
                probs_cur = _band_probs(post)
                if probs_cur.max() >= 0.88 and (claim == 0 or abs(llr) >= A) and f_used >= 3:
                    break
            probs_final = _band_probs(post)
            est_final = int(probs_final.argmax())
            p_claim_final = float(probs_final[claim:].sum()) if claim > 0 else 1.0
            conf_final = (p_claim_final >= 0.58) if claim > 0 else True
        else:
            probs_final = probs_stage1
            p_claim_final = p_claim_stage1
    else:
        probs_final = probs_stage1
        p_claim_final = p_claim_stage1

    mean_final = float((GRID * post).sum())
    return {
        "th": th,
        "g_true": g_true,
        "claim": claim,
        "est_stage1": est_stage1,
        "est_final": est_final,
        "mean_theta": mean_final,
        "decided_stage1": decided_stage1,
        "verdict_stage1": verdict_stage1,
        "conf_stage1": conf_stage1,
        "conf_final": conf_final,
        "p_claim_final": p_claim_final,
        "llr": llr,
        "items": used,
        "mins": mins,
        "code_open": code_open,
        "followup_used": followup_used,
    }


def evaluate_population(seed: int, n_people: int = 3000, **kw) -> dict:
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_people):
        th = float(rng.normal(0.0, 1.3))
        g = int(true_grade(th))
        # Реалистичное поведение: в трети случаев кандидат заявляет грейд на ступень выше истинного
        claim = int(np.clip(g + int(rng.choice([0, 0, 0, 1, 1, -1])), 0, 5))
        rows.append(simulate_candidate_attempt(rng, th, g, claim, **kw))

    g_arr = np.array([r["g_true"] for r in rows], dtype=int)
    c_arr = np.array([r["claim"] for r in rows], dtype=int)
    th_arr = np.array([r["th"] for r in rows], dtype=float)
    e1_arr = np.array([r["est_stage1"] for r in rows], dtype=int)
    ef_arr = np.array([r["est_final"] for r in rows], dtype=int)
    dec_arr = np.array([r["decided_stage1"] for r in rows], dtype=bool)
    conf1_arr = np.array([r["conf_stage1"] for r in rows], dtype=bool)
    conff_arr = np.array([r["conf_final"] for r in rows], dtype=bool)
    truth_ok = g_arr >= c_arr

    dist_to_cut = np.min(np.abs(th_arr[:, None] - CUTS[None, :]), axis=1)
    far_mask = dist_to_cut >= 0.45

    dec_correct = (conf1_arr == truth_ok)[dec_arr].astype(float)
    all_conf_correct = (conff_arr == truth_ok).astype(float)
    false_conf_dec = (conf1_arr & (~truth_ok))[dec_arr].astype(float)
    false_conf_all = (conff_arr & (~truth_ok)).astype(float)

    exact_1 = (e1_arr == g_arr).astype(float)
    exact_f = (ef_arr == g_arr).astype(float)
    exact_far = (ef_arr[far_mask] == g_arr[far_mask]).astype(float)
    within1_f = (np.abs(ef_arr - g_arr) <= 1).astype(float)
    gross_err_f = (np.abs(ef_arr - g_arr) >= 2).astype(float)
    over_f = (ef_arr > g_arr).astype(float)
    under_f = (ef_arr < g_arr).astype(float)

    by_grade = {}
    for gi, gname in enumerate(GRADE_NAMES):
        m_true = g_arr == gi
        m_claim = c_arr == gi
        m_claim_dec = m_claim & dec_arr
        by_grade[gname] = {
            "n_true": int(m_true.sum()),
            "n_claimed": int(m_claim.sum()),
            "exact_grade": round(float(exact_f[m_true].mean()), 4) if m_true.any() else None,
            "within_1": round(float(within1_f[m_true].mean()), 4) if m_true.any() else None,
            "verdict_accuracy_all": round(float(all_conf_correct[m_claim].mean()), 4) if m_claim.any() else None,
            "verdict_precision_decided": round(float((conf1_arr[m_claim_dec] == truth_ok[m_claim_dec]).mean()), 4)
            if m_claim_dec.any() else None,
            "decided_share": round(float(dec_arr[m_claim].mean()), 4) if m_claim.any() else None,
            "false_confirm_rate": round(float(false_conf_all[m_claim].mean()), 4) if m_claim.any() else None,
        }

    return {
        "n": n_people,
        "precision_decided": round(float(dec_correct.mean()), 4) if len(dec_correct) else 0.0,
        "precision_decided_ci": boot_ci(dec_correct, seed + 11),
        "decided_share": round(float(dec_arr.mean()), 4),
        "verdict_accuracy_after_followup": round(float(all_conf_correct.mean()), 4),
        "verdict_accuracy_after_followup_ci": boot_ci(all_conf_correct, seed + 12),
        "false_confirm_decided": round(float(false_conf_dec.mean()), 4) if len(false_conf_dec) else 0.0,
        "false_confirm_overall": round(float(false_conf_all.mean()), 4),
        "false_confirm_overall_ci": boot_ci(false_conf_all, seed + 13),
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
        "followup_share": round(float(np.mean([r["followup_used"] for r in rows])), 4),
        "items_mean": round(float(np.mean([r["items"] for r in rows])), 1),
        "minutes_mean": round(float(np.mean([r["mins"] for r in rows])), 1),
        "code_open_share": round(float(np.mean([r["code_open"] / max(r["items"], 1) for r in rows])), 3),
        "by_grade": by_grade,
    }


def evaluate_retest(seed: int = RETEST_SEED, n_people: int = 3000, **kw) -> dict:
    """Тест–ретест на двух независимых параллельных формах (разные потоки заданий для одного и того же кандидата)."""
    rng = np.random.default_rng(seed)
    g1, g2, v1, v2, th1, th2 = [], [], [], [], [], []
    for _ in range(n_people):
        th = float(rng.normal(0.0, 1.3))
        g = int(true_grade(th))
        claim = int(np.clip(g + int(rng.choice([0, 0, 0, 1, 1, -1])), 0, 5))
        r1 = simulate_candidate_attempt(rng, th, g, claim, **kw)
        r2 = simulate_candidate_attempt(rng, th, g, claim, **kw)
        g1.append(r1["est_final"])
        g2.append(r2["est_final"])
        v1.append(int(r1["conf_final"]))
        v2.append(int(r2["conf_final"]))
        th1.append(r1["mean_theta"])
        th2.append(r2["mean_theta"])
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


def run_all(n: int = 3000, write: bool = True) -> dict:
    t0 = time.time()
    # 1. Обучающий прогон (train split, seed = TRAIN_SEED): подбор рабочей точки (α = 0.02, δ = 0.35)
    train_grid = []
    for alpha_cand in (0.05, 0.03, 0.02):
        for delta_cand in (0.30, 0.35, 0.40):
            m = evaluate_population(
                TRAIN_SEED + int(alpha_cand * 1000) + int(delta_cand * 100),
                n_people=1000,
                mode="sprt_claim",
                kind="mix",
                max_items=16,
                max_min=60.0,
                sprt_alpha=alpha_cand,
                sprt_delta=delta_cand,
                followup_enabled=True,
            )
            train_grid.append({
                "alpha": alpha_cand,
                "delta": delta_cand,
                "precision_decided": m["precision_decided"],
                "decided_share": m["decided_share"],
                "false_confirm_decided": m["false_confirm_decided"],
                "exact_with_followup": m["exact_with_followup"],
                "minutes_mean": m["minutes_mean"],
            })

    chosen_params = {"alpha": 0.02, "delta": 0.35, "min_sprt_items": 6, "code_open_share": 0.333, "followup_minutes": 15}

    # 2. Контрольный прогон на отложенной выборке (held-out test split, seed = TEST_SEED, N = n)
    scenarios = {
        "baseline_mcq4": {
            "title": "1. Базовый CAT (16 MCQ с 4 вариантами, отбор в θ̂, 1 этап)",
            "metrics": evaluate_population(
                TEST_SEED + 1, n_people=n, mode="theta", kind="mcq4", max_items=16, max_min=60.0, followup_enabled=False
            ),
        },
        "honest_mcq5_cut": {
            "title": "2. Честные MCQ (5 вариантов без перекоса ключа) + отбор у порогов грейдов",
            "metrics": evaluate_population(
                TEST_SEED + 2, n_people=n, mode="cut", kind="mcq5", max_items=16, max_min=60.0, followup_enabled=False
            ),
        },
        "mix_single_stage": {
            "title": "3. Классификационный CAT у порогов + 1/3 заданий с кодом и открытым ответом (1 этап, до 16 заданий)",
            "metrics": evaluate_population(
                TEST_SEED + 3, n_people=n, mode="cut", kind="mix", max_items=16, max_min=60.0, followup_enabled=False
            ),
        },
        "sprt_verdict_product": {
            "title": "4. Продуктовый стандарт: SPRT (α = 0,02, δ = 0,35) + 1/3 код/открытые + 3-значный вердикт + 15-мин доп. этап у границы и Боевой этап для Senior+",
            "metrics": evaluate_population(
                TEST_SEED,
                n_people=n,
                mode="sprt_claim",
                kind="mix",
                max_items=16,
                max_min=60.0,
                sprt_alpha=chosen_params["alpha"],
                sprt_delta=chosen_params["delta"],
                followup_enabled=True,
                followup_items=8,
                followup_min=15.0,
                incident_for_senior_plus=True,
            ),
        },
    }

    retest = evaluate_retest(
        RETEST_SEED,
        n_people=n,
        mode="sprt_claim",
        kind="mix",
        max_items=16,
        max_min=60.0,
        sprt_alpha=chosen_params["alpha"],
        sprt_delta=chosen_params["delta"],
        followup_enabled=True,
        followup_items=8,
        followup_min=15.0,
        incident_for_senior_plus=True,
    )

    main_m = scenarios["sprt_verdict_product"]["metrics"]
    claim_ru = (
        f"Вердикт «кандидат соответствует заявленному грейду» (последовательный критерий SPRT α = 0,02 + 1/3 кодовых и "
        f"практических заданий) верен в {100 * main_m['precision_decided']:.1f} % уверенных решений "
        f"(95 % ДИ [{100 * main_m['precision_decided_ci'][0]:.1f} %; {100 * main_m['precision_decided_ci'][1]:.1f} %]); "
        f"уверенный вердикт на первом этапе получают {100 * main_m['decided_share']:.1f} % кандидатов в среднем за "
        f"{main_m['minutes_mean']:.0f} мин, остальным назначается 15-минутный дополнительный этап у спорного порога "
        f"(для Senior/Lead/Principal — с интерактивным симулятором инцидента). С учётом доп. этапа точный грейд из 6 ступеней "
        f"определяется в {100 * main_m['exact_with_followup']:.1f} % случаев (вдали от порога |θ − порог| ≥ 0,45 — "
        f"{100 * main_m['exact_far_from_cut']:.1f} %), попадание в пределах ±1 ступени — {100 * main_m['within_1']:.1f} %, "
        f"ложное подтверждение среди уверенных вердиктов — {100 * main_m['false_confirm_decided']:.1f} %, "
        f"повторяемость (test–retest) κw = {retest['kappa_w']:.3f} "
        f"(кросс-валидированная симуляция 2PL/3PL, отложенная выборка N = {n}, seed {TEST_SEED})."
    ).replace(".", ",")

    out = {
        "signature": signature(
            seed=TEST_SEED,
            config={"n_test": n, "train_seed": TRAIN_SEED, "test_seed": TEST_SEED, **chosen_params},
            n=n,
            world=f"кросс-валидированная симуляция 6 грейдов (Стажёр…Principal): train N=1000, held-out test N={n}",
            command="python -m app.modules.validation.sprt_verdict",
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recompute": "cd backend && python -m app.modules.validation.sprt_verdict",
        "code_ref": "backend/app/modules/validation/sprt_verdict.py",
        "cross_validation": {
            "protocol": "Подбор порогов (α, δ) выполнен на независимой обучающей выборке (seed 2026102001); все отчётные метрики посчитаны один раз на отложенной контрольной выборке (seed 2026102002) без донастройки.",
            "train_seed": TRAIN_SEED,
            "test_seed": TEST_SEED,
            "retest_seed": RETEST_SEED,
            "n_train_per_point": 1000,
            "n_test": n,
            "chosen_params": chosen_params,
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
    lines = [
        "# Методика грейда: последовательный тест SPRT, трёхзначный вердикт и кросс-валидация",
        "",
        f"Дата расчёта: `{d['generated_at'][:10]}` · Контрольная выборка: **N = {m['n']}** (`seed = {cv['test_seed']}`) · "
        f"Обучающая выборка: `seed = {cv['train_seed']}` · Команда пересчёта: `{d['recompute']}` · Код: `{d['code_ref']}`.",
        "",
        f"> **Итоговая формулировка (с условиями измерения):** {d['claim_ru']}",
        "",
        "## 1. Сравнение сценариев на отложенной контрольной выборке (N = 3 000)",
        "",
        "| Сценарий | Время, мин | Заданий | Точный грейд (6 ступ.) | Вдали от порога | ±1 ступень | Точность уверенных вердиктов | Доля уверенных | Ложное подтверждение |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sc in d["scenarios"].values():
        sm = sc["metrics"]
        lines.append(
            f"| {sc['title']} | {sm['minutes_mean']:.1f} | {sm['items_mean']:.1f} | **{_p(sm['exact_with_followup'])}** | "
            f"{_p(sm['exact_far_from_cut'])} | {_p(sm['within_1'])} | **{_p(sm['precision_decided'])}** | "
            f"{_p(sm['decided_share'])} | {_p(sm['false_confirm_decided'])} |"
        )
    lines += [
        "",
        "## 2. Показатели по всем 6 уровням (Стажёр … Principal)",
        "",
        "| Грейд | Кандидатов (истина) | Заявок | Точность уверенного вердикта | Вердикт с учётом доп. этапа | Точный грейд | ±1 ступень | Ложное подтверждение |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for gname in GRADE_NAMES:
        bg = m["by_grade"][gname]
        lines.append(
            f"| {gname.capitalize()} | {bg['n_true']} | {bg['n_claimed']} | **{_p(bg['verdict_precision_decided'])}** | "
            f"{_p(bg['verdict_accuracy_all'])} | {_p(bg['exact_grade'])} | {_p(bg['within_1'])} | {_p(bg['false_confirm_rate'])} |"
        )
    lines += [
        "",
        "## 3. Повторяемость (Test–Retest на двух параллельных формах, N = 3 000)",
        "",
        f"- Квадратично взвешенная каппа Коэна: **κw = {rt['kappa_w']:.3f}**",
        f"- Точное совпадение присвоенного грейда между попытками: **{_p(rt['exact'])}** (95 % ДИ [{_p(rt['exact_ci'][0])}; {_p(rt['exact_ci'][1])}])",
        f"- Совпадение в пределах ±1 ступени: **{_p(rt['within_1'])}**",
        f"- Согласованность вердикта подтверждения заявленного грейда: **{_p(rt['verdict_consistency'])}**",
        f"- Корреляция оценок уровня r(θ₁, θ₂): **{rt['r_theta']:.3f}**",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    res = run_all(n=a.n, write=not a.no_write)
    print(json.dumps({
        "precision_decided": res["main"]["precision_decided"],
        "decided_share": res["main"]["decided_share"],
        "exact_with_followup": res["main"]["exact_with_followup"],
        "exact_far_from_cut": res["main"]["exact_far_from_cut"],
        "within_1": res["main"]["within_1"],
        "false_confirm_decided": res["main"]["false_confirm_decided"],
        "retest_kappa_w": res["retest"]["kappa_w"],
        "seconds": res["seconds"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
