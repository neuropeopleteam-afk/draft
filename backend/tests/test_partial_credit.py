"""Частичный балл 0–4 у развёрнутых ответов: GPCM, смешанная оценка θ, движок за флагом ASSESSMENT_PARTIAL_CREDIT_ENABLED,
симуляция «0/1» против «0–4» (малый прогон)."""
import numpy as np
import pytest
from scipy import special

from assessment_bank.psychometrics import CATConfig, CATSession, gpcm
from assessment_bank.psychometrics.irt import estimate_theta

from app.core.config import get_settings
from app.modules.assessment import bank_engine as be, partial_credit as pc
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.grader import GradeOutcome
from app.modules.validation import sim


def test_points_from_score():
    assert [pc.points(v) for v in (0.0, 0.1, 0.125, 0.3, 0.375, 0.5, 0.6667, 0.875, 1.0)] == [0, 0, 1, 1, 2, 2, 3, 4, 4]
    assert pc.points(None) is None
    assert pc.points(1.7) == 4 and pc.points(-0.2) == 0


def test_gpcm_probs_information_and_2pl_match():
    ag, steps = gpcm.from_2pl(1.2, 0.5)
    th = np.linspace(-3, 3, 13)
    p = gpcm.category_probs(th, ag, steps)
    assert p.shape == (13, 5) and np.allclose(p.sum(axis=1), 1.0)
    # ожидаемая доля балла ≈ кривая 2PL той же части: шкала θ та же, что у дихотомических заданий
    e = gpcm.expected_score(th, ag, steps) / 4
    assert np.max(np.abs(e - special.expit(1.2 * (th - 0.5)))) < 0.06
    # информация 0–4 больше, чем у той же части в 0/1, во всём рабочем диапазоне
    info2 = 1.2 ** 2 * special.expit(1.2 * (th - 0.5)) * (1 - special.expit(1.2 * (th - 0.5)))
    assert np.all(gpcm.information(th, ag, steps) > info2)
    assert gpcm.text_parts("open_answer", 1) == [0] and gpcm.text_parts("open_book_3step", 3) == [2]
    assert gpcm.text_parts("mcq_concept", 1) == []


def test_mixed_estimate_equals_2pl_without_text_parts():
    x, a, b = np.array([1, 0, 1, np.nan, 0.5]), np.array([1.0, 1.4, 0.8, 1.0, 1.1]), np.array([0, 0.5, -0.5, 0, 1])
    e1 = estimate_theta(x, a, b)
    e2 = gpcm.estimate_theta_mixed(x, a, b, [])
    assert abs(e1.theta - e2.theta) < 1e-9 and abs(e1.se - e2.se) < 1e-9


def _pool():
    return sim.make_pool(1)


def _session(partial: bool, score: float):
    pool = _pool()
    it = next(p for p in pool if p.format == "open_answer" and not p.canary)
    mc = [p for p in pool if p.format == "mcq_concept" and p.block in ("common", "backend") and not p.canary][:3]
    s = CATSession(pool, "backend", CATConfig(partial_credit=partial, exposure="none"), None, "middle",
                   rng=np.random.default_rng(1))
    for p, v in zip(mc, (1.0, 0.0, 1.0)):
        s.record(p, [v], None)
    s.record(it, [score], None)
    return s, it


def test_cat_session_flag_off_unchanged_and_on_uses_points():
    s_off, it = _session(False, 0.75)
    x, a, b = s_off._scored_arrays()
    ref = estimate_theta(x, a, b)
    assert abs(s_off.theta - ref.theta) < 1e-12  # без флага — прежняя оценка (2PL, доля как квазибиномиальная)
    s_on, _ = _session(True, 0.75)
    assert s_on.se < s_off.se  # балл 3 из 4 — больше информации, чем доля 0,75 в 2PL
    hi, _ = _session(True, 1.0)
    lo, _ = _session(True, 0.25)
    assert hi.theta > s_on.theta > lo.theta
    # 0,70 и 0,80 — тот же балл 3: GPCM видит балл, а не дробь
    a1, _ = _session(True, 0.70)
    a2, _ = _session(True, 0.80)
    assert abs(a1.theta - a2.theta) < 1e-12
    # выбор: информация развёрнутого задания с флагом выше
    assert it.information_pc(float(it.b[0])) > it.information(float(it.b[0]))
    # «на проверке» (nan) не входит в θ
    s_nan, _ = _session(True, float("nan"))
    s_none = CATSession(_pool(), "backend", CATConfig(partial_credit=True, exposure="none"), None, "middle",
                        rng=np.random.default_rng(1))
    assert s_nan._pc_arrays()[3] == [] and s_none.theta == s_nan.cfg.start_theta.get("middle", 0.0)


