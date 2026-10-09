"""Test–retest всего пути кандидата и дискриминативность семейств — на симуляции в конфигурации платформы.

    make path-retest    # cd backend && python -m app.modules.validation.path_retest [--n 500] [--quick]

Путь — как у живого кандидата, из функций продукта (ничего не переписано заново):
1. опрос: стаж (лет) → подсказка грейда ``grade_hint.grade_by_years``; самооценка — θ + N(0; 0,6) на шкале платформы
   (ниже порога Стажёра — Стажёр); заявленный грейд — подсказка (с вероятностью 0,5) или самооценка; без
   коммерческого стажа и с самооценкой «Стажёр» — Стажёр. Стек опроса — фильтр семейств ``bank_engine.stack_excluded``;
2. адаптивный тест на банке (все семейства выдачи) — ``AppCATSession`` с настройками платформы
   (``sim.app_config_from_settings``): классификационная остановка, дотестирование у порога, Sympson — Hetter,
   ротация субпулов ``exposure.choose_subpool`` по истории сессий, семейства последней сессии не в дотестировании,
   тест Стажёра — без ротации и только по лёгким семействам (``intern_pool.intern_exclusions``);
3. детектор предзнания и пересчёт θ, как в ``bank_engine.finish``; решение — ``grades.decide_grade`` (P ≥ 0,8,
   «Junior (предварительно)» при P от 0,10);
4. не подтверждён: «принять уровень ниже без нового теста» (``rules.accept_lower_allowed``, P ≥ 0,8), иначе — один
   тест ступенью ниже (в продукте он доступен сразу), иначе категории нет.
Повтор — та же процедура ещё раз с историей первой (другой субпул, новые варианты заданий); 30- и 90-дневные
блокировки не моделируются: они ограничивают частоту попыток, а не результат.

Метрики: точное совпадение итогового грейда, ±1 ступень, квадратично взвешенная κ (5 ступеней: без категории,
Стажёр, Junior, Middle, Senior) с бутстрэп-ДИ 95 %, ICC(2,1) по θ̂ первой сессии (тот же заявленный грейд), доля
повторов семейств между попытками; разрезы «уверенные / у порога» (по решению и по истинному θ), направления,
заявленные грейды; точность итогового грейда к истине. Дискриминативность: индекс D (верхние 27 % − нижние 27 % по
сумме остальных заданий) и точечно-бисериальная r_pb «задание — остальные» на симулированном пилоте (все семейства
блока, θ ~ N(0; 1), авторские параметры заданий); рядом — r_pb на панели моделей, если панель доступна (BANK_DIR).

Всё синтетическое: истинные параметры заданий = предкалибровка + ошибка эксперта σ = 0,5 (как везде на
/validation), проверяется механика процедуры, а не качество заданий на людях. Результат — data/path_retest.json
(для /validation) и docs/validation/TEST_RETEST.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import time

import numpy as np
from scipy import special

from assessment_bank.psychometrics import CanaryDetector, ExposureControl
from assessment_bank.simulation import Person, TrueFamily, _timed, make_responder, make_truth

from app.modules.assessment.bank_engine import stack_excluded
from app.modules.assessment.exposure import choose_subpool, exposure_table
from app.modules.assessment.grade_hint import grade_by_years
from app.modules.assessment.grades import cuts_tuple, decide_grade, point_grade
from app.modules.assessment.intern_pool import intern_exclusions
from app.modules.assessment.rules import accept_lower_allowed
from app.modules.catalog.seed_data import GRADE_CUTS, GRADE_ORDER
from app.modules.validation import sim
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT = HERE / "data" / "path_retest.json"
DOCS_MD = REPO / "docs" / "validation" / "TEST_RETEST.md"

SEED = 20261006          # мир симуляции теста /validation (make validate, бенчмарк подбора — тот же seed)
LEVELS = ("none",) + tuple(GRADE_ORDER)   # 0 — без категории, 1 — Стажёр, …, 4 — Senior
LEVEL_RU = {"none": "без категории", "intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior"}
P_FOLLOW_HINT = 0.5      # доля заявляющих грейд по подсказке опроса (остальные — по самооценке)
SELF_SD = 0.6            # шум самооценки, как в assessment_bank.simulation.make_population
BORDER = 0.25            # «у порога»: |θ − ближайший порог| < 0,25 (как у Прототип А)
N_BOOT = 2000
WEAK_D, WEAK_RPB = 0.2, 0.2   # слабое на симуляции: D < 0,2 или r_pb < 0,2 (критерий Прототип А — D ≥ 0,2 у ≥ 2/3)
WEAK_PANEL = 0.15             # слабое на панели моделей: r_pb < 0,15 (независимая проверка, шкала моделей ≠ шкала людей)
BACKEND_LANGS = ("django", "go", "java", None)  # основной язык бэкенда в опросе (None — Python без Django и др.)
# Аудит банка 08.10 (раздел «на переделку»): подсказки длиной или структурой верного варианта, неточные дистракторы.
# Сверка с D / r_pb: это другой сигнал (подсказка облегчает задание для «угадывающих по форме»), пересечение — в отчёте.
BANK_AUDIT_REWORK = (
    "backend.kafka.outbox_relay_fix", "backend.django.migration_default_bug", "qa.load.percentile_merge_mcq",
    "common.git.undo_mcq", "common.db.tx_isolation_mcq", "security.web.cors_csrf_mcq", "security.web.cookie_policy_mcq",
    "frontend.js.listener_leak_fix", "qa.sql.reconciliation_fix", "common.docker.cache_order_fix",
    "security.supply.dependency_patch_fix", "frontend.a11y.focus_trap_ob3", "common.db.index_plan_mcq",
    "backend.kafka.offset_commit_mcq", "data_ml.fe.onehot_serving_fix",
)
GAP_SHARE, GAP_MIN_ITEMS = 0.3, 4  # флаг «общий блок сильнее направления» (консилиум 07.10, п. 7.4)


# ---------------------------------------------------------------- кандидаты (опрос → заявленный грейд)

@dataclass
class Candidate:
    theta: float
    tau: float
    direction: str
    years: float
    hint: str
    self_grade: str
    claimed: str
    stack: list[str] = field(default_factory=list)


def survey_years(theta: float, rng: np.random.Generator) -> float:
    """Стаж из опроса: при θ = 0 — 1,5 года (граница Junior/Middle подсказки), при θ = 1 — 4,5 (Middle/Senior), шум 1 год."""
    return round(float(max(0.0, 1.5 + 3.0 * theta + rng.normal(0, 1.0))), 1)


def make_candidates(n: int, direction: str, rng: np.random.Generator) -> list[Candidate]:
    out = []
    for _ in range(n):
        th, tau = float(rng.normal()), float(rng.normal(0, 0.3))
        years = survey_years(th, rng)
        hint = grade_by_years(years)
        sg = point_grade(th + float(rng.normal(0, SELF_SD)))
        sg = "intern" if sg == "none" else sg
        if rng.random() < P_FOLLOW_HINT:
            claimed = "intern" if (hint == "junior" and sg == "intern" and years < 0.5) else hint
        else:
            claimed = sg
        stack: list[str] = []
        if direction == "backend":
            lang = BACKEND_LANGS[int(rng.integers(len(BACKEND_LANGS)))]
            if lang:
                stack.append(lang)
            if rng.random() < 0.3:
                stack.append("kafka")
        if rng.random() < 0.4:
            stack.append("docker")
        out.append(Candidate(th, tau, direction, years, hint, sg, claimed, stack))
    return out


# ---------------------------------------------------------------- одна сессия и весь путь

def _block_gap(sess, res, direction: str) -> dict:
    """Доли верных в общем блоке и в блоке направления (для флага п. 7.4)."""
    by = {"common": [], "direction": []}
    for a in res.administered:
        if a.canary:
            continue
        it = sess.items.get(a.family_id)
        if it is None:
            continue
        by["common" if it.block == "common" else "direction"].append(float(np.mean(a.x)))
    c, d = by["common"], by["direction"]
    flag = bool(len(d) >= GAP_MIN_ITEMS and c and (np.mean(c) - np.mean(d)) >= GAP_SHARE)
    return {"n_common": len(c), "n_direction": len(d), "flag": flag}


def run_session(pool, cand: Candidate, truth, cfg: sim.AppConfig, counter, claimed: str, history: list[dict],
                rng: np.random.Generator, det: CanaryDetector, responder=None) -> tuple[dict, object]:
    d = cand.direction
    prev_sp = [h["subpool"] for h in history if h["subpool"] is not None]
    sp = choose_subpool(cfg.subpools, int(rng.integers(2 ** 31)), prev_sp)
    excl = set(stack_excluded(cand.stack))
    if claimed == "intern":  # как bank_engine.start/_rebuild: без ротации, только лёгкие семейства
        sp = None
        excl |= set(intern_exclusions(pool, d))
    last = history[0]["families"] if history else []
    person = Person(cand.theta, cand.tau, claimed)
    sess, res = sim.run_session(pool, d, responder or make_responder(person, truth), cfg, counter, claimed, sp, rng,
                                exclude_ext=sorted(last), exclude=sorted(excl))
    theta, se = float(res.theta), float(res.se)
    clean, canary, idx = _timed(sess, res)
    st = det.statistic(clean, canary)
    rescored = False
    if st.flagged:
        mask = det.suspicious_mask(clean, st.tau_clean)
        ex = {idx[i] for i in np.flatnonzero(mask)}
        if ex and len(ex) < len(idx):
            theta, se = (float(v) for v in sess.rescore(ex))
            rescored = True
    dec = decide_grade(theta, se, claimed)
    fams = [a.family_id for a in res.administered if not a.canary]
    history.insert(0, {"subpool": sp, "families": fams})
    rec = {"claimed": claimed, "theta": round(theta, 4), "se": round(se, 4), "n_items": int(res.n_items),
           "time_s": float(res.time_used_s), "subpool": sp, "stop": res.stop_reason, "n_ext": int(sess.n_ext),
           "families": fams, "confirmed": bool(dec.confirmed), "provisional": bool(dec.provisional),
           "p_claimed": dec.p_claimed, "rescored": rescored, "gap": _block_gap(sess, res, d)}
    return rec, dec


def run_path(pool, cand: Candidate, truth, cfg: sim.AppConfig, counter, history: list[dict], rng: np.random.Generator,
             det: CanaryDetector) -> dict:
    """Весь путь: тест на заявленный грейд → решение → принять доказанный уровень ниже или один тест ступенью ниже."""
    g = cand.claimed
    tests = []
    final, status, intern_proved = "none", "none", False
    for step in range(2):
        rec, dec = run_session(pool, cand, truth, cfg, counter, g, history, rng, det)
        tests.append(rec)
        if dec.confirmed:
            final, status = g, "confirmed"
            break
        if dec.provisional:
            lower, _ = accept_lower_allowed(None, g, False, dec.probabilities, provisional=True)
            final, status, intern_proved = "junior", "provisional", lower == "intern"
            break
        lower, _ = accept_lower_allowed(None, g, False, dec.probabilities)
        if lower:
            final, status = lower, "accepted_lower"
            break
        if step == 0 and g != "intern":
            g = GRADE_ORDER[GRADE_ORDER.index(g) - 1]
            continue
        break
    return {"grade": final, "level": LEVELS.index(final), "status": status, "intern_proved": intern_proved,
            "tests": tests, "families": sorted({f for t in tests for f in t["families"]})}


# ---------------------------------------------------------------- метрики

def kappa_w(a: np.ndarray, b: np.ndarray, k: int = len(LEVELS)) -> float:
    O = np.bincount(np.asarray(a) * k + np.asarray(b), minlength=k * k).reshape(k, k).astype(float)
    return sim.kappa_from_matrix(O)


def _boot(n: int, seed: int, b: int = N_BOOT) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(b, n))


def _ci(vals: np.ndarray) -> list[float]:
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return [round(float(lo), 3), round(float(hi), 3)]


def nearest_cut_distance(theta: np.ndarray) -> np.ndarray:
    cuts = np.array(cuts_tuple())
    return np.min(np.abs(np.asarray(theta)[:, None] - cuts[None, :]), axis=1)


def agreement(l1: np.ndarray, l2: np.ndarray, boot: np.ndarray | None = None) -> dict:
    n = len(l1)
    if n == 0:
        return {"n": 0}
    out = {"n": int(n), "exact": round(float(np.mean(l1 == l2)), 3),
           "within_1": round(float(np.mean(np.abs(l1 - l2) <= 1)), 3),
           "two_steps": round(float(np.mean(np.abs(l1 - l2) >= 2)), 3),
           "kappa_w": round(kappa_w(l1, l2), 3) if n > 1 else None}
    marg = np.bincount(np.r_[l1, l2], minlength=len(LEVELS)) / (2 * n)
    out["kappa_informative"] = bool(marg.max() < 0.9)  # почти все в одной ступени — κ не информативна (парадокс κ)
    if boot is not None and n > 1:
        ks = np.array([kappa_w(l1[i], l2[i]) for i in boot])
        ex = np.array([np.mean(l1[i] == l2[i]) for i in boot])
        out["kappa_w_ci"], out["exact_ci"] = _ci(ks), _ci(ex)
    return out


def overlap(f1: list[list[str]], f2: list[list[str]]) -> dict:
    """Доля семейств второй попытки, которые кандидат уже видел в первой (по кандидату, затем среднее)."""
    sh = np.array([len(set(b) & set(a)) / max(len(b), 1) for a, b in zip(f1, f2, strict=True)])
    return {"mean": round(float(sh.mean()), 3), "median": round(float(np.median(sh)), 3),
            "any_share": round(float(np.mean(sh > 0)), 3), "max": round(float(sh.max()), 3) if len(sh) else None}


def retest_block(cands: list[Candidate], r1: list[dict], r2: list[dict], seed: int, ci: bool = True) -> dict:
    l1, l2 = np.array([r["level"] for r in r1]), np.array([r["level"] for r in r2])
    t1, t2 = np.array([r["tests"][0]["theta"] for r in r1]), np.array([r["tests"][0]["theta"] for r in r2])
    s1, s2 = np.array([r["tests"][0]["se"] for r in r1]), np.array([r["tests"][0]["se"] for r in r2])
    th = np.array([c.theta for c in cands])
    boot = _boot(len(cands), seed) if ci and len(cands) > 1 else None
    out = {"path_grade": agreement(l1, l2, boot)}
    if len(cands) > 2:
        out["icc_theta"] = round(sim.icc_21(t1, t2), 3)
        out["r_theta"] = round(float(np.corrcoef(t1, t2)[0, 1]), 3)
        if boot is not None:
            out["icc_theta_ci"] = _ci(np.array([sim.icc_21(t1[i], t2[i]) for i in boot]))
        # точечный грейд по θ̂ первой сессии (5 ступеней) и потолок при той же погрешности
        p1 = np.array([LEVELS.index(point_grade(t)) for t in t1])
        p2 = np.array([LEVELS.index(point_grade(t)) for t in t2])
        out["point_grade"] = agreement(p1, p2)
        P1, P2 = sim._band_probs(th, s1, cuts_tuple()), sim._band_probs(th, s2, cuts_tuple())
        O = P1.T @ P2 / len(P1)
        idx = np.arange(O.shape[0])
        out["point_grade_ceiling"] = {"exact": round(float(np.trace(O)), 3),
                                      "within_1": round(float(O[np.abs(idx[:, None] - idx[None, :]) <= 1].sum()), 3),
                                      "kappa_w": round(sim.kappa_from_matrix(O), 3)}
    out["status_agreement"] = round(float(np.mean([a["status"] == b["status"] for a, b in zip(r1, r2, strict=True)])), 3)
    out["overlap_all"] = overlap([r["families"] for r in r1], [r["families"] for r in r2])
    out["overlap_first"] = overlap([r["tests"][0]["families"] for r in r1], [r["tests"][0]["families"] for r in r2])
    return out


def truth_block(cands: list[Candidate], runs: list[dict]) -> dict:
    """Итоговый грейд пути против истинного (точечный грейд по θ, шкала платформы)."""
    true = np.array([LEVELS.index(point_grade(c.theta)) for c in cands])
    got = np.array([r["level"] for r in runs])
    has = got > 0
    return {"n": len(cands), "exact": round(float(np.mean(true == got)), 3),
            "exact_with_category": round(float(np.mean((true == got)[has])), 3) if has.any() else None,
            "over_share": round(float(np.mean(got > true)), 3),  # присвоен грейд выше истинного
            "under_share": round(float(np.mean((got < true) & has)), 3),  # ниже истинного (категория есть)
            "no_category_share": round(float(np.mean(~has)), 3),
            "kappa_w_true": round(kappa_w(true, got), 3)}


def path_stats(runs: list[dict]) -> dict:
    tests = [t for r in runs for t in r["tests"]]
    st = Counter(r["status"] for r in runs)
    n = max(len(runs), 1)
    return {"status_share": {k: round(st.get(k, 0) / n, 3) for k in ("confirmed", "provisional", "accepted_lower", "none")},
            "sessions_per_path": round(len(tests) / n, 2),
            "mean_items_per_session": round(float(np.mean([t["n_items"] for t in tests])), 2),
            "mean_items_per_path": round(float(np.mean([sum(t["n_items"] for t in r["tests"]) for r in runs])), 2),
            "mean_time_min_per_path": round(float(np.mean([sum(t["time_s"] for t in r["tests"]) for r in runs]) / 60), 1),
            "extension_share": round(float(np.mean([t["n_ext"] > 0 for t in tests])), 3),
            "rescored_share": round(float(np.mean([t["rescored"] for t in tests])), 3),
            "provisional_intern_proved": int(sum(1 for r in runs if r["status"] == "provisional" and r["intern_proved"])),
            "block_gap_flag_share": round(float(np.mean([t["gap"]["flag"] for t in tests])), 3)}


# ---------------------------------------------------------------- флаг «общий блок сильнее направления» (п. 7.4)

def block_gap_check(pool, truth, direction: str, cfg: sim.AppConfig, k: dict, rng: np.random.Generator,
                    n: int = 150, shifts: tuple[float, ...] = (1.0, 3.0)) -> dict:
    """Как часто сработал бы флаг: у кандидатов, слабее в направлении, чем в общем блоке, на shift (θ направления =
    θ − shift), и у обычных. Заявлен Middle, θ общего блока ~ N(0,5; 0,5); решение — как в продукте."""
    det = CanaryDetector()
    rows = []
    for sh in (0.0, *shifts):
        flags, conf = [], []
        counter = ExposureControl(0.3, k=dict(k))
        for _ in range(n):
            th = float(rng.normal(0.5, 0.5))
            cand = Candidate(th, float(rng.normal(0, 0.3)), direction, 3.0, "middle", "middle", "middle", ["docker"])
            rc = make_responder(Person(th, cand.tau, "middle"), truth)
            rd = make_responder(Person(th - sh, cand.tau, "middle"), truth)

            def resp(item, r, _rc=rc, _rd=rd):
                return _rc(item, r) if item.block == "common" else _rd(item, r)
            rec, dec = run_session(pool, cand, truth, cfg, counter, "middle", [], rng, det, responder=resp)
            flags.append(rec["gap"]["flag"])
            conf.append(dec.confirmed)
        f, c = np.array(flags), np.array(conf)
        rows.append({"shift": sh, "n": n, "flag_share": round(float(f.mean()), 3),
                     "confirmed_share": round(float(c.mean()), 3),
                     "confirmed_flagged_share": round(float((f & c).sum() / max(c.sum(), 1)), 3)})
    return {"direction": direction, "claimed": "middle", "rule": {"gap": GAP_SHARE, "min_items": GAP_MIN_ITEMS},
            "rows": rows}


# ---------------------------------------------------------------- дискриминативность (D, r_pb) на симулированном пилоте

def author_truth(pool) -> dict[str, TrueFamily]:
    """Истина = авторские параметры заданий (без ошибки эксперта): D и r_pb отражают замысел автора."""
    return {it.family_id: TrueFamily(it.family_id, np.asarray(it.a, float), np.asarray(it.b, float),
                                     float(np.mean(it.sigma)), float(it.beta_time), float(it.time_limit_s))
            for it in pool}


def pilot_item_stats(pool, direction: str, truth: dict, rng: np.random.Generator, n: int = 1000) -> list[dict]:
    """Фиксированная форма из всех некарантинных семейств блоков common + direction, θ ~ N(0; 1), новый вариант
    каждому (разброс трудности вариантов σ). Балл семейства — доля верных частей."""
    items = [i for i in pool if not i.canary and i.block in ("common", direction)]
    th = rng.normal(size=n)
    X = np.zeros((n, len(items)))
    for j, it in enumerate(items):
        tf = truth[it.family_id]
        delta = rng.normal(0, tf.sigma, size=n)
        p = special.expit(tf.a[None, :] * (th[:, None] - (tf.mu[None, :] + delta[:, None])))
        X[:, j] = (rng.random(p.shape) < p).mean(1)
    total = X.sum(1)
    q = int(round(0.27 * n))
    out = []
    for j, it in enumerate(items):
        rest = total - X[:, j]
        order = np.argsort(rest, kind="stable")
        lo, hi = order[:q], order[-q:]
        x = X[:, j]
        r = float(np.corrcoef(x, rest)[0, 1]) if x.std() > 0 else 0.0
        out.append({"family_id": it.family_id, "block": it.block, "format": it.format, "grades": list(it.grades),
                    "p": round(float(x.mean()), 3), "D": round(float(x[hi].mean() - x[lo].mean()), 3),
                    "r_pb": round(r, 3), "a": round(float(np.mean(it.a)), 3), "b": round(float(np.mean(it.b)), 3)})
    return out


def panel_family_stats(bank_dir: Path | None) -> dict[str, dict]:
    """r_pb и флаги панели моделей по семействам (последняя панель, где семейство есть): независимая проверка."""
    if bank_dir is None:
        return {}
    out: dict[str, dict] = {}
    for panel in ("panel_20261005", "panel_20261005_ext1", "panel_20261005_ext2", "panel_20261006"):
        p = bank_dir / "calibration" / panel / "item_stats.csv"
        if not p.exists():
            continue
        rows: dict[str, list] = {}
        with p.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("canary") == "True":
                    continue
                try:
                    v = float(row.get("pbis") or "nan")
                except ValueError:
                    v = float("nan")
                rows.setdefault(row["family_id"], []).append((v, (row.get("flags") or "").strip()))
        for fid, vals in rows.items():
            pb = [v for v, _ in vals if np.isfinite(v)]
            flags = sorted({part.strip() for _, f in vals for part in f.split(";") if part.strip()})
            out[fid] = {"panel": panel, "r_pb_panel": round(float(np.mean(pb)), 3) if pb else None, "flags": flags}
    return out


def _bank_dir() -> Path | None:
    p = Path(os.environ.get("BANK_DIR", REPO.parent / "bank"))
    return p if (p / "calibration").exists() else None


def discrimination(pool, directions, rng: np.random.Generator, n: int) -> dict:
    truth = author_truth(pool)
    per: dict[str, list[dict]] = {}
    for d in directions:
        for r in pilot_item_stats(pool, d, truth, rng, n):
            per.setdefault(r["family_id"], []).append(r)
    panel = panel_family_stats(_bank_dir())
    fams = []
    for fid, rows in sorted(per.items()):
        base = dict(rows[0])
        base["D"] = round(float(np.mean([r["D"] for r in rows])), 3)
        base["r_pb"] = round(float(np.mean([r["r_pb"] for r in rows])), 3)
        base["p"] = round(float(np.mean([r["p"] for r in rows])), 3)
        reasons = []
        if base["p"] >= 0.9:
            reasons.append("слишком лёгкое для популяции")
        elif base["p"] <= 0.1:
            reasons.append("слишком трудное для популяции")
        if base["a"] < 0.8:
            reasons.append("низкая крутизна (a < 0,8)")
        base["weak_sim"] = bool(base["D"] < WEAK_D or base["r_pb"] < WEAK_RPB)
        base["reasons"] = reasons
        if fid in panel:
            base.update(panel[fid])
        base["weak_panel"] = bool(base.get("r_pb_panel") is not None and base["r_pb_panel"] < WEAK_PANEL)
        base["weak"] = base["weak_sim"] or base["weak_panel"]
        base["audit_rework"] = fid in BANK_AUDIT_REWORK
        fams.append(base)
    D = np.array([f["D"] for f in fams])
    R = np.array([f["r_pb"] for f in fams])
    pr = [(f["r_pb"], f["r_pb_panel"]) for f in fams if f.get("r_pb_panel") is not None]
    by_fmt: dict[str, list] = {}
    for f in fams:
        by_fmt.setdefault(f["format"], []).append(f)
    return {"n_pilot": n, "n_families": len(fams),
            "criteria": {"weak_D": WEAK_D, "weak_r_pb": WEAK_RPB, "weak_r_pb_panel": WEAK_PANEL},
            "summary": {"D_mean": round(float(D.mean()), 3), "D_median": round(float(np.median(D)), 3),
                        "r_pb_mean": round(float(R.mean()), 3), "r_pb_median": round(float(np.median(R)), 3),
                        "share_D_ge_03": round(float(np.mean(D >= 0.3)), 3),
                        "share_D_02_03": round(float(np.mean((D >= 0.2) & (D < 0.3))), 3),
                        "share_D_lt_02": round(float(np.mean(D < 0.2)), 3),
                        "share_r_pb_gt_02": round(float(np.mean(R > 0.2)), 3),
                        "n_weak": int(sum(f["weak"] for f in fams)),
                        "n_weak_sim": int(sum(f["weak_sim"] for f in fams)),
                        "panel_n": len(pr),
                        "panel_corr": (round(float(np.corrcoef([a for a, _ in pr], [b for _, b in pr])[0, 1]), 3)
                                       if len(pr) > 2 else None),
                        "panel_weak": int(sum(f["weak_panel"] for f in fams)),
                        "audit_rework_n": int(sum(f["audit_rework"] for f in fams)),
                        "audit_rework_and_weak": sorted(f["family_id"] for f in fams if f["audit_rework"] and f["weak"]),
                        "audit_rework_panel_r_pb_mean": (round(float(np.mean(
                            [f["r_pb_panel"] for f in fams if f["audit_rework"] and f.get("r_pb_panel") is not None])), 3)
                            if any(f["audit_rework"] and f.get("r_pb_panel") is not None for f in fams) else None)},
            "by_format": {k: {"n": len(v), "D_mean": round(float(np.mean([f["D"] for f in v])), 3),
                              "r_pb_mean": round(float(np.mean([f["r_pb"] for f in v])), 3)} for k, v in sorted(by_fmt.items())},
            "weak": sorted([f for f in fams if f["weak"]], key=lambda f: (f.get("r_pb_panel") is None, f.get("r_pb_panel") or 0, f["D"])),
            "families": fams}


# ---------------------------------------------------------------- прогон

def _rng(*parts: int) -> np.random.Generator:
    return np.random.default_rng([SEED, 8, *parts])


def direction_run(d: str, i: int, n: int, cfg: sim.AppConfig, pool, k: dict) -> tuple[list[Candidate], list[dict], list[dict]]:
    rng0 = _rng(i, 0)
    truth = make_truth(pool, rng0, misspec=0.5)
    cands = make_candidates(n, d, rng0)
    counter = ExposureControl(0.3, k=dict(k))
    det = CanaryDetector()
    rng = _rng(i, 1)
    r1, r2 = [], []
    for c in cands:
        hist: list[dict] = []
        r1.append(run_path(pool, c, truth, cfg, counter, hist, rng, det))
        r2.append(run_path(pool, c, truth, cfg, counter, hist, rng, det))
    return cands, r1, r2


def splits(cands, r1, r2, seed: int) -> dict:
    th = np.array([c.theta for c in cands])
    dist = nearest_cut_distance(th)
    sure = np.array([a["status"] in ("confirmed", "accepted_lower") and b["status"] in ("confirmed", "accepted_lower")
                     for a, b in zip(r1, r2, strict=True)])

    def sub(mask):
        idx = np.flatnonzero(mask)
        return {"share": round(float(mask.mean()), 3),
                **retest_block([cands[j] for j in idx], [r1[j] for j in idx], [r2[j] for j in idx], seed, ci=True)["path_grade"]}
    # Граница решения сдвинута вверх от номинального порога: подтверждение и «уровень ниже» требуют P ≥ 0,8,
    # то есть θ̂ ≥ порог + z(0,8) · SE. Расстояние до этой эффективной границы — честный разрез «уверенные / у порога».
    se_med = float(np.median([r["tests"][0]["se"] for r in r1]))
    shift = float(special.ndtri(0.8)) * se_med
    dist_eff = nearest_cut_distance(th - shift)
    return {"far_from_cut": sub(dist >= BORDER), "near_cut": sub(dist < BORDER),
            "far_from_boundary": sub(dist_eff >= BORDER), "near_boundary": sub(dist_eff < BORDER),
            "boundary_shift": round(shift, 3),
            "decided_both": sub(sure), "undecided_any": sub(~sure)}


def run(n: int = 500, quick: bool = False, write: bool = True, pilot_n: int = 1000) -> dict:
    t0 = time.time()
    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    k_all = (exposure_table() or {}).get("k", {})
    dirs = sim.DIRECTIONS[:2] if quick else sim.DIRECTIONS
    if quick:
        n, pilot_n = min(n, 60), min(pilot_n, 300)
    all_c, all_1, all_2 = [], [], []
    by_dir = {}
    for i, d in enumerate(dirs):
        t = time.time()
        c, r1, r2 = direction_run(d, i, n, cfg, pool, k_all.get(d, {}))
        all_c += c
        all_1 += r1
        all_2 += r2
        rb = retest_block(c, r1, r2, SEED + i)
        by_dir[d] = {**rb, "truth": truth_block(c, r1), "path": path_stats(r1 + r2)}
        print(f"  {d}: κw {rb['path_grade']['kappa_w']} {rb['path_grade'].get('kappa_w_ci')}, точно "
              f"{rb['path_grade']['exact']}, ±1 {rb['path_grade']['within_1']}, ICC {rb.get('icc_theta')}, повтор "
              f"семейств {rb['overlap_all']['mean']} ({time.time() - t:.0f} с)", flush=True)
    total = retest_block(all_c, all_1, all_2, SEED + 99)
    claimed = Counter(c.claimed for c in all_c)
    by_claim = {}
    for g in GRADE_ORDER:
        idx = [j for j, c in enumerate(all_c) if c.claimed == g]
        if len(idx) > 2:
            by_claim[g] = retest_block([all_c[j] for j in idx], [all_1[j] for j in idx], [all_2[j] for j in idx],
                                       SEED + 50 + GRADE_ORDER.index(g))["path_grade"]
    k0 = k_all.get(dirs[0], {})
    gap = block_gap_check(pool, make_truth(pool, _rng(0, 7), misspec=0.5), dirs[0], cfg, k0, _rng(0, 8),
                          n=40 if quick else 150)
    disc = discrimination(pool, dirs, _rng(0, 9), pilot_n)
    cfg_d = {k: v for k, v in asdict(cfg).items()}
    world_cfg = {"app": cfg_d, "n_per_direction": n, "directions": list(dirs), "p_follow_hint": P_FOLLOW_HINT,
                 "self_sd": SELF_SD, "misspec": 0.5, "border": BORDER, "pilot_n": pilot_n,
                 "cuts": dict(GRADE_CUTS), "n_families": len(pool)}
    rep = {
        "signature": signature(seed=SEED, config=world_cfg, n=len(all_c),
                               world=f"симуляция теста: {len(dirs)} направлений × {n} кандидатов, семейств в банке: {len(pool)}",
                               command="make path-retest" if not quick else "python -m app.modules.validation.path_retest --quick"),
        "quick": quick, "n_per_direction": n, "directions": list(dirs), "config": world_cfg,
        "claimed": {g: int(claimed.get(g, 0)) for g in GRADE_ORDER},
        "true_grades": {g: int(sum(1 for c in all_c if point_grade(c.theta) == g)) for g in LEVELS},
        "total": {**total, "truth": truth_block(all_c, all_1), "path": path_stats(all_1 + all_2),
                  "splits": splits(all_c, all_1, all_2, SEED + 77)},
        "by_direction": by_dir, "by_claimed": by_claim,
        "transitions": _transitions(all_1, all_2),
        "block_gap": gap, "discrimination": disc,
        "procedure": PROCEDURE, "caveat": CAVEAT,
        "other_reference": OTHER_REFERENCE,
    }
    rep["seconds"] = round(time.time() - t0, 1)
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.parent.mkdir(parents=True, exist_ok=True)
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {OUT.relative_to(REPO)}, {DOCS_MD.relative_to(REPO)} ({rep['seconds']} с)", flush=True)
    return rep


def _transitions(r1: list[dict], r2: list[dict]) -> list[list[int]]:
    k = len(LEVELS)
    O = np.zeros((k, k), dtype=int)
    for a, b in zip(r1, r2, strict=True):
        O[a["level"], b["level"]] += 1
    return O.tolist()


PROCEDURE = [
    "Опрос: стаж (θ = 0 → 1,5 года, θ = 1 → 4,5 года, шум 1 год) → подсказка грейда по стажу (как в продукте); "
    "самооценка — θ + N(0; 0,6). Заявленный грейд — подсказка (в половине случаев) или самооценка; ниже порога Стажёра — Стажёр.",
    "Стек опроса фильтрует семейства (Go, Java, Django, Kafka, Docker — только тем, у кого тег есть).",
    "Адаптивный тест платформы на банке: классификационная остановка, дотестирование у порога, контроль частоты, "
    "ротация субпулов по истории сессий; тест Стажёра — только лёгкие семейства, без ротации.",
    "Детектор предзнания и пересчёт θ; решение: подтверждён при P ≥ 0,8, «Junior (предварительно)» при P от 0,10.",
    "Не подтверждён: принять доказанный уровень ниже без нового теста (P ≥ 0,8), иначе один тест ступенью ниже, "
    "иначе без категории.",
    "Повтор — вся процедура ещё раз: другой субпул, новые варианты, семейства прошлой сессии не в дотестировании.",
]
CAVEAT = ("Синтетика: истинные параметры заданий = предкалибровка + ошибка эксперта σ = 0,5, люди — модель ответов "
          "2PL; проверяется механика всей процедуры, а не качество заданий на людях. «Предварительно» считается "
          "ступенью Junior. Дискриминативность — на симулированном пилоте с авторскими параметрами: она показывает "
          "замысел автора, а не поведение людей; r_pb панели моделей — независимая проверка на ответах моделей, "
          "шкала моделей не равна шкале людей.")
OTHER_REFERENCE = {
    "source": "внешний репозиторий, docs/testing.md (05.10.2026)",
    "kappa_w": 0.866, "exact": 0.759, "within_1": 0.998, "r_theta_parallel": 0.874, "borderline_exact": 0.663,
    "far_exact": 0.826, "length": 20, "confirm_rule": "P ≥ 0,5", "param_error": "b + N(0; 0,35), a · LogN(0; 0,2)",
    "n": 1600, "levels": 4, "ci": None, "icc": None,
}


# ---------------------------------------------------------------- документация

def _f(v, d: int = 3) -> str:
    if v is None:
        return "—"
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def _pc(v) -> str:
    return "—" if v is None else f"{round(100 * v)} %"


def _ci_s(ci) -> str:
    return "" if not ci else f" [{_f(ci[0])}; {_f(ci[1])}]"


def _pci(ci) -> str:
    return "" if not ci else f" [{round(100 * ci[0])}; {round(100 * ci[1])} %]"


def markdown(rep: dict) -> str:
    t = rep["total"]
    pg, sig = t["path_grade"], rep["signature"]
    cr = rep["other_reference"]
    L = [
        "# Test–retest всего пути кандидата и дискриминативность семейств",
        "",
        f"Подпись мира: {sig['world']}; seed {sig['seed']}, конфигурация `{sig['config_hash']}`, коммит `{sig['commit']}`, "
        f"банк `{sig['bank']}`. Пересчёт: `{sig['command']}` ({_f(rep['seconds'], 0)} с).",
        "",
        f"> {rep['caveat']}",
        "",
        "## Процедура",
        "",
        *[f"{i + 1}. {s}" for i, s in enumerate(rep["procedure"])],
        "",
        "## Итог",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| Кандидатов (пар попыток) | {pg['n']} |",
        f"| Итоговый грейд совпал точно | {_pc(pg['exact'])}{_pci(pg.get('exact_ci'))} |",
        f"| В пределах ±1 ступени | {_pc(pg['within_1'])} |",
        f"| Расхождение на 2 ступени и больше | {_pc(pg['two_steps'])} |",
        f"| Квадратично взвешенная κ (5 ступеней) | {_f(pg['kappa_w'])}{_ci_s(pg.get('kappa_w_ci'))} |",
        f"| ICC(2,1) по θ̂ первой сессии | {_f(t.get('icc_theta'))}{_ci_s(t.get('icc_theta_ci'))} |",
        f"| Совпал статус (подтверждён / предварительно / принят ниже / без категории) | {_pc(t['status_agreement'])} |",
        f"| Доля семейств второй попытки, уже виденных в первой | {_pc(t['overlap_all']['mean'])} (хотя бы одно — у {_pc(t['overlap_all']['any_share'])}) |",
        f"| То же, только тест на заявленный грейд | {_pc(t['overlap_first']['mean'])} |",
        f"| Точечный грейд по θ̂: κ / потолок при той же погрешности | {_f(t.get('point_grade', {}).get('kappa_w'))} / {_f(t.get('point_grade_ceiling', {}).get('kappa_w'))} |",
        "",
        f"Для сравнения (другой мир, другая процедура): Прототип А — κw {_f(cr['kappa_w'])}, точно {_pc(cr['exact'])}, ±1 "
        f"{_pc(cr['within_1'])}; 4 ступени, 20 заданий, подтверждение при {cr['confirm_rule']}, ошибка параметров "
        f"{cr['param_error']}, без ДИ и ICC ({cr['source']}). У нас — 5 ступеней (со Стажёром), подтверждение при P ≥ 0,8, "
        "ошибка параметров σ = 0,5: числа не сравнимы напрямую, сравнимы только методы внутри одного мира.",
        "",
        "## Уверенные и у порога",
        "",
        "| Группа | Доля | Точно | ±1 | κw [95 % ДИ] |",
        "|---|---|---|---|---|",
    ]
    names = {"far_from_boundary": f"Истинный θ дальше 0,25 от границы решения (порог + {_f(t['splits']['boundary_shift'], 2)})",
             "near_boundary": "Истинный θ ближе 0,25 к границе решения",
             "far_from_cut": "Истинный θ дальше 0,25 от номинального порога", "near_cut": "Истинный θ ближе 0,25 к номинальному порогу",
             "decided_both": "Обе попытки — решение принято (подтверждён или принят ниже)",
             "undecided_any": "Хотя бы в одной — «предварительно» или без категории"}
    for key, title in names.items():
        s = t["splits"][key]
        L.append(f"| {title} | {_pc(s['share'])} | {_pc(s.get('exact'))} | {_pc(s.get('within_1'))} | "
                 f"{_f(s.get('kappa_w'))}{_ci_s(s.get('kappa_w_ci'))} |")
    L += ["", f"Граница решения выше номинального порога на z(0,8) · SE ≈ {_f(t['splits']['boundary_shift'], 2)}: подтверждение "
          "и «уровень ниже» требуют P ≥ 0,8. Поэтому расхождения сосредоточены у этой границы, а разрез по номинальному "
          "порогу их почти не разделяет.", "", "## По направлениям", "", "| Направление | n | Точно | ±1 | κw [95 % ДИ] | ICC θ | Повтор семейств | Грейд = истинный |",
          "|---|---|---|---|---|---|---|---|"]
    for d, b in rep["by_direction"].items():
        p = b["path_grade"]
        L.append(f"| {d} | {p['n']} | {_pc(p['exact'])} | {_pc(p['within_1'])} | {_f(p['kappa_w'])}{_ci_s(p.get('kappa_w_ci'))} | "
                 f"{_f(b.get('icc_theta'))} | {_pc(b['overlap_all']['mean'])} | {_pc(b['truth']['exact'])} |")
    L += ["", "## По заявленному грейду", "", "| Заявлен | n | Точно | ±1 | κw [95 % ДИ] |", "|---|---|---|---|---|"]
    for g, p in rep["by_claimed"].items():
        kw = (f"{_f(p['kappa_w'])}{_ci_s(p.get('kappa_w_ci'))}" if p.get("kappa_informative", True)
              else "— (почти все в одной ступени, κ не информативна)")
        L.append(f"| {LEVEL_RU[g]} | {p['n']} | {_pc(p['exact'])} | {_pc(p['within_1'])} | {kw} |")
    tr, ps = t["truth"], t["path"]
    L += ["", "## Путь и точность к истине (первая попытка)", "",
          f"- Итоговый грейд = истинный: {_pc(tr['exact'])}; среди получивших категорию — {_pc(tr['exact_with_category'])}; "
          f"κw с истиной {_f(tr['kappa_w_true'])}.",
          f"- Грейд выше истинного: {_pc(tr['over_share'])}; ниже истинного (категория есть): {_pc(tr['under_share'])}; "
          f"без категории: {_pc(tr['no_category_share'])}.",
          f"- Статусы (обе попытки): подтверждён {_pc(ps['status_share']['confirmed'])}, предварительно "
          f"{_pc(ps['status_share']['provisional'])}, принят уровень ниже {_pc(ps['status_share']['accepted_lower'])}, "
          f"без категории {_pc(ps['status_share']['none'])}.",
          f"- Сессий на путь {_f(ps['sessions_per_path'], 2)}, заданий на сессию {_f(ps['mean_items_per_session'], 1)}, "
          f"на путь {_f(ps['mean_items_per_path'], 1)}, минут на путь {_f(ps['mean_time_min_per_path'], 0)}; "
          f"дотестирование у порога — в {_pc(ps['extension_share'])} сессий.",
          f"- «Junior (предварительно)», у которых доказан Стажёр (путь «принять Стажёра»): {ps['provisional_intern_proved']}.",
          ""]
    bg = rep["block_gap"]
    L += ["## Флаг «общий блок сильнее направления» (консилиум 07.10, п. 7.4)", "",
          f"Проверка правила: доля верных в блоке направления ниже, чем в общем, на ≥ {_f(GAP_SHARE, 1)} при ≥ "
          f"{GAP_MIN_ITEMS} заданиях направления. Заявлен Middle, θ общего блока ~ N(0,5; 0,5), по "
          f"{bg['rows'][0]['n']} кандидатов; θ в направлении ниже на сдвиг.", "",
          "| Сдвиг θ в направлении | Флаг сработал | Middle подтверждён | Из подтверждённых с флагом |", "|---|---|---|---|"]
    for r in bg["rows"]:
        L.append(f"| {_f(r['shift'], 1)} | {_pc(r['flag_share'])} | {_pc(r['confirmed_share'])} | {_pc(r['confirmed_flagged_share'])} |")
    L += ["", "Флаг по доле верных срабатывает и у обычных кандидатов (сдвиг 0): адаптивный тест даёт блокам задания "
          "разной трудности, поэтому сырая доля верных — грубый сигнал. В объяснение результата он не добавлен; "
          "решение по грейду не меняется (консилиум: страж направления — после 11.10 с отдельной симуляцией).", ""]
    ds = rep["discrimination"]
    sm = ds["summary"]
    L += ["## Дискриминативность семейств (симулированный пилот)", "",
          f"Пилот: {ds['n_pilot']} человек на направление, θ ~ N(0; 1), каждому — все семейства общего блока и блока "
          "направления, новый вариант каждому; авторские параметры. D — доля верных в верхних 27 % минус в нижних 27 % "
          "по сумме остальных заданий; r_pb — корреляция «задание — сумма остальных».",
          "",
          f"- Семейств: {ds['n_families']}; D: среднее {_f(sm['D_mean'])}, медиана {_f(sm['D_median'])}; доли D ≥ 0,3 / "
          f"0,2–0,3 / < 0,2: {_pc(sm['share_D_ge_03'])} / {_pc(sm['share_D_02_03'])} / {_pc(sm['share_D_lt_02'])}.",
          f"- r_pb: среднее {_f(sm['r_pb_mean'])}, медиана {_f(sm['r_pb_median'])}; r_pb > 0,2 у {_pc(sm['share_r_pb_gt_02'])}.",
          f"- Слабых на симуляции (D < {_f(WEAK_D, 1)} или r_pb < {_f(WEAK_RPB, 1)}): {sm['n_weak_sim']} — авторские "
          "параметры по замыслу различают; это проверка замысла, не людей.",
          f"- Панель моделей (независимая проверка на ответах моделей): r_pb есть у {sm['panel_n']} семейств, "
          f"корреляция с симуляцией {_f(sm['panel_corr'])}; r_pb панели < {_f(WEAK_PANEL, 2)} — у {sm['panel_weak']}. "
          "Низкая связь авторской и модельной дискриминативности — довод за калибровку на людях после хакатона.",
          "",
          f"- Аудит банка 08.10 отдал на переделку {sm['audit_rework_n']} семейств (подсказки длиной верного варианта, "
          f"дистракторы); из них слабые здесь: {', '.join(sm['audit_rework_and_weak']) or 'нет'}; средняя r_pb панели у них "
          f"{_f(sm['audit_rework_panel_r_pb_mean'])}. Сигналы разные: подсказка в форме облегчает задание, а не обязательно "
          "снижает различение.",
          "",
          "Слабые (по симуляции или по панели моделей):",
          "",
          "| Семейство | Формат | p | D | r_pb | a | b | r_pb панели | Причина / флаги панели |",
          "|---|---|---|---|---|---|---|---|---|"]
    for f in ds["weak"]:
        why = "; ".join(f["reasons"] + list(f.get("flags") or []) + (["аудит 08.10: на переделку"] if f["audit_rework"] else [])) or "—"
        L.append(f"| {f['family_id']} | {f['format']} | {_f(f['p'], 2)} | {_f(f['D'], 2)} | {_f(f['r_pb'], 2)} | "
                 f"{_f(f['a'], 2)} | {_f(f['b'], 2)} | {_f(f.get('r_pb_panel'), 2)} | {why} |")
    L += ["", "Полные данные: `backend/app/modules/validation/data/path_retest.json` (по каждому семейству — `discrimination.families`).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Test–retest всего пути и дискриминативность → data/path_retest.json")
    ap.add_argument("--n", type=int, default=500, help="кандидатов на направление")
    ap.add_argument("--pilot", type=int, default=1000, help="человек в симулированном пилоте на направление")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    rep = run(a.n, a.quick, not a.no_write, a.pilot)
    pg = rep["total"]["path_grade"]
    print(f"итог: κw {pg['kappa_w']} {pg.get('kappa_w_ci')}, точно {pg['exact']}, ±1 {pg['within_1']}, "
          f"ICC {rep['total'].get('icc_theta')} {rep['total'].get('icc_theta_ci')}, слабых семейств "
          f"{rep['discrimination']['summary']['n_weak']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
