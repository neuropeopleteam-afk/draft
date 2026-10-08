"""Test–retest всего пути, D / r_pb, абляции подбора, P-полосы «предварительно», первый экран /validation."""
import json

import numpy as np
import pytest

from assessment_bank.psychometrics import CanaryDetector, ExposureControl
from assessment_bank.simulation import make_truth

from app.modules.assessment.intern_pool import intern_family_ids
from app.modules.validation import headline as hl
from app.modules.validation import junior_stability as js
from app.modules.validation import matching_bench as mb
from app.modules.validation import path_retest as pr
from app.modules.validation import sim
from app.modules.validation.bench_world import BenchConfig
from app.modules.validation.signature import config_hash, short, signature


@pytest.fixture(scope="module")
def quick():
    return pr.run(n=12, quick=True, write=False)


@pytest.fixture(scope="module")
def pool():
    cfg = sim.app_config_from_settings()
    return cfg, sim.make_pool(cfg.subpools)


def test_kappa_and_cut_distance():
    a = np.array([0, 1, 2, 3, 4, 2])
    assert pr.kappa_w(a, a) == pytest.approx(1.0)
    assert pr.kappa_w(a, a[::-1]) < 0.5
    d = pr.nearest_cut_distance(np.array([-1.0, -0.4, 0.1, 2.0]))
    assert d.tolist() == pytest.approx([0.0, 0.4, 0.1, 1.0])
    ag = pr.agreement(np.array([1, 2, 2, 3]), np.array([1, 2, 3, 3]))
    assert ag["exact"] == 0.75 and ag["within_1"] == 1.0 and ag["two_steps"] == 0.0


def test_quick_run_structure(quick):
    t = quick["total"]
    pg = t["path_grade"]
    assert pg["n"] == 24 and 0 <= pg["exact"] <= pg["within_1"] <= 1
    assert -1 <= pg["kappa_w"] <= 1 and pg["kappa_w_ci"][0] <= pg["kappa_w"] <= pg["kappa_w_ci"][1]
    assert 0 <= t["overlap_all"]["mean"] <= 1 and -1 <= t["icc_theta"] <= 1
    assert sum(quick["claimed"].values()) == 24
    assert sum(map(sum, quick["transitions"])) == 24
    st = t["path"]["status_share"]
    assert sum(st.values()) == pytest.approx(1.0, abs=0.01)
    assert {"far_from_cut", "near_cut", "far_from_boundary", "near_boundary", "decided_both", "undecided_any"} <= set(t["splits"])
    sig = quick["signature"]
    assert sig["seed"] == pr.SEED and len(sig["config_hash"]) == 12 and sig["commit"]
    assert "seed 20261006" in short(sig)
    md = pr.markdown(quick)
    assert "κ" in md and "Подпись мира" in md and "Дискриминативность" in md
    ds = quick["discrimination"]
    assert ds["n_families"] > 50 and all(-1 <= f["r_pb"] <= 1 and -1 <= f["D"] <= 1 for f in ds["families"])
    shifts = [r["shift"] for r in quick["block_gap"]["rows"]]
    assert shifts[0] == 0.0 and len(shifts) == 3


def test_retest_uses_new_subpool_and_excludes_last_families(pool):
    cfg, p = pool
    rng = np.random.default_rng(3)
    truth = make_truth(p, rng, misspec=0.5)
    cand = pr.Candidate(0.3, 0.0, "backend", 3.0, "middle", "middle", "middle", ["docker"])
    hist: list[dict] = []
    ctr, det = ExposureControl(0.3), CanaryDetector()
    r1 = pr.run_path(p, cand, truth, cfg, ctr, hist, rng, det)
    r2 = pr.run_path(p, cand, truth, cfg, ctr, hist, rng, det)
    assert r2["tests"][0]["subpool"] != r1["tests"][-1]["subpool"]  # ротация субпулов по истории
    assert r1["level"] in range(len(pr.LEVELS)) and r2["status"] in ("confirmed", "provisional", "accepted_lower", "none")


