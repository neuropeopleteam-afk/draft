"""Я22: точность уровня — позиция внутри уровня (флаг GRADE_POSITION_ENABLED), параметры решения в симуляции пути,
перебор параметров (метрики, Парето, выбор)."""
from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path

from app.core.config import get_settings
from app.modules.assessment.grades import level_position
from app.modules.assessment.rules import accept_lower_allowed
from app.modules.validation import grade_sweep as gs
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, ONBOARDING, pass_test


# ------------------------------------------------------------------ позиция внутри уровня

@pytest.mark.parametrize("theta,se,grade,code", [
    (0.5, 0.30, "middle", "middle"),
    (0.1, 0.30, "middle", "lower"),
    (0.9, 0.30, "middle", "upper"),
    (0.5, 0.45, "middle", "uncertain"),     # погрешность шире половины полосы — позицию не называем
    (0.3, 0.33, "middle", "uncertain"),
    (2.0, 0.40, "senior", "upper"),         # у Senior условная ширина полосы 1
    (-1.3, 0.30, "intern", "uncertain"),    # полоса Стажёра узкая (0,75)
    (-0.8, 0.25, "junior", "lower"),
    (0.1, 0.70, "middle", "uncertain"),     # SE > POSITION_MAX_SE
])
def test_level_position(theta, se, grade, code):
    p = level_position(theta, se, grade)
    assert p["code"] == code and p["known"] == (code != "uncertain")
    assert "θ" not in p["text"] and not any(ch.isdigit() for ch in p["text"])  # без чисел θ


def test_level_position_none():
    assert level_position(0.5, 0.3, None) is None
    assert level_position(0.5, 0.3, "none") is None
    assert level_position(None, 0.3, "middle") is None


def _with_flag(monkeypatch, on: bool):
    monkeypatch.setenv("GRADE_POSITION_ENABLED", "true" if on else "false")
    get_settings.cache_clear()


