"""Стабильность «Junior (предварительно)»: правило решения на одних и тех же сессиях, дотестирование, API."""
import numpy as np

from assessment_bank.simulation import make_population, make_truth

from app.modules.validation import junior_stability as js
from app.modules.validation import sim


def test_quick_run_before_after_consistency():
    rep = js.run(n=60, quick=True, write=False)
    assert set(rep["directions"]) == set(sim.DIRECTIONS[:2])
    for pid in ("app", "legacy_sim"):
        b, a = rep["total"][pid]["before"], rep["total"][pid]["after"]
        # те же люди: заявившие Junior и истинно «ниже» совпадают; «до» предварительных нет
        assert b["n_claimed_junior"] == a["n_claimed_junior"] > 0 and b["n_true_below"] == a["n_true_below"]
        assert b["provisional"] == 0 and a["provisional"] > 0
        # «предварительно» берётся только из отказов: подтверждённые не меняются, отказов становится меньше
        assert a["confirmed"] == b["confirmed"] and a["rejected"] + a["provisional"] == b["rejected"]
        assert a["false_rejected"] <= b["false_rejected"]
        assert 0 <= a["false_provisional_share"] <= 1
    c = rep["total"]["app"]["confirm"]
    assert c["n_provisional"] == rep["total"]["app"]["after"]["provisional"]
    assert len(c["attempts"]) == js.CONFIRM_ATTEMPTS
    for att in c["attempts"]:
        assert att["confirmed_total"] + att["still_provisional"] == c["n_provisional"]  # отказов после дотестирования нет
        assert 0 < att["mean_new_items"] <= rep["rule"]["confirm_ext_items"]
    assert c["attempts"][-1]["confirmed_total"] >= c["attempts"][0]["confirmed_total"]


def test_confirm_session_carries_prior_answers_and_adds_short_items():
    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    rng = np.random.default_rng(5)
    truth = make_truth(pool, rng, misspec=0.5)
    person = next(p for p in make_population(50, rng) if p.claimed == "junior")
    (s1, r1), = js._run_people(pool, truth, [person], "backend", cfg, np.random.default_rng(6), {})
    s2, r2 = js.confirm_session(pool, "backend", person, truth, s1, r1, cfg, set(), np.random.default_rng(7))
    fam1 = {a.family_id for a in r1.administered}
    new = [a for a in r2.administered if a.family_id not in fam1]
    assert r2.n_items > r1.n_items and 1 <= len(new) <= cfg.ext_items
    assert all(not a.canary and s2.items[a.family_id].time_limit_s <= 300 for a in new)  # короткие задания у порога
    assert fam1 <= {a.family_id for a in r2.administered}  # ответы прошлой сессии перенесены


def test_api_serves_committed_report(client):
    r = client.get("/api/validation/junior-stability")
    assert r.status_code == 200
    d = r.json()
    assert not d.get("missing") and d["rule"]["confirm_level"] == 0.8 and d["rule"]["provisional_level"] == 0.1
    t = d["total"]["app"]
    assert t["after"]["provisional"] > 0 and t["after"]["false_rejected"] <= t["before"]["false_rejected"]
    assert len(d["directions"]) == 5 and d["total"]["app"]["confirm"]["attempts"]
