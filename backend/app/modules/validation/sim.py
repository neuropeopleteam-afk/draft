"""Симуляция адаптивного теста в конфигурации платформы (строительные блоки — assessment_bank.simulation).

Отличие от симуляции банка: сессия — ``AppCATSession`` (лимит форматов), контроль частоты показа
Sympson — Hetter с K_f из ``exposure_k.json``, ротация 2 субпулов, длина и время — из настроек платформы.
Всё синтетическое: истинные параметры заданий = предкалибровка + систематическая ошибка эксперта
(σ = 0,5 по трудности семейства), популяция θ ~ N(0, 1). Проверяется механика, а не качество заданий на людях.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from assessment_bank import load_specs
from assessment_bank.psychometrics import CanaryDetector, CATConfig, ExposureControl, decide, pool_from_specs
from assessment_bank.simulation import (LeakModel, Person, _apply_detector, _grade_idx, make_population,
                                        make_responder, make_truth, quadratic_kappa, summarize)

from app.modules.assessment.exposure import AppCATSession

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

    def cat(self) -> CATConfig:
        return CATConfig(min_items=self.min_items, max_items=self.max_items, se_target=self.se_target,
                         max_time_s=self.max_minutes * 60.0, exposure="sympson_hetter" if self.exposure else "none")


BASELINE_DAY2 = AppConfig(max_items=20, max_minutes=90, subpools=1, exposure=False, max_per_format={})


def app_config_from_settings() -> AppConfig:
    from app.core.config import get_settings

    s = get_settings()
    return AppConfig(min_items=s.assessment_min_items, max_items=s.assessment_max_items,
                     se_target=s.assessment_se_target, max_minutes=s.assessment_max_minutes,
                     subpools=max(1, s.assessment_subpools), exposure=s.assessment_exposure == "sympson_hetter",
                     max_per_format={"open_book_3step": s.assessment_max_open_book,
                                     "open_answer": s.assessment_max_open_answer})


def make_pool(n_subpools: int, params: dict | None = None):
    return pool_from_specs(load_specs().values(), params=params, n_subpools=max(1, n_subpools))


def run_session(pool, direction, responder, cfg: AppConfig, exposure: ExposureControl | None, claimed: str,
                subpool: int | None, rng: np.random.Generator) -> tuple[AppCATSession, object]:
    # ExposureControl передаётся всегда (счётчик частоты показа); отбор Sympson — Hetter включает cfg.cat().exposure
    sess = AppCATSession(pool, direction, cfg.cat(), exposure, claimed, subpool, rng, max_per_format=cfg.max_per_format)
    while True:
        item = sess.next_item()
        if item is None:
            break
        x, log_t = responder(item, rng)
        sess.record(item, x, log_t, time_s=float(np.exp(log_t)) if log_t is not None else None)
    return sess, sess.result()


def run_population(pool, truth, people: list[Person], direction: str, cfg: AppConfig, rng, *,
                   k: dict | None = None, r_max: float = 0.3, subpools: list[int | None] | None = None,
                   leak: LeakModel | None = None, detector: CanaryDetector | None = None,
                   counter: ExposureControl | None = None) -> list[dict]:
    """Прогон популяции. counter — общий ExposureControl для подсчёта частоты показа по сессиям."""
    out = []
    for i, p in enumerate(people):
        if subpools is not None:
            sp = subpools[i]
        else:
            sp = int(rng.integers(cfg.subpools)) if cfg.subpools > 1 else None
        expo = counter if counter is not None else (ExposureControl(r_max, k=k) if cfg.exposure else None)
        if counter is not None:
            counter.k = dict(k or {})
        sess, res = run_session(pool, direction, make_responder(p, truth, leak), cfg, expo, p.claimed, sp, rng)
        d = decide(res.theta, res.se, p.claimed)
        rec = {"theta": res.theta, "se": res.se, "n_items": res.n_items, "time_s": res.time_used_s,
               "confirmed": d.confirmed, "stop": res.stop_reason, "subpool": sp,
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
                     subpools=1, exposure=False, max_per_format=cfg.max_per_format)
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


def retest(pool, truth, people, direction, cfg: AppConfig, rng, k) -> dict:
    """Повторное прохождение на другом субпуле (параллельная форма) и других вариантах."""
    n = len(people)
    r1 = run_population(pool, truth, people, direction, cfg, rng, k=k, subpools=[0] * n)
    r2 = run_population(pool, truth, people, direction, cfg, rng, k=k, subpools=[1 % max(cfg.subpools, 1)] * n)
    t1, t2 = np.array([r["theta"] for r in r1]), np.array([r["theta"] for r in r2])
    g1, g2 = _grade_idx(t1), _grade_idx(t2)
    c1, c2 = np.array([r["confirmed"] for r in r1]), np.array([r["confirmed"] for r in r2])
    return {"n": n, "r_theta": round(float(np.corrcoef(t1, t2)[0, 1]), 3),
            "grade_exact_agreement": round(float(np.mean(g1 == g2)), 3),
            "grade_within_1": round(float(np.mean(np.abs(g1 - g2) <= 1)), 3),
            "grade_kappa_quadratic": round(quadratic_kappa(g1, g2), 3),
            "decision_agreement": round(float(np.mean(c1 == c2)), 3),
            "mean_items": round(float(np.mean([r["n_items"] for r in r1 + r2])), 2)}


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
    res["leak_detector_rotation"] = leak_summary(people, run_population(
        pool, truth, people, direction, cfg, rng, k=k, leak=LeakModel(p_hit_scored=0.0), detector=det))
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