def test_intern_claim_uses_intern_pool_without_rotation(pool):
    cfg, p = pool
    rng = np.random.default_rng(4)
    truth = make_truth(p, rng, misspec=0.5)
    cand = pr.Candidate(-1.5, 0.0, "qa", 0.0, "junior", "intern", "intern", [])
    rec, _ = pr.run_session(p, cand, truth, cfg, ExposureControl(0.3), "intern", [], rng, CanaryDetector())
    assert rec["subpool"] is None
    keep = set(intern_family_ids(p, "qa"))
    assert set(rec["families"]) <= keep


def test_discrimination_flags_flat_items(pool):
    _, p = pool
    truth = pr.author_truth(p)
    fid = next(i.family_id for i in p if not i.canary and i.block == "qa")
    truth[fid].a[:] = 0.0  # задание, которое не различает
    rows = {r["family_id"]: r for r in pr.pilot_item_stats(p, "qa", truth, np.random.default_rng(1), n=400)}
    assert abs(rows[fid]["D"]) < 0.15 and abs(rows[fid]["r_pb"]) < 0.15
    others = [r["D"] for k, r in rows.items() if k != fid]
    assert np.median(others) > 0.3


def test_p_bands():
    b = js.p_bands([(0.12, True), (0.2, False), (0.3, True), (0.7, False), (0.79, False)])
    assert [x["n"] for x in b] == [2, 1, 0, 0, 2] and b[0]["true_below_share"] == 0.5 and b[2]["true_below_share"] is None


def test_bench_ablations():
    rep = mb.run(BenchConfig(n_needs=20, n_candidates=200), quick=True, write=False)
    ab = {a["method"]: a for a in rep["ablations"]}
    assert {"platform", "no_theta", "no_stack", "no_fsp", "no_tier", "no_test", "bm25"} <= set(ab)
    for k, a in ab.items():
        if k != "platform":
            d = a["diff_ndcg@10"]
            assert d["lo"] <= d["mean"] <= d["hi"]
    assert ab["no_tier"]["diff_ndcg@10"]["mean"] > 0  # ярус грейда из теста — главная часть подбора
    assert rep["signature"]["seed"] == rep["config"]["seed"]
    assert "## Абляции" in mb.markdown(rep)


def test_weighted_without_transfer():
    sc = {"comps": np.array([[[1.0, 0.0, 0.0, 0.0, 0.0]]]), "has_req": np.array([False]),
          "provisional": np.array([0.0])}
    w = np.array([0.0, 0.35, 0.05, 0.10, 0.05])
    assert mb.weighted(sc, w)[0, 0] == pytest.approx(0.35)  # без обязательного стека вес стека уходит на тест
    assert mb.weighted(sc, w, transfer=False)[0, 0] == 0.0


def test_headline_from_files(tmp_path, monkeypatch, quick):
    full = {**quick, "quick": False}
    p = tmp_path / "pr.json"
    p.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(hl, "PATH_RETEST", p)
    d = hl.headline()
    ids = [i["id"] for i in d["items"]]
    assert ids[:2] == ["path_kappa", "over_share"]
    assert all(i["signature"] and i["anchor"] for i in d["items"])
    monkeypatch.setattr(hl, "PATH_RETEST", tmp_path / "нет.json")
    monkeypatch.setattr(hl, "BENCH", tmp_path / "нет.json")
    assert hl.headline()["missing"] is True


def test_signature_hash_is_stable():
    assert config_hash({"b": 1, "a": [1, 2]}) == config_hash({"a": [1, 2], "b": 1})
    s = signature(seed=1, config={"x": 1}, world="мир", command="make x", n=3)
    assert s["seed"] == 1 and s["n"] == 3 and s["generated_at"]


def test_api_headline_and_path_retest(client):
    r = client.get("/api/validation/headline")
    assert r.status_code == 200 and "items" in r.json()
    r = client.get("/api/validation/path-retest")
    assert r.status_code == 200
    d = r.json()
    assert d.get("missing") or "families" not in d["discrimination"]