def test_result_position_flag(client, monkeypatch):
    t = register_and_verify(client, email="pos@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    _with_flag(monkeypatch, False)
    res = pass_test(client, t, "middle")
    assert "level_position" not in res  # флаг выключен — как раньше
    _with_flag(monkeypatch, True)
    try:
        res = client.get(f"/api/assessment/sessions/{res['session_id']}/result", headers=H(t))
        if res.status_code == 404:  # путь итога другой — проверяем через новый тест
            res = pass_test(client, t, "middle")
        else:
            res = res.json()
        assert "level_position" in res
        if res.get("confirmed"):
            assert res["level_position"]["grade"] == "middle"
            assert res["level_position"]["code"] in ("lower", "middle", "upper", "uncertain")
    finally:
        _with_flag(monkeypatch, False)


def test_grade_status_position(monkeypatch):
    from app.modules.profiles import facts

    out: dict = {}
    _with_flag(monkeypatch, False)
    facts._position(out, {"theta": 0.9, "se": 0.3}, "middle")
    assert "position" not in out
    _with_flag(monkeypatch, True)
    try:
        facts._position(out, {"theta": 0.9, "se": 0.3}, "middle")
        assert out["position"]["code"] == "upper"
    finally:
        _with_flag(monkeypatch, False)


# ------------------------------------------------------------------ порог уверенности «уровня ниже»

def test_accept_lower_level_parameter():
    probs = {"none": 0.02, "intern": 0.08, "junior": 0.25, "middle": 0.6, "senior": 0.05}
    # P(≥ junior) = 0,9, P(≥ middle) = 0,65: при 0,8 — junior, при 0,6 — middle (но middle заявлен) → junior
    assert accept_lower_allowed(None, "senior", False, probs, level=0.8)[0] == "junior"
    assert accept_lower_allowed(None, "senior", False, probs, level=0.6)[0] == "middle"


# ------------------------------------------------------------------ перебор: метрики, Парето, выбор

def _row(true, l1, l2, minutes=50.0):
    n = len(true)
    return {"true": true, "claimed": true, "l1": l1, "l2": l2, "min1": [minutes] * n, "items1": [20] * n,
            "sess1": [1] * n, "status1": ["confirmed"] * n, "border1": [False] * n}


def test_sweep_metrics_and_choice():
    t = [1, 2, 3, 4, 2, 3, 3, 2, 1, 4]
    exact = gs.metrics([_row(t, t, t)], boot=False)
    assert exact["exact"] == 1.0 and exact["over"] == 0.0 and exact["retest_kappa"] == 1.0 and exact["feasible"]
    low = [max(v - 1, 0) for v in t]
    under = gs.metrics([_row(t, low, low)], boot=False)
    assert under["under"] + under["none"] == 1.0 and under["exact"] == 0.0
    slow = gs.metrics([_row(t, t, t, minutes=75.0)], boot=False)
    assert not slow["feasible"]  # время пути > 60 мин
    base = gs.baseline_point()
    pts = [{"key": "base", "point": base, "metrics": under},
           {"key": "fast", "point": {**base, "confirm_level": 0.5}, "metrics": exact},
           {"key": "slow", "point": {**base, "max_items": 20}, "metrics": slow}]
    front = gs.pareto(pts)
    assert "fast" in front and "base" not in front
    ch = gs.choose(pts, "base")
    assert ch["key"] == "fast" and ch["better_on_all"] and ch["delta_exact"] == 1.0


def test_borderline_rule():
    assert not gs.borderline("middle", 0.5, 0.2)
    assert gs.borderline("middle", 0.1, 0.3)       # нижняя граница не доказана с P ≥ 0,8
    assert gs.borderline("middle", 0.9, 0.3)       # следующий уровень не исключён
    assert not gs.borderline("senior", 2.0, 0.3)


def test_low_info_families_share():
    from app.modules.validation import sim

    pool = sim.make_pool(2)
    low = gs.low_info_families(pool, 0.2)
    blocks = {i.block for i in pool if not i.canary}
    assert 0 < len(low) <= int(0.2 * len([i for i in pool if not i.canary])) + len(blocks)
    assert not gs.low_info_families(pool, 0.0)


def test_sweep_task_small():
    """Одна точка, 3 кандидата: путь считается, уровни в шкале, 4 ступени — без Стажёра."""
    r = gs.run_task((gs._p(), 0, "backend", 3))
    assert len(r["l1"]) == 3 and all(0 <= v <= 4 for v in r["l1"] + r["true"])
    r4 = gs.run_task((gs._p(levels=4, misspec=0.35, decision="point"), 0, "backend", 3))
    assert all(0 <= v <= 3 for v in r4["l1"] + r4["true"])
    assert np.isfinite(r4["min1"]).all()


def test_confirm_level_setting(monkeypatch):
    """Порог уверенности — из настройки ASSESSMENT_CONFIRM_LEVEL (по умолчанию 0,6 по перебору); 0,8 — прежнее правило."""
    from app.modules.assessment.grades import GRADE_CUTS, confirm_level, confirm_pct, decide_grade, p_at_least

    assert get_settings().assessment_confirm_level == pytest.approx(0.6)
    se = 0.33
    th = GRADE_CUTS["middle"] + 0.5 * se  # P(θ ≥ порога Middle) ≈ 0,69: подтверждён при 0,6, не при 0,8
    assert 0.6 < p_at_least(th, se, "middle") < 0.8
    assert decide_grade(th, se, "middle").confirmed
    assert not decide_grade(th, se, "middle", confirm_level=0.8).confirmed
    monkeypatch.setenv("ASSESSMENT_CONFIRM_LEVEL", "0.8")
    get_settings.cache_clear()
    try:
        assert confirm_level() == pytest.approx(0.8) and confirm_pct() == 80
        assert not decide_grade(th, se, "middle").confirmed
    finally:
        monkeypatch.delenv("ASSESSMENT_CONFIRM_LEVEL")
        get_settings.cache_clear()


def test_meta_confirm_pct(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert r.json()["rules"]["confirm_pct"] == round(100 * get_settings().assessment_confirm_level)


def test_grade_accuracy_endpoint(client):
    r = client.get("/api/validation/grade-accuracy")
    assert r.status_code == 200
    d = r.json()
    if d.get("missing"):
        pytest.skip("grade_sweep.json не посчитан")
    assert d["baseline"]["label"].startswith("прежняя конфигурация")
    ch = d["choice"]["row"]
    assert ch["feasible"] and ch["exact"] > d["baseline"]["exact"]
    assert ch["over"] <= d["constraints"]["max_over"]
    assert ch["point"]["confirm_level"] == pytest.approx(get_settings().assessment_confirm_level)
    pool = d.get("pool") or {}
    if pool.get("rows"):  # чистка пула: строки двух миров; флаг по умолчанию выключен, пока исключение не лучше по всем
        assert {"platform", "plus"} >= set(pool["exclude_better"])
        if not any(pool["exclude_better"].values()):
            assert not get_settings().assessment_weak_exclude
        assert all(not r["world_weak"] or "истинная a" in r["label"] for r in pool["rows"])
    assert d["pareto"] and d["worlds"] and d["key_rows"]


# ------------------------------------------------------------------ чистка пула (ASSESSMENT_WEAK_EXCLUDE)

def test_weak_exclude_flag(monkeypatch):
    """Флаг выключен — пул как раньше; включён — 26 слабых по панели семейств не выдаются (один список с симуляцией)."""
    from types import SimpleNamespace as NS

    from app.modules.assessment import weak_pool

    assert not get_settings().assessment_weak_exclude
    assert weak_pool.weak_excluded() == frozenset()
    assert weak_pool.weak_excluded(NS(assessment_weak_exclude=True)) == weak_pool.WEAK_FAMILIES
    # Список меняется при перезаморозке банка (выведенные семейства из него убираются), поэтому проверяем не длину,
    # а смысл: список не пуст, один объект с симуляцией и каждое семейство есть в ДЕЙСТВУЮЩЕМ банке (не в выведенных).
    assert weak_pool.WEAK_FAMILIES and gs.WEAK_FAMILIES is weak_pool.WEAK_FAMILIES
    import re as _re

    bank_root = Path(__file__).resolve().parents[1] / "assessment_bank"
    def _ids(sub: str) -> set[str]:
        out = set()
        for y in (bank_root / sub).rglob("*.yaml"):
            m = _re.search(r"^family_id:\s*(\S+)", y.read_text(encoding="utf-8"), _re.M)
            if m:
                out.add(m.group(1))
        return out
    live, retired = _ids("families"), _ids("families_retired")
    assert weak_pool.WEAK_FAMILIES <= live, sorted(weak_pool.WEAK_FAMILIES - live)
    assert not (weak_pool.WEAK_FAMILIES & retired), sorted(weak_pool.WEAK_FAMILIES & retired)
    from app.modules.validation import sim

    ids = {i.family_id for i in sim.make_pool(1)}
    assert weak_pool.WEAK_FAMILIES <= ids  # все семейства списка есть в банке платформы
    monkeypatch.setenv("ASSESSMENT_WEAK_EXCLUDE", "true")
    get_settings.cache_clear()
    try:
        assert weak_pool.weak_excluded() == weak_pool.WEAK_FAMILIES
    finally:
        monkeypatch.delenv("ASSESSMENT_WEAK_EXCLUDE")
        get_settings.cache_clear()


def test_weak_exclude_session(monkeypatch):
    """С флагом слабые семейства не попадают ни в основную часть, ни в дотестирование; без флага — пул прежний."""
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment import weak_pool

    eng = be.BankEngine()
    st = eng.start(direction="frontend", claimed_grade="middle", stack_tags=["javascript", "react", "typescript"],
                   seed=777)
    sess = eng._rebuild(st)
    before = {p.family_id for p in sess.scored_pool} | {p.family_id for p in sess.ext_pool}
    assert before & weak_pool.WEAK_FAMILIES  # без флага слабые frontend-семейства в пуле есть
    monkeypatch.setenv("ASSESSMENT_WEAK_EXCLUDE", "true")
    get_settings.cache_clear()
    try:
        sess = eng._rebuild(st)
        after = {p.family_id for p in sess.scored_pool} | {p.family_id for p in sess.ext_pool}
        assert after and not after & weak_pool.WEAK_FAMILIES
        assert after == before - weak_pool.WEAK_FAMILIES
    finally:
        monkeypatch.delenv("ASSESSMENT_WEAK_EXCLUDE")
        get_settings.cache_clear()


def test_plus_snapshot_and_task():
    """Снимок добора у порогов: 17 семейств, prior с basis в банке; точка с plus = 1 считается."""
    specs = gs.plus_specs()
    assert [s.family_id for s in specs] == list(gs.PLUS_FAMILIES)
    assert all(s.prior_difficulty.a > 0 and s.time_limit_s > 0 for s in specs)
    pool = gs._pool(1, 1)
    ids = {i.family_id for i in pool}
    assert set(gs.PLUS_FAMILIES) <= ids
    r = gs.run_task((gs._p(confirm_level=0.6, plus=1, weak_pool="exclude"), 0, "security", 3))
    assert len(r["l1"]) == 3


# ------------------------------------------------------------------ другие условия измерения (grade_compare)

def test_promote_and_exact_task_small():
    """Мир точных параметров и короткий тест на уровень выше: путь считается, предложение — только подтвердившим."""
    r = gs.run_task((gs._p(confirm_level=0.6, exact=1, promote=0.0, promote_up=0.8), 0, "backend", 4))
    assert len(r["l1"]) == 4 and len(r["offer1"]) == 4
    for st, off in zip(r["status1"], r["offer1"]):
        assert not off or st in ("confirmed", "promoted")
    th, se = gs.combine(1.0, 0.33, 1.2, 0.45)
    assert 1.0 < th < 1.2 and se < 0.33


def test_grade_compare_subset_and_doc():
    from app.modules.validation import grade_compare as gc

    row = {"true": [2, 3, 3, 4], "claimed": [2, 2, 3, 4], "l1": [2, 2, 3, 4], "l2": [2, 2, 3, 3],
           "min1": [50.0] * 4, "items1": [20] * 4, "sess1": [1] * 4, "border1": [False] * 4,
           "status1": ["confirmed"] * 4, "offer1": [False] * 4}
    sub = gc._subset([row], lambda t, c: c >= t)
    assert sub[0]["true"] == [2, 3, 4]
    m = gc.block([row], 0)
    assert m["under_claimed_below"] == 0.25 and m["claimed_below_share"] == 0.25 and m["under_other"] == 0.0
    if gc.OUT.exists():  # документ — из генератора
        import json

        assert gc.DOCS_MD.read_text(encoding="utf-8") == gc.markdown(json.loads(gc.OUT.read_text(encoding="utf-8")))
