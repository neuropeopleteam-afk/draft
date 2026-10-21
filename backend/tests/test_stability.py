"""Стабильность грейда: классификационная остановка, дотестирование у порога, потолок совпадения, ICC."""
from __future__ import annotations

import numpy as np
import pytest

from assessment_bank.psychometrics import CATConfig, CATSession, ExposureControl, GradeScale
from assessment_bank.simulation import Person, make_responder, make_truth

from app.modules.validation import sim

CUTS = GradeScale().cuts


@pytest.fixture(scope="module")
def pool():
    return sim.make_pool(2)


def _run(pool, theta, cfg, subpool=0, seed=1, **kw):
    rng = np.random.default_rng(seed)
    truth = make_truth(pool, np.random.default_rng(0), misspec=0.0)
    sess = CATSession(pool, "backend", cfg, None, "middle", subpool, rng, **kw)
    resp = make_responder(Person(theta, 0.0, "middle"), truth)
    while (item := sess.next_item()) is not None:
        x, lt = resp(item, rng)
        sess.record(item, x, lt, time_s=float(np.exp(lt)))
    return sess


NEW = dict(stop_rule="classification", classify_z=1.28, select_at="cut", ext_items=6, ext_time_s=1200.0,
           ext_own_first=True, max_items=16, min_items=8, se_target=0.35, max_time_s=3600.0)


def test_classification_stop_far_from_cuts(pool):
    """Сильный кандидат далеко от порогов: основная часть останавливается по классификации, без дотестирования."""
    s = _run(pool, 2.8, CATConfig(**NEW))
    assert s.stop_reason in ("classified", "se_target") and s.n_ext == 0
    assert not s.uncertain_cuts()


def test_extension_at_nearest_cut_short_items(pool):
    s = _run(pool, CUTS["middle"] + 0.05, CATConfig(**NEW))
    assert s.ext_start is not None and 1 <= s.n_ext <= 6
    assert s.ext_cut in CUTS.values()
    ext = [a for a in s.administered if not a.canary][s.ext_start:]
    assert all(s.items[a.family_id].time_limit_s <= 300 for a in ext)
    assert s.stop_reason in ("extension_done", "extension_classified", "extension_pool_exhausted")


def test_extension_respects_quarantine_and_previous_families(pool):
    first = _run(pool, 0.05, CATConfig(**NEW), subpool=0, seed=3)
    prev = {a.family_id for a in first.administered if not a.canary}
    # Дотестирование у порога включается, только если оценка второй попытки легла у порога; при θ = 0,05 это
    # зависит от случайных ответов (с ростом банка до ~200 семейств на направление seed=4 перестал давать порог).
    # Берём первый seed из фиксированного ряда, где дотестирование было, и проверяем его свойства.
    for seed in range(4, 64):
        s = _run(pool, 0.05, CATConfig(**NEW), subpool=1, seed=seed, exclude_ext=prev, blocked_subpools={0})
        if s.ext_start is not None:
            break
    ext = [a.family_id for a in s.administered if not a.canary][s.ext_start or 0:]
    assert s.ext_start is not None and ext, "ни в одной из 60 попыток не было дотестирования у порога"
    assert not set(ext) & prev
    assert all(s.items[f].subpool == 1 for f in ext)


def test_old_defaults_unchanged(pool):
    """CATConfig по умолчанию — прежнее поведение (остановка по SE, выбор в θ̂, без дотестирования)."""
    c = CATConfig()
    assert (c.stop_rule, c.select_at, c.ext_items, c.ext_own_first) == ("se", "theta", 0, False)
    s = _run(pool, 0.0, CATConfig(max_items=16, max_time_s=3600.0))
    assert s.n_ext == 0 and s.stop_reason != "classified"


def test_ceiling_curve_matches_pilot_plan():
    """Потолок при SE 0,35 (план пилота, 2.2): точное совпадение ≈ 0,66, κ ≈ 0,81; растёт с точностью."""
    cur = {round(x["se"], 2): x for x in sim.ceiling_curve()}
    assert abs(cur[0.35]["grade_exact_agreement"] - 0.664) < 0.01
    assert abs(cur[0.35]["grade_kappa_quadratic"] - 0.812) < 0.01
    ks = [cur[s]["grade_kappa_quadratic"] for s in sorted(cur)]
    assert ks == sorted(ks, reverse=True)


def test_ceiling_for_monte_carlo():
    rng = np.random.default_rng(0)
    th = rng.normal(0, 1, 4000)
    se = np.full(th.shape, 0.4)
    c = sim.ceiling_for(th, se, se)
    g1 = sim._grade_idx(th + rng.normal(0, 0.4, th.shape))
    g2 = sim._grade_idx(th + rng.normal(0, 0.4, th.shape))
    assert abs(c["grade_exact_agreement"] - float(np.mean(g1 == g2))) < 0.03


def test_icc_21():
    x = np.linspace(-2, 2, 50)
    assert sim.icc_21(x, x) == pytest.approx(1.0)
    assert sim.icc_21(x, x + 1.0) < sim.icc_21(x, x)        # абсолютное согласие штрафует сдвиг
    rng = np.random.default_rng(1)
    t = rng.normal(0, 1, 3000)
    icc = sim.icc_21(t + rng.normal(0, 0.5, t.shape), t + rng.normal(0, 0.5, t.shape))
    assert abs(icc - 1 / 1.25) < 0.04


def test_legacy_extension_reproduces_old_product_rule(pool):
    """Механика до 06.10 в симуляции: 3 задания у порога заявленного грейда, если |θ̂ − порог| < SE."""
    truth = make_truth(pool, np.random.default_rng(0), misspec=0.0)
    rng = np.random.default_rng(5)
    resp = make_responder(Person(0.02, 0.0, "middle"), truth)
    s, res = sim.run_session(pool, "backend", resp, sim.LEGACY, ExposureControl(0.3), "middle", 0, rng)
    if s.n_ext:
        assert s.n_ext == 3 and s.stop_reason == "extension_done"
    else:
        assert abs(res.theta - CUTS["middle"]) >= res.se or s.stop_reason == "time"
