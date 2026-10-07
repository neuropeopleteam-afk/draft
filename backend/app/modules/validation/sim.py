"""Симуляция адаптивного теста в конфигурации платформы (строительные блоки — assessment_bank.simulation).

Отличие от симуляции банка: сессия — ``AppCATSession`` (лимит форматов), контроль частоты показа
Sympson — Hetter с K_f из ``exposure_k.json``, ротация 2 субпулов, длина, время и дотестирование у порога —
из настроек платформы (тот же класс сессии и те же правила, что в ``bank_engine``).
Всё синтетическое: истинные параметры заданий = предкалибровка + систематическая ошибка эксперта
(σ = 0,5 по трудности семейства), популяция θ ~ N(0, 1). Проверяется механика, а не качество заданий на людях.

Политики для сравнения «до/после» (одинаковые seed):
* ``LEGACY_SIM`` — как считалось на /validation до 06.10: без дотестирования (в продукте оно было);
* ``LEGACY`` — механика продукта до 06.10: остановка по SE, выбор по информации в θ̂, при |θ̂ − порог
  заявленного грейда| < SE ещё 3 задания из всего банка (``LegacyExtSession``);
* текущая (``app_config_from_settings``) — классификационная остановка, выбор у неопределённого порога,
  дотестирование до точности у ближайшего порога (см. assessment_bank/psychometrics/cat.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from scipy import stats

from assessment_bank import load_specs
from assessment_bank.psychometrics import (CanaryDetector, CATConfig, ExposureControl, GradeScale, decide,
                                           estimate_theta, pool_from_specs)
from assessment_bank.simulation import (LeakModel, Person, _apply_detector, _grade_idx, make_population,
                                        make_responder, make_truth, quadratic_kappa, summarize)

from app.modules.assessment.exposure import AppCATSession
from app.modules.assessment.grades import cuts_tuple, start_theta

DIRECTIONS = ("backend", "frontend", "data_ml", "qa", "security")


@dataclass
class AppConfig:
    """Конфигурация теста платформы (значения по умолчанию = app.core.config)."""

    min_items: int = 8
    max_items: int = 16
    se_target: float = 0.35
    max_minutes: int = 60
    subpools: int = 2
    exposure: bool = True
    max_per_format: dict = field(default_factory=lambda: {"open_book_3step": 2, "open_answer": 1})
    # классификация по грейду и дотестирование у порога (значения по умолчанию = app.core.config)
    stop_rule: str = "classification"
    classify_z: float = 1.28
    select_at: str = "cut"
    time_weight: float = 0.0
    ext_items: int = 6
    ext_minutes: int = 20
    ext_own_first: bool = True
    legacy_ext: int = 0            # > 0 — механика до 06.10 (LegacyExtSession), ext_items не используется
    claim_prior: bool = False      # абляция: EAP с априорным распределением по заявленному грейду
    rotation: str = "subpool"      # subpool — параллельные формы-субпулы; exclude_last — весь банк без семейств прошлой попытки
    cuts: tuple = field(default_factory=cuts_tuple)              # пороги грейдов платформы (со Стажёром), как в bank_engine
    start_theta: dict = field(default_factory=start_theta)       # стартовая θ по заявленному грейду

    def cat(self) -> CATConfig:
        return CATConfig(min_items=self.min_items, max_items=self.max_items, se_target=self.se_target,
                         max_time_s=self.max_minutes * 60.0, exposure="sympson_hetter" if self.exposure else "none",
                         cuts=tuple(self.cuts), start_theta=dict(self.start_theta),
                         stop_rule=self.stop_rule, classify_z=self.classify_z, select_at=self.select_at,
                         time_weight=self.time_weight, ext_items=0 if self.legacy_ext else self.ext_items,
                         ext_time_s=self.ext_minutes * 60.0, ext_own_first=self.ext_own_first)


BASELINE_DAY2 = AppConfig(max_items=20, max_minutes=90, subpools=1, exposure=False, max_per_format={},
                          stop_rule="se", select_at="theta", ext_items=0, ext_own_first=False)
# Механика до 06.10: в продукте (дотестирование 3 заданиями у порога заявленного грейда) и как её считала симуляция
LEGACY = AppConfig(stop_rule="se", select_at="theta", ext_items=0, legacy_ext=3, ext_own_first=False)
LEGACY_SIM = AppConfig(stop_rule="se", select_at="theta", ext_items=0, ext_own_first=False)


def app_config_from_settings() -> AppConfig:
    from app.core.config import get_settings

    s = get_settings()
    return AppConfig(min_items=s.assessment_min_items, max_items=s.assessment_max_items,
                     se_target=s.assessment_se_target, max_minutes=s.assessment_max_minutes,
                     subpools=max(1, s.assessment_subpools), exposure=s.assessment_exposure == "sympson_hetter",
                     max_per_format={"open_book_3step": s.assessment_max_open_book,
                                     "open_answer": s.assessment_max_open_answer},
                     stop_rule=s.assessment_stop_rule, classify_z=s.assessment_classify_z,
                     select_at=s.assessment_select_at, ext_items=s.assessment_extension_items,
                     ext_minutes=s.assessment_extension_minutes, ext_own_first=s.assessment_extension_own_first)


def make_pool(n_subpools: int, params: dict | None = None):
    return pool_from_specs(load_specs().values(), params=params, n_subpools=max(1, n_subpools))


class LegacyExtSession(AppCATSession):
    """Механика продукта до 06.10 (прежний ``bank_engine._select``): после основной части, если причина остановки —
    не время и |θ̂ − порог заявленного грейда| < SE, ещё ``legacy_n`` заданий (не меньше 3) из всего банка
    направления — без учёта карантина субпулов и семейств прошлой попытки, — выбранных по информации в этом
    пороге; внутри дотестирования правила остановки нет."""

    def __init__(self, *args, legacy_n: int = 3, **kwargs):
        super().__init__(*args, **kwargs)
        self.legacy_n = legacy_n
        self._cut = GradeScale().cuts[self.claimed_grade]
        self._all_scored = [i for i in self.items.values() if not i.canary]
        self._lx: tuple[int, int] | None = None

    @property
    def n_ext(self) -> int:
        return 0 if self._lx is None else self.n_scored - self._lx[0]

    def next_item(self):
        if self._lx is None:
            nxt = super().next_item()
            if nxt is not None:
                return nxt
            if not (self.legacy_n and self.stop_reason != "time" and abs(self.theta - self._cut) < self.se):
                return None
            start = self.n_scored
            self.cfg = replace(self.cfg, min_items=0, max_items=start + self.legacy_n, se_target=-1.0,
                               max_time_s=self.cfg.max_time_s + 1800.0)
            self.scored_pool = self._all_scored
            n = min(self.legacy_n, len(self._candidates()))
            if n < 3:
                return None
            self.cfg = replace(self.cfg, max_items=start + n)
            self._lx = (start, n)
        start, n = self._lx
        if self.n_scored >= start + n:
            self.stop_reason = "extension_done"
            return None
        th = self.theta
        self.theta = self._cut  # дотестирование: информация в пороге, а не в текущей θ̂
        try:
            nxt = super().next_item()
        finally:
            self.theta = th
        if nxt is None:
            self.stop_reason = "extension_" + (self.stop_reason or "stopped")
        return nxt


def claim_priors(n: int = 20000, seed: int = 7) -> dict[str, tuple[float, float]]:
    """Эмпирическое априорное распределение θ при заявленном грейде (по синтетической популяции —
    самый выгодный для метода случай: модель заявления известна точно)."""
    rng = np.random.default_rng(seed)
    ppl = make_population(n, rng)
    out = {}
    for g in ("junior", "middle", "senior"):
        th = np.array([p.theta for p in ppl if p.claimed == g])
        out[g] = (float(th.mean()), float(th.std()))
    return out


class ClaimPriorSession(AppCATSession):
    """Абляция: θ — EAP с априорным N(μ_g, σ_g) по заявленному грейду g вместо N(0, 1)."""

    PRIORS: dict[str, tuple[float, float]] = {}

    def _prior(self) -> tuple[float, float]:
        if not ClaimPriorSession.PRIORS:
            ClaimPriorSession.PRIORS = claim_priors()
        return ClaimPriorSession.PRIORS.get(self.claimed_grade, (0.0, 1.0))

    def _update_theta(self) -> None:
        x, a, b = self._scored_arrays()
        m, sd = self._prior()
        est = estimate_theta(x, a, b, method=self.cfg.estimator, prior_mean=m, prior_sd=sd)
        self.theta, self.se = est.theta, est.se
        self.trace.append((self.theta, self.se))

    def rescore(self, exclude: set[int]) -> tuple[float, float]:
        x, a, b = self._scored_arrays(exclude)
        m, sd = self._prior()
        est = estimate_theta(x, a, b, method=self.cfg.estimator, prior_mean=m, prior_sd=sd)
        return est.theta, est.se


def run_session(pool, direction, responder, cfg: AppConfig, exposure: ExposureControl | None, claimed: str,
                subpool: int | None, rng: np.random.Generator, *, exclude_ext=(), blocked_subpools=(), exclude=()
                ) -> tuple[AppCATSession, object]:
    # ExposureControl передаётся всегда (счётчик частоты показа); отбор Sympson — Hetter включает cfg.cat().exposure
    kw = {"max_per_format": cfg.max_per_format}
    if cfg.legacy_ext:
        cls, kw["legacy_n"] = LegacyExtSession, cfg.legacy_ext
    else:
        cls = ClaimPriorSession if cfg.claim_prior else AppCATSession
        kw.update(exclude_ext=exclude_ext, blocked_subpools=blocked_subpools, exclude=exclude)
        if cfg.rotation == "exclude_last":
            subpool = None
    sess = cls(pool, direction, cfg.cat(), exposure, claimed, subpool, rng, **kw)
    while True:
        item = sess.next_item()
        if item is None:
            break
        x, log_t = responder(item, rng)
        sess.record(item, x, log_t, time_s=float(np.exp(log_t)) if log_t is not None else None)
    return sess, sess.result()


def subpool_leak_responder(person: Person, truth, leak: LeakModel, leaked_subpools: set[int]):
    """Утечка только заданий из leaked_subpools (и опубликованных канареек): субпул «слили» и вывели в карантин."""
    leaky, clean = make_responder(person, truth, leak), make_responder(person, truth, None)

    def respond(item, rng):
        return leaky(item, rng) if item.canary or item.subpool in leaked_subpools else clean(item, rng)
    return respond


def run_population(pool, truth, people: list[Person], direction: str, cfg: AppConfig, rng, *,
                   k: dict | None = None, r_max: float = 0.3, subpools: list[int | None] | None = None,
                   leak: LeakModel | None = None, detector: CanaryDetector | None = None,
                   counter: ExposureControl | None = None, exclude: list[set] | None = None,
                   blocked_subpools: set[int] | None = None, leaked_subpools: set[int] | None = None) -> list[dict]:
    """Прогон популяции. counter — общий ExposureControl для подсчёта частоты показа по сессиям;
    exclude — семейства прошлой попытки каждого кандидата (в дотестирование не попадают)."""
    out = []
    for i, p in enumerate(people):
        if subpools is not None:
            sp = subpools[i]
        else:
            sp = int(rng.integers(cfg.subpools)) if cfg.subpools > 1 else None
        expo = counter if counter is not None else (ExposureControl(r_max, k=k) if cfg.exposure else None)
        if counter is not None:
            counter.k = dict(k or {})
        responder = (subpool_leak_responder(p, truth, leak, leaked_subpools) if leak is not None and leaked_subpools
                     else make_responder(p, truth, leak))
        prev = exclude[i] if exclude else ()
        sess, res = run_session(pool, direction, responder, cfg, expo, p.claimed, sp, rng,
                                exclude_ext=prev, blocked_subpools=blocked_subpools or (),
                                exclude=prev if cfg.rotation == "exclude_last" else ())
        d = decide(res.theta, res.se, p.claimed)
        rec = {"theta": res.theta, "se": res.se, "n_items": res.n_items, "time_s": res.time_used_s,
               "confirmed": d.confirmed, "stop": res.stop_reason, "subpool": sp, "n_ext": sess.n_ext,
               "families": [a.family_id for a in res.administered if not a.canary],
               "n_ob3": sum(1 for a in res.administered if not a.canary and sess._fmt.get(a.family_id) == "open_book_3step")}
        if detector is not None:
            rec.update(_apply_detector(sess, res, p, detector))
        out.append(rec)
    return out


class FixedFormSession(AppCATSession):
    """Фиксированная форма: одни и те же задания (и варианты) всем кандидатам заявленного грейда, без адаптивного
    отбора, контроля частоты, ротации и канареек; θ оценивается так же (EAP)."""

    def __init__(self, pool, direction, cfg: CATConfig, form: list, claimed: str, rng):
        super().__init__(pool, direction, cfg, None, claimed, None, rng, max_per_format={})
        self.form = list(form)

    def next_item(self):
        free = [i for i in self.form if i.family_id not in self.used]
        if not free:
            self.stop_reason = "fixed_form"
            return None
        return free[0]


def fixed_forms(pool, truth, direction: str, cfg: AppConfig, rng) -> dict[str, list]:
    """Форма для каждого заявленного грейда — задания, которые адаптивный тест (без контроля частоты и ротации)
    выдал бы кандидату ровно на старте грейда; дальше она не меняется."""
    forms = {}
    base = AppConfig(min_items=cfg.max_items, max_items=cfg.max_items, se_target=0.0, max_minutes=cfg.max_minutes,
                     subpools=1, exposure=False, max_per_format=cfg.max_per_format, stop_rule="se",
                     select_at="theta", ext_items=0)
    for g in ("junior", "middle", "senior"):
        theta = base.cat().start_theta.get(g, 0.0)
        p = Person(theta=theta, tau=0.0, claimed=g)
        sess, _ = run_session(pool, direction, make_responder(p, truth), base, None, g, None, rng)
        items = {i.family_id: i for i in sess.scored_pool}
        forms[g] = [items[a.family_id] for a in sess.administered if not a.canary and a.family_id in items]
    return forms


def run_fixed_population(pool, truth, people: list[Person], direction: str, forms: dict, cfg: AppConfig, rng,
                         leak: LeakModel | None = None) -> list[dict]:
    out = []
    for p in people:
        sess = FixedFormSession(pool, direction, cfg.cat(), forms[p.claimed], p.claimed, rng)
        responder = make_responder(p, truth, leak)
        while (item := sess.next_item()) is not None:
            x, log_t = responder(item, rng)
            sess.record(item, x, log_t, time_s=float(np.exp(log_t)) if log_t is not None else None)
        res = sess.result()
        d = decide(res.theta, res.se, p.claimed)
        out.append({"theta": res.theta, "se": res.se, "n_items": res.n_items, "confirmed": d.confirmed})
    return out


def calibrate_k(pool, direction: str, cfg: AppConfig, r_max: float = 0.3, n_sessions: int = 300,
                iterations: int = 6, seed: int = 0) -> tuple[dict, list[float]]:
    """Итеративная калибровка K_f (Sympson & Hetter, 1985) для конфигурации платформы.

    Истина = предкалибровка (misspec = 0): K_f зависят от того, что видит алгоритм выбора, а не от истины.
    """
    rng = np.random.default_rng(seed)
    truth = make_truth(pool, rng, misspec=0.0)
    ctrl = ExposureControl(r_max=r_max)
    hist = []
    for _ in range(iterations):
        ctrl.reset_counts()
        people = make_population(n_sessions, rng)
        for s, p in enumerate(people):
            sp = (s % cfg.subpools) if cfg.subpools > 1 else None
            run_session(pool, direction, make_responder(p, truth), cfg, ctrl, p.claimed, sp, rng)
        canary = {i.family_id for i in pool if i.canary}
        rates = {f: r for f, r in ctrl.exposure_rates().items() if f not in canary}  # канарейки опубликованы
        hist.append(round(max(rates.values()) if rates else 0.0, 3))
        ctrl.update()
    return {f: round(v, 4) for f, v in ctrl.k.items() if v < 0.9999}, hist


def exposure_stats(counter: ExposureControl, pool, direction: str, r_max: float = 0.3) -> dict:
    fam = [i.family_id for i in pool if not i.canary and i.block in ("common", direction)]
    n = max(counter.n_sessions, 1)
    rates = np.array([counter.administered.get(f, 0) / n for f in fam])
    return {"families": len(fam), "max_rate": round(float(rates.max()), 3), "mean_rate": round(float(rates.mean()), 3),
            "unused_share": round(float(np.mean(rates == 0)), 3),
            "share_over_rmax": round(float(np.mean(rates > r_max)), 3), "r_max": r_max}


def icc_21(x1, x2) -> float:
    """ICC(2,1) — двухфакторная модель со случайными эффектами, абсолютное согласие (Shrout & Fleiss, 1979)."""
    Y = np.column_stack([np.asarray(x1, float), np.asarray(x2, float)])
    n, k = Y.shape
    gm = Y.mean()
    msr = k * np.sum((Y.mean(1) - gm) ** 2) / (n - 1)
    msc = n * np.sum((Y.mean(0) - gm) ** 2) / (k - 1)
    resid = Y - Y.mean(1, keepdims=True) - Y.mean(0, keepdims=True) + gm
    mse = np.sum(resid ** 2) / ((n - 1) * (k - 1))
    return float((msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n))


def _band_probs(theta, se, cuts=(-1.0, 0.0, 1.0)) -> np.ndarray:
    """P(грейд = g) для θ̂ ~ N(θ, se²): (n, 4)."""
    theta, se = np.atleast_1d(np.asarray(theta, float)), np.atleast_1d(np.asarray(se, float))
    cdf = stats.norm.cdf((np.asarray(cuts)[None, :] - theta[:, None]) / np.maximum(se[:, None], 1e-9))
    full = np.column_stack([np.zeros(len(theta)), cdf, np.ones(len(theta))])
    return np.diff(full, axis=1)


def kappa_from_matrix(O: np.ndarray) -> float:
    k = O.shape[0]
    O = O / O.sum()
    W = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0))
    return float(1 - (W * O).sum() / max((W * E).sum(), 1e-12))


def ceiling_for(theta_true, se1, se2) -> dict:
    """Потолок повторяемости: два независимых измерения θ̂ = θ + N(0, SE²) с той же погрешностью, что у теста
    (по каждому кандидату), — ожидаемые точное совпадение грейда, ±1 ступень и κ (квадр.)."""
    P1, P2 = _band_probs(theta_true, se1), _band_probs(theta_true, se2)
    O = P1.T @ P2 / len(P1)
    idx = np.arange(O.shape[0])
    return {"grade_exact_agreement": round(float(np.trace(O)), 3),
            "grade_within_1": round(float(O[np.abs(idx[:, None] - idx[None, :]) <= 1].sum()), 3),
            "grade_kappa_quadratic": round(kappa_from_matrix(O), 3)}


def ceiling_curve(ses=(0.25, 0.30, 0.35, 0.40, 0.45, 0.50), sd: float = 1.0) -> list[dict]:
    """Потолок при постоянной погрешности SE и θ ~ N(0, sd²) (план пилота, п. 2.2): численное интегрирование."""
    grid = np.linspace(-5 * sd, 5 * sd, 2001)
    w = stats.norm.pdf(grid, 0, sd)
    w /= w.sum()
    out = []
    for se in ses:
        P = _band_probs(grid, np.full(grid.shape, se))
        O = (P * w[:, None]).T @ P
        idx = np.arange(O.shape[0])
        out.append({"se": se, "grade_exact_agreement": round(float(np.trace(O)), 3),
                    "grade_within_1": round(float(O[np.abs(idx[:, None] - idx[None, :]) <= 1].sum()), 3),
                    "grade_kappa_quadratic": round(kappa_from_matrix(O), 3),
                    "reliability": round(sd ** 2 / (sd ** 2 + se ** 2), 3)})
    return out


def retest_metrics(people, r1: list[dict], r2: list[dict]) -> dict:
    t1, t2 = np.array([r["theta"] for r in r1]), np.array([r["theta"] for r in r2])
    s1, s2 = np.array([r["se"] for r in r1]), np.array([r["se"] for r in r2])
    th = np.array([p.theta for p in people])
    g1, g2 = _grade_idx(t1), _grade_idx(t2)
    c1, c2 = np.array([r["confirmed"] for r in r1]), np.array([r["confirmed"] for r in r2])
    diff = t2 - t1
    both = r1 + r2
    return {"n": len(people), "r_theta": round(float(np.corrcoef(t1, t2)[0, 1]), 3),
            "icc_theta": round(icc_21(t1, t2), 3),
            "grade_exact_agreement": round(float(np.mean(g1 == g2)), 3),
            "grade_within_1": round(float(np.mean(np.abs(g1 - g2) <= 1)), 3),
            "grade_two_step_change": round(float(np.mean(np.abs(g1 - g2) >= 2)), 3),
            "grade_kappa_quadratic": round(quadratic_kappa(g1, g2), 3),
            "decision_agreement": round(float(np.mean(c1 == c2)), 3),
            "mean_diff_theta": round(float(diff.mean()), 3), "loa_theta": round(float(1.96 * diff.std(ddof=1)), 3),
            "mean_items": round(float(np.mean([r["n_items"] for r in both])), 2),
            "max_items": int(max(r["n_items"] for r in both)),
            "mean_time_min": round(float(np.mean([r["time_s"] for r in both]) / 60), 1),
            "extension_share": round(float(np.mean([r.get("n_ext", 0) > 0 for r in both])), 3),
            "mean_ext_items": round(float(np.mean([r.get("n_ext", 0) for r in both])), 2),
            "mean_se": round(float(np.mean(np.r_[s1, s2])), 3),
            "rms_se": round(float(np.sqrt(np.mean(np.r_[s1, s2] ** 2))), 3),
            "ceiling": ceiling_for(th, s1, s2)}


def retest(pool, truth, people, direction, cfg: AppConfig, rng, k) -> dict:
    """Повторное прохождение на другом субпуле (параллельная форма) и других вариантах. Во второй попытке
    семейства первой не попадают в дотестирование (как в продукте: previous_families)."""
    n = len(people)
    r1 = run_population(pool, truth, people, direction, cfg, rng, k=k, subpools=[0] * n)
    excl = [set(r["families"]) for r in r1]
    r2 = run_population(pool, truth, people, direction, cfg, rng, k=k, subpools=[1 % max(cfg.subpools, 1)] * n,
                        exclude=excl)
    return retest_metrics(people, r1, r2)


def summarize_safe(people, results) -> dict:
    return summarize(people, results)


def leak_summary(people, results) -> dict:
    from assessment_bank.psychometrics import GradeScale

    scale = GradeScale()
    ch = np.array([p.cheater for p in people])
    th = np.array([p.theta for p in people])
    est = np.array([r["theta"] for r in results])
    conf = np.array([r["confirmed"] for r in results])
    truly = np.array([p.theta >= scale.cuts[p.claimed] for p in people])
    gi_t, gi_e = _grade_idx(th), _grade_idx(est)
    out = {"n": len(people), "n_cheaters": int(ch.sum()),
           "cheaters_bias_theta": round(float(np.mean((est - th)[ch])), 3) if ch.any() else None,
           "honest_bias_theta": round(float(np.mean((est - th)[~ch])), 3),
           "cheaters_grade_inflated": round(float(np.mean((gi_e > gi_t)[ch])), 3) if ch.any() else None,
           "cheaters_false_confirm": round(float(np.mean(conf[ch & ~truly])), 3) if (ch & ~truly).any() else None,
           "honest_false_confirm": round(float(np.mean(conf[~ch & ~truly])), 3) if (~ch & ~truly).any() else None}
    if any("flagged" in r for r in results):
        fl = np.array([bool(r.get("flagged")) for r in results])
        out["detector_tpr"] = round(float(np.mean(fl[ch])), 3) if ch.any() else None
        out["detector_fpr"] = round(float(np.mean(fl[~ch])), 3)
    return out


def leak_experiment(pool, truth, direction: str, cfg: AppConfig, rng, k, n: int = 400, leak_share: float = 0.3,
                    cheater_share: float = 0.25, fpr: float = 0.01) -> dict:
    """Утечка leak_share вариантов + все канарейки; cheater_share кандидатов пользуются утечкой.

    Порог детектора калибруется по честной популяции при заданной доле ложных срабатываний (FPR).
    rotation: утёкший субпул выведен из ротации (карантин) — кандидаты получают неутёкший субпул;
    канарейки по замыслу остаются опубликованными.
    """
    honest = make_population(max(150, n // 2), rng)
    det0 = CanaryDetector()
    rh = run_population(pool, truth, honest, direction, cfg, rng, k=k, detector=det0)
    thr = CanaryDetector.calibrate_threshold(np.array([r["combined"] for r in rh]), fpr)
    det = CanaryDetector(threshold=thr)
    people = make_population(n, rng, cheater_share=cheater_share)
    leak = LeakModel(p_hit_scored=leak_share)
    res = {"threshold": round(float(thr), 3), "leak_share": leak_share, "cheater_share": cheater_share, "fpr_target": fpr}
    res["no_leak"] = leak_summary(people, run_population(pool, truth, people, direction, cfg, rng, k=k))
    res["leak_no_detector"] = leak_summary(people, run_population(pool, truth, people, direction, cfg, rng, k=k, leak=leak))
    res["leak_detector"] = leak_summary(people, run_population(pool, truth, people, direction, cfg, rng, k=k, leak=leak,
                                                               detector=det))
    # Карантин: утёк субпул 0 (та же доля вариантов), он выведен из ротации — сессии получают субпул 1. Задания
    # субпула 0 могут попасть только в дотестирование, если оно не учитывает карантин (механика до 06.10)
    n_people = len(people)
    sp_rot = [1] * n_people if cfg.subpools > 1 else None
    res["leak_detector_rotation"] = leak_summary(people, run_population(
        pool, truth, people, direction, cfg, rng, k=k, leak=leak if cfg.subpools > 1 else LeakModel(p_hit_scored=0.0),
        detector=det, subpools=sp_rot, blocked_subpools={0}, leaked_subpools={0} if cfg.subpools > 1 else None))
    # Фиксированная форма (одни задания всем): та же доля утечки и форма, утёкшая целиком (её задания не меняются)
    pool1 = make_pool(1)
    forms = fixed_forms(pool1, truth, direction, cfg, rng)
    res["fixed_form_items"] = {g: len(f) for g, f in forms.items()}
    res["fixed_no_leak"] = leak_summary(people, run_fixed_population(pool1, truth, people, direction, forms, cfg, rng))
    res["fixed_leak"] = leak_summary(people, run_fixed_population(pool1, truth, people, direction, forms, cfg, rng, leak))
    res["fixed_full_leak"] = leak_summary(people, run_fixed_population(pool1, truth, people, direction, forms, cfg, rng,
                                                                       LeakModel(p_hit_scored=1.0)))
    # Доля успешной атаки (ASR): списывающий без нужного уровня получил подтверждение заявленного грейда
    from assessment_bank.psychometrics import GradeScale

    cuts = GradeScale().cuts
    res["n_unqualified_cheaters"] = int(sum(1 for p in people if p.cheater and p.theta < cuts[p.claimed]))
    res["attack_success_rate"] = {k: res[k]["cheaters_false_confirm"] for k in (
        "no_leak", "leak_no_detector", "leak_detector", "leak_detector_rotation",
        "fixed_no_leak", "fixed_leak", "fixed_full_leak")}
    return res


# --------------------------------------------------------------------------- метрики к истине, условия конкурентов
def truth_metrics(people, results) -> dict:
    """Грейд по θ̂ против истинного грейда: точное совпадение, ±1, взвешенная κ с истиной, r(θ̂, θ)."""
    th = np.array([p.theta for p in people])
    est = np.array([r["theta"] for r in results])
    gt, ge = _grade_idx(th), _grade_idx(est)
    return {"n": len(people), "grade_exact": round(float(np.mean(gt == ge)), 3),
            "grade_within_1": round(float(np.mean(np.abs(gt - ge) <= 1)), 3),
            "kappa_true": round(quadratic_kappa(gt, ge), 3), "r_theta": round(float(np.corrcoef(th, est)[0, 1]), 3),
            "mean_items": round(float(np.mean([r["n_items"] for r in results])), 2),
            "mean_time_min": round(float(np.mean([r["time_s"] for r in results]) / 60), 1)}


def make_truth_like(pool, rng, b_sd: float, a_logsd: float) -> dict:
    """Истинные параметры с ошибкой как в симуляции конкурента: b + N(0; b_sd) по каждому заданию (семейству;
    у трёхшаговых — один сдвиг на семейство), a · LogN(0; a_logsd); разброс вариантов и время — как у банка."""
    from assessment_bank.simulation import TrueFamily

    out = {}
    for it in pool:
        mu = it.b + rng.normal(0, b_sd)
        a = it.a * np.exp(rng.normal(0, a_logsd))
        sigma = float(np.mean(it.sigma) * np.exp(rng.normal(0, 0.3)))
        out[it.family_id] = TrueFamily(it.family_id, a, mu, sigma,
                                       float(np.log(0.45 * it.time_limit_s) + rng.normal(0, 0.2)), it.time_limit_s)
    return out


# Длина 20 без досрочной остановки и дотестирования, весь банк направления (без субпулов), лимит времени 120 минут;
# повтор — семейства первой попытки исключены (вторая форма короче, если банк кончается)
COMPETITOR_LIKE = AppConfig(min_items=20, max_items=20, se_target=0.0, max_minutes=120, subpools=1,
                            stop_rule="se", ext_items=0, rotation="exclude_last")
COMPETITOR_ERROR = {"b_sd": 0.35, "a_logsd": 0.2, "source": "miliantr/fsp-talent, evaluation/results/tests_report.md"}


def competitor_run(pool1, direction, rng, k, n: int) -> dict:
    truth = make_truth_like(pool1, rng, COMPETITOR_ERROR["b_sd"], COMPETITOR_ERROR["a_logsd"])
    people = make_population(n, rng)
    cfg = COMPETITOR_LIKE
    r1 = run_population(pool1, truth, people, direction, cfg, rng, k=k)
    r2 = run_population(pool1, truth, people, direction, cfg, rng, k=k, exclude=[set(r["families"]) for r in r1])
    return {"truth": truth_metrics(people, r1), "retest": retest_metrics(people, r1, r2)}


def overclaim_attack(pool, truth, direction: str, cfg: AppConfig, rng, k, n: int = 300) -> dict:
    """Кандидат заявляет грейд на ступень выше своего истинного: доля ложных подтверждений."""
    scale = GradeScale()
    order = ("none", "junior", "middle", "senior")
    people = []
    for p in make_population(n, rng):
        g = scale.point(p.theta)
        if g != "senior":
            people.append(Person(p.theta, p.tau, order[max(order.index(g) + 1, 1)]))
    res = run_population(pool, truth, people, direction, cfg, rng, k=k)
    unq = [i for i, p in enumerate(people) if p.theta < scale.cuts[p.claimed]]
    return {"n": len(unq), "false_confirm": round(float(np.mean([res[i]["confirmed"] for i in unq])), 3) if unq else None}


def leak_share_table(pool, truth, direction: str, cfg: AppConfig, rng, k, shares=(0.1, 0.25, 0.5, 0.75),
                     n: int = 300, cheater_share: float = 0.25, fpr: float = 0.01) -> dict:
    """Доля успешной атаки по доле слитых вариантов: фиксированная форма против нашего теста (без детектора,
    с детектором, с детектором и карантином утёкшего субпула). Порог детектора — один, по честным при FPR 1 %."""
    honest = make_population(max(150, n // 2), rng)
    rh = run_population(pool, truth, honest, direction, cfg, rng, k=k, detector=CanaryDetector())
    det = CanaryDetector(threshold=CanaryDetector.calibrate_threshold(np.array([r["combined"] for r in rh]), fpr))
    people = make_population(n, rng, cheater_share=cheater_share)
    pool1 = make_pool(1)
    forms = fixed_forms(pool1, truth, direction, cfg, rng)
    cuts = GradeScale().cuts
    out = {"n": n, "cheater_share": cheater_share, "fpr_target": fpr,
           "n_unqualified_cheaters": int(sum(1 for p in people if p.cheater and p.theta < cuts[p.claimed])), "rows": []}
    two = cfg.subpools > 1
    for sh in shares:
        leak = LeakModel(p_hit_scored=sh)
        fx = leak_summary(people, run_fixed_population(pool1, truth, people, direction, forms, cfg, rng, leak))
        nd = leak_summary(people, run_population(pool, truth, people, direction, cfg, rng, k=k, leak=leak))
        dt = leak_summary(people, run_population(pool, truth, people, direction, cfg, rng, k=k, leak=leak, detector=det))
        rot = leak_summary(people, run_population(
            pool, truth, people, direction, cfg, rng, k=k, leak=leak if two else LeakModel(0.0), detector=det,
            subpools=[1] * len(people) if two else None, blocked_subpools={0}, leaked_subpools={0} if two else None))
        out["rows"].append({"leak_share": sh, "fixed_form": fx["cheaters_false_confirm"],
                            "no_detector": nd["cheaters_false_confirm"], "detector": dt["cheaters_false_confirm"],
                            "detector_quarantine": rot["cheaters_false_confirm"], "detector_tpr": dt.get("detector_tpr"),
                            "detector_fpr": dt.get("detector_fpr")})
    return out
