"""Бенчмарк подбора со скрытой истиной: метрики, детерминизм, изоляция истины, верность продукту, API."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import score_candidate
from app.modules.validation import matching_bench as mb
from app.modules.validation.bench_world import BenchConfig, Latent, Observed, build_bundle, generate, true_relevance
from app.modules.validation.matching_eval import BM25

SMALL = BenchConfig(n_needs=20, n_candidates=200)
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def world():
    return generate(SMALL)


def _digest(w) -> str:
    h = hashlib.sha256()
    h.update(w.rel.tobytes())
    for c in w.candidates:
        h.update(json.dumps(asdict(c.obs), sort_keys=True, ensure_ascii=False).encode())
    for n in w.needs:
        h.update(n.text.encode())
    return h.hexdigest()


def test_metrics_on_hand_example():
    rel = np.array([[3, 0, 2, 0, 1, 0, 0, 0, 0, 0, 0, 2]])
    order = np.arange(12)[None, :]
    m = mb.per_need(rel, order)
    disc = 1 / np.log2(np.arange(2, 12))
    dcg5 = 7 * disc[0] + 3 * disc[2] + 1 * disc[4]
    idcg5 = 7 * disc[0] + 3 * disc[1] + 3 * disc[2] + 1 * disc[3]
    assert m["ndcg@5"][0] == pytest.approx(dcg5 / idcg5)
    assert m["p@5"][0] == pytest.approx(2 / 5)
    assert m["p@10"][0] == pytest.approx(2 / 10)
    assert m["mrr"][0] == pytest.approx(1.0)
    m2 = mb.per_need(rel, np.array([[1, 3, 0, 2, 4, 5, 6, 7, 8, 9, 10, 11]]))
    assert m2["mrr"][0] == pytest.approx(1 / 3)
    ideal = mb.per_need(rel, np.argsort(-rel, kind="stable"))
    assert ideal["ndcg@10"][0] == pytest.approx(1.0)


def test_bootstrap_ci_contains_mean():
    x = np.random.default_rng(1).random(50)
    ci = mb._ci(x, mb.boot_idx(50, 2))
    assert ci["lo"] <= ci["mean"] <= ci["hi"] and ci["hi"] - ci["lo"] < 0.3


def test_world_is_deterministic_across_processes(world):
    """Тот же seed — тот же мир, в том числе при другом PYTHONHASHSEED (порядок обхода множеств)."""
    assert _digest(generate(SMALL)) == _digest(world)
    code = ("from tests.test_matching_bench import _digest, SMALL; from app.modules.validation.bench_world import generate;"
            "print(_digest(generate(SMALL)))")
    env = {**os.environ, "PYTHONHASHSEED": "12345"}
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == _digest(world)
    assert _digest(generate(replace(SMALL, seed=SMALL.seed + 1))) != _digest(world)


def test_ranking_does_not_see_truth(world):
    """Выдача платформы и базовых линий строится только из Observed: если стереть истину (Latent и метки),
    порядки не меняются ни на одну позицию."""
    assert not set(Latent.__dataclass_fields__) & set(Observed.__dataclass_fields__)
    reqs = mb._parsed(world)
    blank = Latent(direction="qa", theta=0.0, true_grade=None, known=frozenset(), talent=0.0, persona="honest")
    wiped = replace(world, candidates=[replace(c, latent=blank) for c in world.candidates],
                    rel=np.zeros_like(world.rel))
    methods = ("platform", "no_fsp", "no_test", "no_guard", "bm25", "keywords_grade")
    a = mb.run_methods(world, reqs, 1, methods)["orders"]
    b = mb.run_methods(wiped, reqs, 1, methods)["orders"]
    for k in methods:
        assert all(np.array_equal(x, y) for x, y in zip(a[k], b[k], strict=True)), k
    # строгая истина меняет метки, но не выдачу
    strict = replace(SMALL, truth="strict")
    rel_s = np.array([[true_relevance(n, c.latent, strict) for c in world.candidates] for n in world.needs])
    assert (rel_s != world.rel).any()


def test_light_bundle_scores_like_orm_models(world):
    reqs = mb._parsed(world)[:5]
    for c in world.candidates[:60]:
        for mode in ("platform", "t0_only", "no_guard"):
            light, orm = build_bundle(c.obs, mode), build_bundle(c.obs, mode, orm=True)
            for r in reqs:
                assert score_candidate(light, r)[:2] == score_candidate(orm, r)[:2]
            assert light.strength() == orm.strength()


def test_score_rebuilt_from_components_matches_product(world):
    sc = mb.score_world(world, mb._parsed(world))
    assert sc["max_rebuild_error"] < 1e-3


def test_bm25_matrix_matches_matching_eval(world):
    docs = [c.obs.resume_text for c in world.candidates]
    a = mb.BM25Matrix(docs)
    b = BM25(dict(enumerate(docs)))
    q = world.needs[0].text
    assert np.allclose(a.scores(q), [b.score(i, q) for i in range(len(docs))])


def test_truth_rules():
    cfg = BenchConfig()
    need = generate(BenchConfig(n_needs=1, n_candidates=30)).needs[0]
    lat = Latent(direction=need.direction, theta=0.5, true_grade=need.grade, known=frozenset(need.required),
                 talent=0.0, persona="honest")
    assert true_relevance(need, lat, cfg) == 3
    assert true_relevance(need, replace(lat, known=frozenset()), cfg) == 1
    other = next(d for d in ("backend", "qa") if d != need.direction)
    assert true_relevance(need, replace(lat, direction=other), cfg) == 0


def test_need_parser_on_generated_texts(world):
    for n in world.needs:
        r = parse_need(n.text, use_llm=False)
        assert r["direction"] == n.direction and r["grade"] == n.grade
        assert set(n.required) <= {i["tag"] for i in r["stack_required"]}


def test_quick_run_sanity():
    rep = mb.run(BenchConfig(n_needs=30, n_candidates=300), quick=True, write=False)
    m = rep["metrics"]
    assert set(m) == set(mb.METHODS)
    for k in m:
        for mt in mb.METRICS:
            assert m[k][mt]["lo"] <= m[k][mt]["mean"] <= m[k][mt]["hi"]
    assert m["platform"]["ndcg@10"]["mean"] > m["random"]["ndcg@10"]["mean"] + 0.2
    assert m["platform"]["p@5"]["mean"] > m["bm25"]["p@5"]["mean"]
    inf = rep["groups"]["inflated"]
    assert inf["platform"]["irrelevant_inflated_top10"] < inf["no_guard"]["irrelevant_inflated_top10"]
    ho = rep["heldout_weights"]
    assert ho["train_needs"] + ho["test_needs"] == 30
    assert sum(ho["weights_tuned"].values()) == pytest.approx(1.0)
    assert ho["world2_seed"] != rep["config"]["seed"]


def test_heldout_split_has_no_overlap():
    n = 31
    perm = np.random.default_rng(5).permutation(n)
    train, test = set(perm[: n // 2]), set(perm[n // 2:])
    assert not train & test and len(train | test) == n
    grid = mb.weight_grid()
    assert np.allclose(grid.sum(1), 1.0) and len(grid) == 1540
    assert any(np.allclose(g, [0.45, 0.35, 0.05, 0.10, 0.05]) for g in grid)  # веса продукта — точка сетки


def test_api_serves_committed_report(client):
    r = client.get("/api/validation/matching-bench")
    assert r.status_code == 200
    d = r.json()
    assert d["world"]["n_pairs"] >= 500 * 50
    assert d["metrics"]["platform"]["ndcg@10"]["mean"] > d["metrics"]["bm25"]["ndcg@10"]["mean"]
    assert d["caveat"] and d["truth_rules"] and d["heldout_weights"]["test"]