@pytest.fixture
def fake_grade(monkeypatch):
    def grade(*, stem, code, step_prompt, rubric, answer, use_llm=True, **_):
        assert rubric and rubric.get("criteria")
        return GradeOutcome(status="scored", score=0.7 if len(answer) > 40 else 0.0, method="llm", model="test")
    monkeypatch.setattr(be, "grade_open", grade)


def _run(engine: BankEngine):
    from tests.test_bank_engine import oracle

    st = engine.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=4242)
    while True:
        item = engine.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        engine.answer(st, item.item_id, oracle(it, item.step or 1, True), 1000, step=item.step)
    return st, engine.finish(st)


def test_engine_flag_off_no_partial_keys(fake_grade):
    assert get_settings().assessment_partial_credit_enabled is False
    st, res = _run(BankEngine())
    assert "partial_credit" not in st["cfg"] and "partial_credit" not in res.details
    assert not any(i.get("pc") for i in st["items"])
    assert all("points" not in (g or {}) for i in st["items"] for g in i["grading"])


def test_engine_flag_on_points_and_summary(fake_grade, monkeypatch):
    monkeypatch.setattr(get_settings(), "assessment_partial_credit_enabled", True)
    st, res = _run(BankEngine())
    assert st["cfg"]["partial_credit"] is True
    opens = [i for i in st["items"] if i["format"] in ("open_answer", "open_book_3step") and not i["canary"]]
    assert opens, "в сессии должны быть развёрнутые задания"
    for i in opens:
        assert i["pc"] is True
        part = 0 if i["format"] == "open_answer" else 2
        assert i["grading"][part]["points"] == 3  # оценка 0,7 → балл 3 из 4
    summ = res.details["partial_credit"]
    assert summ["model"] == pc.MODEL and sum(summ["distribution"]) == len(summ["parts"]) >= 1
    assert all(p["points"] == 3 for p in summ["parts"])


def test_engine_flag_on_generic_rubric(fake_grade, monkeypatch):
    monkeypatch.setattr(get_settings(), "assessment_partial_credit_enabled", True)
    eng = BankEngine()
    orig = be.generate

    def no_rubric(fid, seed):
        v = orig(fid, seed)
        return v.model_copy(update={"rubric": None})
    monkeypatch.setattr(be, "generate", no_rubric)
    st, _ = _run(eng)
    opens = [i for i in st["items"] if i.get("pc")]
    assert opens and all(i["rubric"]["generic"] for i in opens)
    assert [c["id"] for c in pc.generic_rubric("x")["criteria"]] == ["correct", "complete", "reasoning"]


def test_sim_small_run_shapes():
    from app.modules.validation import partial_credit_sim as P

    parts = {arm: P.run_task((arm, "base", 0.6, "adaptive", 0, "backend", 6)) for arm in ("frac", "gpcm")}
    s = P.summarize([parts["gpcm"]])
    for k in ("exact", "over", "retest_exact", "retest_kappa_w", "se_first_mean", "minutes_per_path"):
        assert k in s
    d = P.paired_diff([parts["frac"]], [parts["gpcm"]], 1, n_boot=50)
    assert set(d) >= {"exact", "exact_ci", "over", "retest_exact"}
    m = P.noise_matrix()
    assert m.shape == (5, 5) and np.allclose(m.sum(axis=1), 1.0)


def test_validation_partial_credit_route(client, monkeypatch):
    r = client.get("/api/validation/partial-credit")
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is False
    assert d["grader"]["agreement"]["on_v3_skeptic"]["n"] > 200
    assert "missing" in d or d["rows"]
    monkeypatch.setattr(get_settings(), "assessment_partial_credit_enabled", True)
    assert client.get("/api/validation/partial-credit").json()["enabled"] is True
