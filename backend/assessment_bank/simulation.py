"""Симуляция: восстанавливает ли адаптивный тест θ и грейд при известной «истине».

Все числа получаются из синтетической популяции и синтетических «истинных» параметров
заданий — это проверка механики (оценивание, остановка, ротация, детектор), а не оценка
качества банка на людях. Истинные параметры намеренно отличаются от предкалибровки
(prior_difficulty), чтобы показать цену работы без калибровки.

Сценарии:
* prior_cat       — текущий банк, параметры предкалибровки, истина отличается от них;
* calibrated_cat  — пилот (N≈300 на направление, фиксированная форма, случайные варианты)
                    → иерархическая 2PL-калибровка → адаптивный тест на калиброванных
                    параметрах; отдельно — Раш на малом пилоте (N=20);
* test_retest     — те же люди, два теста на разных субпулах и вариантах;
* leak_*          — утечка 30 % вариантов активного пула + опубликованных канареек,
                    25 % кандидатов пользуются ею; без детектора / с детектором /
                    с детектором и ротацией субпула;
* projected_bank  — синтетический банк ~120 семейств: эффективность адаптивного теста,
                    частота показа без контроля и с Sympson–Hetter;
* fixed_form      — линейная форма той же длины для сравнения.

Случайные числа (с 09.10): у каждой части мира свой поток, выведенный из seed и имени —
истина каждого семейства (по family_id), популяция, пилот и каждый кандидат в каждом сценарии.
Раньше весь прогон шёл одним генератором по порядку, и добавление одного семейства backend
перетасовывало «истину» всех следующих семейств и все популяции frontend: отчёты разных версий
банка сравнивали разные случайные миры. Разброс по мирам (worlds > 0) — отдельная таблица.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import stats

from .psychometrics import (CATConfig, CanaryDetector, GradeScale, PoolItem, TimedResponse,
                            calibrate_sympson_hetter, decide, estimate_theta, fit_hierarchy,
                            fit_mml, pool_from_specs, prob, run_cat)
from .psychometrics.grading import GRADE_ORDER
from .gen_utils import plural
from .registry import load_specs

SCALE = GradeScale()
DIRECTIONS = ("backend", "frontend")


# --------------------------------------------------------------------------- потоки случайных чисел
def _key_ints(keys) -> list[int]:
    out: list[int] = []
    for k in keys:
        if isinstance(k, (tuple, list)):
            out += _key_ints(k)
        elif isinstance(k, (int, np.integer)) and not isinstance(k, bool):
            out.append(int(k) & 0xFFFFFFFFFFFFFFFF)
        else:
            out.append(zlib.crc32(str(k).encode("utf-8")))
    return out


def stream(*keys) -> np.random.Generator:
    """Независимый воспроизводимый поток по ключу (seed, имена…): не зависит от того, сколько
    случайных чисел израсходовали другие части прогона."""
    return np.random.default_rng(_key_ints(keys))


# --------------------------------------------------------------------------- истина
@dataclass
class TrueFamily:
    family_id: str
    a: np.ndarray
    mu: np.ndarray
    sigma: float
    beta_time: float
    time_limit_s: float
    alpha_time: float = 1.6


def make_truth(pool: list[PoolItem], rng: np.random.Generator | None, misspec: float = 0.5, *,
               seed=None) -> dict[str, TrueFamily]:
    """Истинные параметры = предкалибровка + систематическая ошибка эксперта.

    seed=None — прежнее поведение (один генератор rng по порядку пула). seed задан — истина
    каждого семейства из своего потока stream(seed, "truth", family_id): добавление или вывод
    одного семейства не меняет истину остальных.
    """
    out = {}
    for it in pool:
        if seed is not None:
            rng = stream(seed, "truth", it.family_id)
        shift = rng.normal(0, misspec)
        mu = it.b + shift + rng.normal(0, 0.15, size=len(it.b))
        a = it.a * np.exp(rng.normal(0, 0.25))
        sigma = float(np.mean(it.sigma) * np.exp(rng.normal(0, 0.3)))
        out[it.family_id] = TrueFamily(it.family_id, a, mu, sigma,
                                       float(np.log(0.45 * it.time_limit_s) + rng.normal(0, 0.2)),
                                       it.time_limit_s)
    return out


@dataclass
class Person:
    theta: float
    tau: float
    claimed: str
    cheater: bool = False
    knows_canaries: bool = False


def make_population(n: int, rng: np.random.Generator, cheater_share: float = 0.0) -> list[Person]:
    people = []
    for _ in range(n):
        th = float(rng.normal())
        g = SCALE.point(th + rng.normal(0, 0.6))
        claimed = "junior" if g == "none" else g
        ch = bool(rng.random() < cheater_share)
        people.append(Person(th, float(rng.normal(0, 0.3)), claimed, ch, ch and rng.random() < 0.9))
    return people


@dataclass
class LeakModel:
    p_hit_scored: float = 0.0      # вероятность, что выданный вариант есть в утечке
    p_correct: float = 0.95
    fast_fraction: float = 0.15    # доля обычного времени при списывании


def make_responder(person: Person, truth: dict[str, TrueFamily], leak: LeakModel | None = None):
    def respond(item: PoolItem, rng: np.random.Generator):
        tf = truth[item.family_id]
        delta = rng.normal(0, tf.sigma)
        leaked = False
        if person.cheater and leak is not None:
            leaked = (item.canary and person.knows_canaries) or \
                     (not item.canary and rng.random() < leak.p_hit_scored)
        if leaked:
            x = (rng.random(len(tf.mu)) < leak.p_correct).astype(float)
            log_t = float(np.log(leak.fast_fraction * np.exp(tf.beta_time)) + rng.normal(0, 0.3))
        else:
            p = prob(person.theta, tf.a, tf.mu + delta)
            x = (rng.random(len(tf.mu)) < p).astype(float)
            log_t = float(rng.normal(tf.beta_time - person.tau, 1 / tf.alpha_time))
        return x, min(log_t, float(np.log(tf.time_limit_s)))
    return respond


# --------------------------------------------------------------------------- метрики
def _grade_idx(theta) -> np.ndarray:
    return SCALE.points(np.asarray(theta))


def quadratic_kappa(a: np.ndarray, b: np.ndarray, k: int = 4) -> float:
    O = np.zeros((k, k))
    for i, j in zip(a, b):
        O[i, j] += 1
    W = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0)) / max(O.sum(), 1)
    return float(1 - (W * O).sum() / max((W * E).sum(), 1e-12))


def summarize(people: list[Person], results: list[dict]) -> dict:
    th = np.array([p.theta for p in people])
    est = np.array([r["theta"] for r in results])
    se = np.array([r["se"] for r in results])
    n_items = np.array([r["n_items"] for r in results])
    gi_true, gi_est = _grade_idx(th), _grade_idx(est)
    conf = np.array([r["confirmed"] for r in results])
    truly = np.array([p.theta >= SCALE.cuts[p.claimed] for p in people])
    cover = np.mean(np.abs(est - th) <= 1.96 * se)
    return {
        "n": len(people),
        "r_theta": round(float(np.corrcoef(th, est)[0, 1]), 3),
        "rmse": round(float(np.sqrt(np.mean((est - th) ** 2))), 3),
        "bias": round(float(np.mean(est - th)), 3),
        "mean_se": round(float(np.mean(se)), 3),
        "ci95_coverage": round(float(cover), 3),
        "mean_items": round(float(np.mean(n_items)), 2),
        "grade_exact": round(float(np.mean(gi_true == gi_est)), 3),
        "grade_within_1": round(float(np.mean(np.abs(gi_true - gi_est) <= 1)), 3),
        "decision_accuracy": round(float(np.mean(conf == truly)), 3),
        "false_confirm_rate": round(float(np.mean(conf[~truly])) if (~truly).any() else 0.0, 3),
        "false_reject_rate": round(float(np.mean(~conf[truly])) if truly.any() else 0.0, 3),
        "mean_time_min": round(float(np.mean([r["time_s"] for r in results]) / 60), 1),
    }


def _session_record(sess, res, person: Person) -> dict:
    d = decide(res.theta, res.se, person.claimed)
    return {"theta": res.theta, "se": res.se, "n_items": res.n_items, "time_s": res.time_used_s,
            "confirmed": d.confirmed, "stop": res.stop_reason}


def run_population(pool, truth, people, direction, cfg, rng, subpools=None, exposure=None,
                   leak: LeakModel | None = None, detector: CanaryDetector | None = None,
                   keep_sessions: bool = False, *, person_key=None):
    """person_key задан — у k-го кандидата свой поток stream(person_key, k) (общие случайные
    числа: сценарии с одним ключом сравниваются на одних и тех же «бросках»)."""
    results, sessions = [], []
    for k, p in enumerate(people):
        sp = subpools[k] if subpools is not None else None
        r = stream(person_key, k) if person_key is not None else rng
        sess, res = run_cat(pool, direction, make_responder(p, truth, leak), cfg, exposure,
                            p.claimed, sp, r)
        rec = _session_record(sess, res, p)
        if detector is not None:
            rec.update(_apply_detector(sess, res, p, detector))
        results.append(rec)
        if keep_sessions:
            sessions.append(sess)
    return results, sessions


def _timed(sess, res):
    lookup = getattr(sess, "items", None) or {i.family_id: i for i in sess.scored_pool + sess.canary_pool}
    clean, canary, idx = [], [], []
    for k, adm in enumerate(res.administered):
        it = lookup[adm.family_id]
        p_exp = float(np.mean(prob(res.theta, it.a_eff, it.b)))
        tr = TimedResponse(float(np.mean(adm.x)), float(adm.log_t), it.beta_time, it.alpha_time, p_exp)
        (canary if adm.canary else clean).append(tr)
        if not adm.canary:
            idx.append(k)
    return clean, canary, idx


def _apply_detector(sess, res, person: Person, det: CanaryDetector) -> dict:
    clean, canary, idx = _timed(sess, res)
    st = det.statistic(clean, canary)
    out = {"combined": st.combined, "flagged": st.flagged}
    if st.flagged:
        mask = det.suspicious_mask(clean, st.tau_clean)
        excl = {idx[i] for i in np.flatnonzero(mask)}
        th, se = sess.rescore(excl) if len(excl) < len(idx) else (sess.cfg.start_theta.get(person.claimed, 0.0), 1.0)
        d = decide(th, se, person.claimed)
        # флаг — повод для ручной проверки и пересдачи; грейд по «чистым» ответам
        out.update({"theta": th, "se": se, "confirmed": d.confirmed, "rescored": True})
    return out


# --------------------------------------------------------------------------- калибровка
def simulate_pilot(pool, truth, n, rng, n_variants=30, *, key=None):
    """Пилот: фиксированная форма из всех некарантинных семейств, случайные варианты.

    key задан — θ участников из stream(key, "theta"), варианты и ответы по семейству — из
    stream(key, family_id): набор семейств не сдвигает случайные числа остальных."""
    person, item, variant, x = [], [], [], []
    if key is None:
        deltas = {it.family_id: rng.normal(0, truth[it.family_id].sigma, n_variants) for it in pool}
        thetas = rng.normal(size=n)
        draws = None
    else:
        thetas = stream(key, "theta").normal(size=n)
        deltas, draws = {}, {}
        for it in pool:
            if it.canary:
                continue
            r = stream(key, it.family_id)
            deltas[it.family_id] = r.normal(0, truth[it.family_id].sigma, n_variants)
            draws[it.family_id] = (r.integers(n_variants, size=n),
                                   r.random((n, len(truth[it.family_id].mu))))
    for pi, th in enumerate(thetas):
        for it in pool:
            if it.canary:
                continue
            tf = truth[it.family_id]
            if draws is None:
                v = int(rng.integers(n_variants))
                u = rng.random(len(tf.mu))
            else:
                v, u = int(draws[it.family_id][0][pi]), draws[it.family_id][1][pi]
            p = prob(th, tf.a, tf.mu + deltas[it.family_id][v])
            xs = (u < p).astype(float)
            for part, xv in enumerate(xs):
                person.append(pi)
                item.append(f"{it.family_id}#{part}")
                variant.append(f"{it.family_id}:{v}")
                x.append(xv)
    return np.array(person), np.array(item), np.array(variant), np.array(x)


def calibrated_params(hres, pool) -> dict:
    params = {}
    for it in pool:
        if it.canary:
            continue
        parts = [hres.families.get(f"{it.family_id}#{k}") for k in range(len(it.b))]
        if any(p is None for p in parts):
            continue
        params[it.family_id] = {"a": [p.a for p in parts], "b": [p.mu for p in parts],
                                "sigma": [p.sigma for p in parts]}
    return params


def calibration_quality(hres, truth) -> dict:
    est_b, true_b, est_a, true_a, est_s, true_s = [], [], [], [], [], []
    for iid, fp in hres.families.items():
        fid, part = iid.split("#")
        tf = truth[fid]
        est_b.append(fp.mu)
        true_b.append(tf.mu[int(part)])
        est_a.append(fp.a)
        true_a.append(tf.a[int(part)])
        est_s.append(fp.sigma)
        true_s.append(tf.sigma)
    def r(u, v):
        if np.std(u) < 1e-9 or np.std(v) < 1e-9:
            return None          # параметр не оценивается моделью (например, a в модели Раша)
        return round(float(np.corrcoef(u, v)[0, 1]), 3)
    return {"n_items": len(est_b), "r_b": r(est_b, true_b), "r_a": r(est_a, true_a),
            "r_sigma": r(est_s, true_s),
            "rmse_b": round(float(np.sqrt(np.mean((np.array(est_b) - true_b) ** 2))), 3)}


def prior_quality(pool, truth) -> dict:
    b_prior = np.concatenate([it.b for it in pool])
    b_true = np.concatenate([truth[it.family_id].mu for it in pool])
    return {"r_b_prior": round(float(np.corrcoef(b_prior, b_true)[0, 1]), 3),
            "rmse_b_prior": round(float(np.sqrt(np.mean((b_prior - b_true) ** 2))), 3)}


# --------------------------------------------------------------------------- синтетический банк
def projected_pool(rng, n_per_block: int = 40, n_canary: int = 2) -> list[PoolItem]:
    items = []
    for block in ("common",) + DIRECTIONS:
        for k in range(n_per_block + n_canary):
            ob3 = rng.random() < 0.2
            b0 = rng.normal(0.2, 0.9)
            b = b0 + (np.array([-0.5, 0.0, 0.8]) if ob3 else np.array([0.0]))
            a = np.full(len(b), float(np.exp(rng.normal(0, 0.25))))
            tl = float(rng.choice([120, 240, 300, 900 if ob3 else 300]))
            items.append(PoolItem(f"{block}.synthetic.f{k:03d}", block,
                                  "open_book_3step" if ob3 else "predict_output",
                                  ("junior", "middle", "senior"), k >= n_per_block,
                                  a, b, np.full(len(b), 0.3), tl, float(np.log(0.45 * tl))))
    return items


def assign_subpools(pool, n_subpools):
    for block in sorted({i.block for i in pool}):
        blk = sorted([i for i in pool if i.block == block and not i.canary], key=lambda i: float(np.mean(i.b)))
        for k, it in enumerate(blk):
            r = k % (2 * n_subpools)
            it.subpool = r if r < n_subpools else 2 * n_subpools - 1 - r


# --------------------------------------------------------------------------- линейная форма
def fixed_form(pool, truth, people, direction, rng, n_items, *, key=None):
    """key задан — форма из stream(key, "form"), ответы k-го кандидата из stream(key, k)."""
    scored = [i for i in pool if not i.canary and i.block in ("common", direction)]
    form_rng = stream(key, "form") if key is not None else rng
    form = list(form_rng.choice(len(scored), size=min(n_items, len(scored)), replace=False))
    res = []
    for k, p in enumerate(people):
        xs, aa, bb = [], [], []
        resp = make_responder(p, truth)
        r = stream(key, k) if key is not None else rng
        t = 0.0
        for j in form:
            it = scored[j]
            x, lt = resp(it, r)
            xs.append(x)
            aa.append(it.a_eff)
            bb.append(it.b)
            t += float(np.exp(lt))
        est = estimate_theta(np.concatenate(xs), np.concatenate(aa), np.concatenate(bb))
        d = decide(est.theta, est.se, p.claimed)
        res.append({"theta": est.theta, "se": est.se, "n_items": len(form), "time_s": t,
                    "confirmed": d.confirmed})
    return res


# --------------------------------------------------------------------------- главный прогон
def _calibrate(specs, base_pool, truth, direction, key, n_pilot: int = 300):
    """Пилот N = n_pilot → иерархическая 2PL → пул с калиброванными параметрами (и качество калибровки)."""
    dir_pool = [i for i in base_pool if i.block in ("common", direction)]
    P, I, V, X = simulate_pilot(dir_pool, truth, n_pilot, None, key=(key, f"pilot{n_pilot}"))
    hres = fit_hierarchy(P, I, V, X, model="2pl")
    params = calibrated_params(hres, dir_pool)
    cal_pool = pool_from_specs(list(specs.values()), params=params, n_subpools=2)
    return cal_pool, hres, dir_pool


WORLD_METRICS = ("r_theta", "rmse", "bias", "mean_items", "grade_exact", "decision_accuracy",
                 "false_confirm_rate", "false_reject_rate")


def _world(args) -> dict:
    """Один «мир»: своя истина, популяция и пилот; prior_cat и calibrated_cat по обоим направлениям."""
    seed, w, n = args
    wk = (seed, "world", w)
    specs = load_specs()
    base_pool = pool_from_specs(specs.values(), n_subpools=2)
    truth = make_truth(base_pool, None, seed=wk)
    cfg = CATConfig()
    out = {}
    for d in DIRECTIONS:
        people = make_population(n, stream(wk, d, "people"))
        res, _ = run_population(base_pool, truth, people, d, cfg, None, person_key=(wk, d, "cat"))
        prior = summarize(people, res)
        cal_pool, hres, _ = _calibrate(specs, base_pool, truth, d, (wk, d))
        res, _ = run_population(cal_pool, truth, people, d, cfg, None, person_key=(wk, d, "cat"))
        cal = summarize(people, res)
        out[d] = {"prior_cat": {k: prior[k] for k in WORLD_METRICS},
                  "calibrated_cat": {k: cal[k] for k in WORLD_METRICS},
                  "calibration_rmse_b": calibration_quality(hres, truth)["rmse_b"]}
    return out


def _world_subprocess(args) -> dict:
    """Мир в отдельном процессе Python (без multiprocessing: на сервере проверок /dev/shm закрыт на запись)."""
    code = ("import json, sys; from assessment_bank.simulation import _world; "
            "print(json.dumps(_world(tuple(json.loads(sys.argv[1])))))")
    root = str(Path(__file__).resolve().parent.parent)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (root, os.environ.get("PYTHONPATH")) if p)}
    r = subprocess.run([sys.executable, "-c", code, json.dumps(list(args))], capture_output=True, text=True,
                       env=env, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def world_spread(seed: int, n: int, worlds: int, jobs: int = 1, main: dict | None = None) -> dict:
    """Разброс метрик prior_cat и calibrated_cat по `worlds` независимым мирам (тот же банк, тот же N).
    jobs > 1 — миры в отдельных процессах; результат тот же, что при jobs = 1 (у мира свои потоки)."""
    args = [(seed, w, n) for w in range(1, worlds + 1)]
    if jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            ws = list(ex.map(_world_subprocess, args))
    else:
        ws = [_world(a) for a in args]
    out: dict = {"worlds": worlds, "n_per_world": n, "per_world": ws, "summary": {}}
    for d in DIRECTIONS:
        for sc in ("prior_cat", "calibrated_cat"):
            S = out["summary"].setdefault(d, {}).setdefault(sc, {})
            for m in WORLD_METRICS:
                v = np.array([w[d][sc][m] for w in ws], dtype=float)
                S[m] = {"mean": round(float(v.mean()), 3), "sd": round(float(v.std(ddof=1)), 3) if len(v) > 1 else 0.0,
                        "min": round(float(v.min()), 3), "max": round(float(v.max()), 3)}
                if main is not None:
                    S[m]["main_world"] = main[d][sc][m]
    return out


def run_all(n: int = 1000, seed: int = 20261005, out_dir: str | None = None,
            progress: bool = True, worlds: int = 0, jobs: int = 1) -> dict:
    """Главный прогон. Все случайные числа — из потоков stream(seed, …) (см. описание модуля);
    worlds > 0 — дополнительно разброс prior_cat/calibrated_cat по стольким независимым мирам."""
    t0 = time.time()
    specs = load_specs()
    log = (lambda *a: print(*a, flush=True)) if progress else (lambda *a: None)
    report: dict = {"seed": seed, "n_per_scenario": n, "rng": "keyed-v1", "bank": {}, "scenarios": {}}
    base_pool = pool_from_specs(specs.values(), n_subpools=2)
    truth = make_truth(base_pool, None, seed=seed)
    report["bank"] = {"families": len(base_pool),
                      "scored_by_direction": {d: sum(1 for i in base_pool if not i.canary and
                                                     i.block in ("common", d)) for d in DIRECTIONS},
                      "canaries": sum(1 for i in base_pool if i.canary),
                      **prior_quality(base_pool, truth)}
    cfg = CATConfig()
    for direction in DIRECTIONS:
        R = report["scenarios"].setdefault(direction, {})
        K = (seed, direction)
        people = make_population(n, stream(K, "people"))
        # 1. предкалибровка
        res, _ = run_population(base_pool, truth, people, direction, cfg, None, person_key=(K, "cat"))
        R["prior_cat"] = summarize(people, res)
        log(direction, "prior_cat", R["prior_cat"])
        # 2. пилот и калибровка
        cal_pool, hres, dir_pool = _calibrate(specs, base_pool, truth, direction, K)
        R["calibration_2pl_n300"] = calibration_quality(hres, truth)
        P20, I20, V20, X20 = simulate_pilot(dir_pool, truth, 20, None, key=(K, "pilot20"))
        h20 = fit_hierarchy(P20, I20, V20, X20, model="rasch")
        R["calibration_rasch_n20"] = calibration_quality(h20, truth)
        res, _ = run_population(cal_pool, truth, people, direction, cfg, None, person_key=(K, "cat"))
        R["calibrated_cat"] = summarize(people, res)
        log(direction, "calibrated_cat", R["calibrated_cat"])
        # 3. test-retest на разных субпулах и вариантах
        r1, _ = run_population(cal_pool, truth, people, direction, cfg, None, subpools=[0] * n,
                               person_key=(K, "retest", 0))
        r2, _ = run_population(cal_pool, truth, people, direction, cfg, None, subpools=[1] * n,
                               person_key=(K, "retest", 1))
        t1, t2 = np.array([r["theta"] for r in r1]), np.array([r["theta"] for r in r2])
        g1, g2 = _grade_idx(t1), _grade_idx(t2)
        c1, c2 = np.array([r["confirmed"] for r in r1]), np.array([r["confirmed"] for r in r2])
        R["test_retest_subpools"] = {
            "r_theta": round(float(np.corrcoef(t1, t2)[0, 1]), 3),
            "grade_exact_agreement": round(float(np.mean(g1 == g2)), 3),
            "grade_kappa_quadratic": round(quadratic_kappa(g1, g2), 3),
            "decision_agreement": round(float(np.mean(c1 == c2)), 3),
            "mean_items": round(float(np.mean([r["n_items"] for r in r1 + r2])), 2),
            "subpool_0": summarize(people, r1), "subpool_1": summarize(people, r2)}
        log(direction, "retest", {k: v for k, v in R["test_retest_subpools"].items() if "subpool" not in k})
        # 4. утечка 30 % + канарейки, 25 % кандидатов используют утечку
        cheaters = make_population(n, stream(K, "cheaters"), cheater_share=0.25)
        honest_people = [p for p in cheaters if not p.cheater]
        det0 = CanaryDetector()
        res_h, _ = run_population(cal_pool, truth, honest_people, direction, cfg, None, detector=det0,
                                  person_key=(K, "leak_threshold"))
        thr = CanaryDetector.calibrate_threshold(np.array([r["combined"] for r in res_h]), 0.01)
        det = CanaryDetector(threshold=thr)
        leak = LeakModel(p_hit_scored=0.30)
        variants = {
            "leak_no_detector": dict(leak=leak, detector=None),
            "leak_detector": dict(leak=leak, detector=det),
            "leak_detector_rotation": dict(leak=LeakModel(p_hit_scored=0.0), detector=det),
        }
        L = R.setdefault("leak", {"threshold_combined": round(thr, 3),
                                  "threshold_nominal": 2.33, "cheater_share": 0.25,
                                  "leaked_share_of_active_variants": 0.30,
                                  "note": "rotation: утёкший субпул выведен из ротации, "
                                          "кандидатам выдаётся другой; канарейки остаются "
                                          "опубликованными по замыслу"})
        base_res, _ = run_population(cal_pool, truth, cheaters, direction, cfg, None, person_key=(K, "leak"))
        L["no_leak_reference"] = _leak_summary(cheaters, base_res)
        for name, kw in variants.items():
            res, _ = run_population(cal_pool, truth, cheaters, direction, cfg, None, person_key=(K, "leak"), **kw)
            L[name] = _leak_summary(cheaters, res)
            log(direction, name, L[name])
        # 5. линейная форма той же длины, что средний адаптивный тест
        n_fixed = int(round(R["calibrated_cat"]["mean_items"]))
        R["fixed_form_same_length"] = summarize(people, fixed_form(cal_pool, truth, people, direction, None,
                                                                   n_fixed, key=(K, "fixed_form")))
    # 6. синтетический банк ~120 семейств
    report["scenarios"]["projected_bank"] = _projected(n, stream(seed, "projected"), log)
    # 7. разброс по мирам
    if worlds > 0:
        main = {d: {sc: report["scenarios"][d][sc] for sc in ("prior_cat", "calibrated_cat")} for d in DIRECTIONS}
        report["world_spread"] = world_spread(seed, n, worlds, jobs, main)
        log("world_spread", {d: {sc: report["world_spread"]["summary"][d][sc]["decision_accuracy"]
                                 for sc in ("prior_cat", "calibrated_cat")} for d in DIRECTIONS})
    report["elapsed_s"] = round(time.time() - t0, 1)
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "simulation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
        (out / "simulation_report.md").write_text(report_markdown(report), encoding="utf-8")
    return report


def _leak_summary(people, results) -> dict:
    ch = np.array([p.cheater for p in people])
    th = np.array([p.theta for p in people])
    est = np.array([r["theta"] for r in results])
    conf = np.array([r["confirmed"] for r in results])
    truly = np.array([p.theta >= SCALE.cuts[p.claimed] for p in people])
    flagged = np.array([r.get("flagged", False) for r in results])
    gi_t, gi_e = _grade_idx(th), _grade_idx(est)
    out = {
        "cheaters_bias_theta": round(float(np.mean((est - th)[ch])), 3),
        "honest_bias_theta": round(float(np.mean((est - th)[~ch])), 3),
        "cheaters_grade_inflated": round(float(np.mean((gi_e > gi_t)[ch])), 3),
        "cheaters_false_confirm": round(float(np.mean(conf[ch & ~truly])) if (ch & ~truly).any() else 0.0, 3),
        "honest_false_confirm": round(float(np.mean(conf[~ch & ~truly])) if (~ch & ~truly).any() else 0.0, 3),
        "honest_decision_accuracy": round(float(np.mean((conf == truly)[~ch])), 3),
    }
    if any("flagged" in r for r in results):
        out["detector_tpr"] = round(float(np.mean(flagged[ch])), 3)
        out["detector_fpr"] = round(float(np.mean(flagged[~ch])), 3)
    return out


def _projected(n, rng, log) -> dict:
    pool = projected_pool(rng)
    truth = make_truth(pool, rng, misspec=0.0)          # параметры считаем откалиброванными
    out = {"families": len(pool), "per_block": 40, "canaries_per_block": 2}
    cfg = CATConfig()
    people = make_population(n, rng)
    res, _ = run_population(pool, truth, people, "backend", cfg, rng)
    out["cat_se035_max20"] = summarize(people, res)
    cfg30 = CATConfig(max_items=30, se_target=0.30)
    res30, _ = run_population(pool, truth, people, "backend", cfg30, rng)
    out["cat_se030_max30"] = summarize(people, res30)
    out["fixed_form_20"] = summarize(people, fixed_form(pool, truth, people, "backend", rng, 20))
    log("projected", out["cat_se035_max20"])
    # частота показа: без контроля, с Sympson–Hetter, с SH и двумя субпулами
    resp_factory = lambda th: make_responder(Person(th, 0.0, "middle"), truth)
    expo = {}
    m = max(200, n // 2)
    from .psychometrics import ExposureControl
    ctrl_none = ExposureControl(r_max=1.0)
    for _ in range(m):
        run_cat(pool, "backend", resp_factory(float(rng.normal())), cfg, ctrl_none, "middle", None, rng)
    rates = ctrl_none.exposure_rates()
    expo["none"] = _expo_stats(rates, pool)
    ctrl, hist = calibrate_sympson_hetter(pool, "backend", resp_factory, cfg, r_max=0.3,
                                          n_sessions=m, iterations=10, seed=int(rng.integers(1e9)))
    ctrl.reset_counts()
    ppl = make_population(m, rng)
    res_sh, _ = run_population(pool, truth, ppl, "backend", cfg, rng, exposure=ctrl)
    expo["sympson_hetter_r0.3"] = {**_expo_stats(ctrl.exposure_rates(), pool),
                                   "calibration_max_history": [round(h, 3) for h in hist],
                                   "accuracy": summarize(ppl, res_sh)}
    assign_subpools(pool, 2)
    ctrl.reset_counts()
    sp = [k % 2 for k in range(m)]
    res_sp, _ = run_population(pool, truth, ppl, "backend", cfg, rng, subpools=sp, exposure=ctrl)
    expo["sh_plus_2_subpools"] = {**_expo_stats(ctrl.exposure_rates(), pool),
                                  "accuracy": summarize(ppl, res_sp)}
    out["exposure"] = expo
    log("projected exposure", {k: {kk: vv for kk, vv in v.items() if kk.startswith("max") or kk.startswith("share")}
                               for k, v in expo.items()})
    return out


def _expo_stats(rates: dict, pool) -> dict:
    scored = [i.family_id for i in pool if not i.canary and i.block in ("common", "backend")]
    r = np.array([rates.get(f, 0.0) for f in scored])
    return {"max_exposure": round(float(r.max()), 3), "mean_exposure": round(float(r.mean()), 3),
            "share_unused": round(float(np.mean(r == 0)), 3),
            "share_over_0.3": round(float(np.mean(r > 0.3)), 3)}


# --------------------------------------------------------------------------- отчёт
def report_markdown(rep: dict) -> str:
    L = [f"# Симуляция адаптивного теста (seed {rep['seed']}, N = {rep['n_per_scenario']} на сценарий)", "",
         "Синтетическая популяция θ ~ N(0, 1); истинные параметры заданий отличаются от "
         "предкалибровки (сдвиг трудности семейства σ = 0,5, наклон × lognormal(0, 0,25)). "
         "Пороги грейдов предварительные: Junior −1,0; Middle 0,0; Senior 1,0.", "",
         f"Банк: {rep['bank']['families']} семейств, канареек {rep['bank']['canaries']}; оцениваемых "
         f"семейств на направление: {rep['bank']['scored_by_direction']}. Предкалибровка против "
         f"истины: r(b) = {rep['bank']['r_b_prior']}, RMSE(b) = {rep['bank']['rmse_b_prior']}.", ""]
    if rep.get("rng") == "keyed-v1":
        L += ["Случайные числа — потоки по ключу (seed, семейство / сценарий / кандидат): истина семейства не "
              "зависит от состава банка, prior_cat и calibrated_cat идут на одних и тех же кандидатах и бросках. "
              "Таблицы ниже — один мир (этот seed); разброс по независимым мирам — в конце отчёта.", ""]
    hdr = ("| Сценарий | r(θ̂,θ) | RMSE | SE | покрытие 95 % | заданий | грейд точно | ±1 | решение верно | "
           "ложн. подтв. | ложн. отказ | мин |")
    sep = "|" + "---|" * 12
    for d in DIRECTIONS:
        R = rep["scenarios"][d]
        L += [f"## {d}", "", hdr, sep]
        for name in ("prior_cat", "calibrated_cat", "fixed_form_same_length"):
            s = R[name]
            L.append(f"| {name} | {s['r_theta']} | {s['rmse']} | {s['mean_se']} | {s['ci95_coverage']} | "
                     f"{s['mean_items']} | {s['grade_exact']} | {s['grade_within_1']} | "
                     f"{s['decision_accuracy']} | {s['false_confirm_rate']} | {s['false_reject_rate']} | "
                     f"{s['mean_time_min']} |")
        c2, c20 = R["calibration_2pl_n300"], R["calibration_rasch_n20"]
        tr = R["test_retest_subpools"]
        L += ["", f"Калибровка 2PL, пилот N = 300: r(b) = {c2['r_b']}, r(a) = {c2['r_a']}, "
                  f"r(σ) = {c2['r_sigma']}, RMSE(b) = {c2['rmse_b']}. Раш, N = 20: r(b) = {c20['r_b']}, "
                  f"RMSE(b) = {c20['rmse_b']}.", "",
              f"Test-retest (разные субпулы и варианты): r = {tr['r_theta']}, совпадение грейда "
              f"{tr['grade_exact_agreement']}, κ (квадр.) = {tr['grade_kappa_quadratic']}, совпадение "
              f"решения о заявленном грейде {tr['decision_agreement']}, заданий в среднем {tr['mean_items']}.", "",
              "Утечка 30 % вариантов + канарейки, 25 % кандидатов пользуются утечкой "
              f"(порог детектора по честной популяции при FPR 1 %: {R['leak']['threshold_combined']}):", "",
              "| Режим | смещение θ (списывающие) | завышен грейд | ложн. подтв. (списыв.) | "
              "ложн. подтв. (честные) | TPR | FPR |", "|---|---|---|---|---|---|---|"]
        for name in ("no_leak_reference", "leak_no_detector", "leak_detector", "leak_detector_rotation"):
            s = R["leak"][name]
            L.append(f"| {name} | {s['cheaters_bias_theta']} | {s['cheaters_grade_inflated']} | "
                     f"{s['cheaters_false_confirm']} | {s['honest_false_confirm']} | "
                     f"{s.get('detector_tpr', '—')} | {s.get('detector_fpr', '—')} |")
        L.append("")
    P = rep["scenarios"]["projected_bank"]
    L += ["## Проекция: синтетический банк ~120 семейств (параметры откалиброваны)", "", hdr, sep]
    for name in ("cat_se035_max20", "cat_se030_max30", "fixed_form_20"):
        s = P[name]
        L.append(f"| {name} | {s['r_theta']} | {s['rmse']} | {s['mean_se']} | {s['ci95_coverage']} | "
                 f"{s['mean_items']} | {s['grade_exact']} | {s['grade_within_1']} | "
                 f"{s['decision_accuracy']} | {s['false_confirm_rate']} | {s['false_reject_rate']} | "
                 f"{s['mean_time_min']} |")
    L += ["", "| Контроль показа | макс. частота | средняя | не используется | доля > 0,3 |", "|---|---|---|---|---|"]
    for name, s in P["exposure"].items():
        L.append(f"| {name} | {s['max_exposure']} | {s['mean_exposure']} | {s['share_unused']} | {s['share_over_0.3']} |")
    W = rep.get("world_spread")
    if W:
        nw = W["worlds"]
        L += ["", f"## Разброс по мирам ({nw} {plural(nw, 'независимый мир', 'независимых мира', 'независимых миров')}, "
                  f"N = {W['n_per_world']} в каждом)", "",
              "В каждом мире — своя истина параметров (тот же сдвиг σ = 0,5 относительно предкалибровки), своя "
              "популяция и свой пилот N = 300; банк и правила те же. «Мир seed» — значение основного мира из таблиц "
              "выше. Разница между версиями банка в одном мире, меньшая примерно двух SD, — разброс миров, а не "
              "свойство банка.", "",
              "| Направление | Сценарий | Метрика | мир seed | среднее | SD | мин | макс |", "|" + "---|" * 8]
        names = {"decision_accuracy": "решение верно", "false_reject_rate": "ложн. отказ",
                 "false_confirm_rate": "ложн. подтв.", "bias": "смещение θ̂", "r_theta": "r(θ̂,θ)",
                 "mean_items": "заданий"}
        for d in DIRECTIONS:
            for sc in ("prior_cat", "calibrated_cat"):
                for m, title in names.items():
                    v = W["summary"][d][sc][m]
                    L.append(f"| {d} | {sc} | {title} | {v.get('main_world', '—')} | {v['mean']} | {v['sd']} | "
                             f"{v['min']} | {v['max']} |")
    L += ["", f"Время прогона: {rep['elapsed_s']} с.", ""]
    return "\n".join(L)
