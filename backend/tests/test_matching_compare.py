"""Подбор при других условиях измерения (make match-bench-compare): шкалы A и B, ручки мира, флаг MATCH_GRADE_CAP."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from app.modules.catalog.seed_data import GRADE_CUTS
from app.modules.matching.ranking import grade_cap, grade_cap_enabled
from app.modules.profiles.facts import test_component as tcomp
from app.modules.validation import matching_bench as mb
from app.modules.validation import matching_compare as mc
from app.modules.validation.bench_world import (COMPARE_KNOBS, BenchConfig, Latent, NeedSpec, generate,
                                                relevance_label2, relevance_utility, true_relevance)

REPO = Path(__file__).resolve().parents[2]


def _need(grade="middle", required=("python", "sql")):
    return NeedSpec(idx=0, direction="backend", grade=grade, required=list(required), desired=[], work_format=None,
                    text="")


def _lat(grade="middle", theta=None, known=("python", "sql"), direction="backend"):
    theta = GRADE_CUTS[grade] + 0.9 if theta is None and grade else (theta if theta is not None else -2.5)
    return Latent(direction=direction, theta=theta, true_grade=grade, known=frozenset(known), talent=0.0,
                  persona="honest")


def test_strict_protocol_config_and_hash_unchanged():
    """Ручки других условий измерения в значениях по умолчанию не попадают в конфигурацию: hash строгого протокола тот же,
    что записан в docs/validation/matching_bench.json (make bench)."""
    d = BenchConfig().to_dict()
    assert not set(COMPARE_KNOBS) & set(d)
    rec = json.loads((REPO / "docs/validation/matching_bench.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12] == rec["config_hash"]
    assert "claim_over" in replace(BenchConfig(), claim_over=0.25).to_dict()


def test_default_knobs_do_not_change_world():
    small = BenchConfig(n_needs=6, n_candidates=60)
    a = generate(small)
    b = generate(replace(small, need_required=(2, 4), theta_model="normal", t0_model="personas"))
    assert np.array_equal(a.rel, b.rel)
    assert [c.obs for c in a.candidates] == [c.obs for c in b.candidates]


def test_relevance_utility_hand_cases():
    n = _need()
    assert relevance_utility(n, _lat("middle")) == 3  # точный грейд, всё обязательное, сильный внутри грейда
    assert relevance_utility(n, _lat("middle", theta=GRADE_CUTS["middle"])) == 3  # 1 · 1 · 0,85 = 0,85
    assert relevance_utility(n, _lat("senior")) == 2  # на ступень выше: 0,75
    assert relevance_utility(n, _lat("junior")) == 1  # на ступень ниже: 0,45
    assert relevance_utility(n, _lat("intern")) == 0
    assert relevance_utility(n, _lat("middle", known=("python",))) == 2  # (0,25 + 0,375) · 1,12 = 0,70
    assert relevance_utility(n, _lat("middle", known=())) == 0  # 0,25 · 1,12 < 0,4
    assert relevance_utility(n, _lat("middle", direction="frontend")) == 0
    assert relevance_utility(n, _lat(None)) == 0


def test_relevance_label2_hand_cases():
    n = _need(required=("python", "sql", "docker"))
    assert relevance_label2(n, _lat("middle", known=("docker",))) == 2
    assert relevance_label2(n, _lat("middle", known=())) == 1
    assert relevance_label2(n, _lat("senior", known=("sql",))) == 1
    assert relevance_label2(n, _lat("junior", known=())) == 0
    assert relevance_label2(n, _lat("intern", known=("sql",))) == 0
    assert relevance_label2(n, _lat("middle", known=("sql",), direction="qa")) == 0
    cfg = replace(BenchConfig(), truth="label2")
    assert true_relevance(n, _lat("middle", known=("docker",)), cfg) == 2


def test_compare_world_knobs():
    wa = next(c for c in mc.CONDITIONS if c["id"] == "util_world")
    cfg = replace(BenchConfig(n_needs=20, n_candidates=200), **wa["cfg"])
    w = generate(cfg)
    assert {c.latent.direction for c in w.candidates} <= set(cfg.dirs)
    assert {n.direction for n in w.needs} <= set(cfg.dirs)
    assert {n.grade for n in w.needs} <= {"junior", "middle", "senior"}
    assert all(c.latent.true_grade in ("junior", "middle", "senior") for c in w.candidates)  # θ* в полосах грейдов
    assert set(np.unique(w.rel)) <= {0, 1, 2, 3}
    wb = next(c for c in mc.CONDITIONS if c["id"] == "label2_world")
    w2 = generate(replace(BenchConfig(n_needs=10, n_candidates=100), **wb["cfg"]))
    assert all(len(n.required) == 3 for n in w2.needs)
    assert set(np.unique(w2.rel)) <= {0, 1, 2}
    # приписки: у части кандидатов в резюме навыки, которыми они не владеют
    stuffed = [c for c in w2.candidates if set(c.obs.stack_declared) - set(c.latent.known)]
    assert 0 < len(stuffed) < len(w2.candidates)


def test_grade_cap_flag(monkeypatch):
    monkeypatch.delenv("MATCH_GRADE_CAP", raising=False)
    assert not grade_cap_enabled()
    assert grade_cap(0.95, "middle") == 0.95  # по умолчанию выключено
    cap = tcomp(GRADE_CUTS["senior"], None, "middle")
    assert grade_cap(0.95, "middle", True) == cap == 0.846
    assert grade_cap(0.5, "middle", True) == 0.5
    assert grade_cap(0.99, "senior", True) == 0.99  # следующего грейда нет
    assert grade_cap(0.95, None, True) == 0.95
    monkeypatch.setenv("MATCH_GRADE_CAP", "1")
    assert grade_cap_enabled() and grade_cap(0.95, "junior") == tcomp(GRADE_CUTS["middle"], None, "junior")


def test_grade_cap_changes_only_test_component(monkeypatch):
    w = generate(BenchConfig(n_needs=6, n_candidates=60))
    reqs = mb._parsed(w)
    monkeypatch.delenv("MATCH_GRADE_CAP", raising=False)
    base = mb.score_world(w, reqs)
    capped = mc.scored_with_flag(w, reqs, {"MATCH_GRADE_CAP": "1"})
    import os
    assert "MATCH_GRADE_CAP" not in os.environ  # флаг снят после расчёта
    t = mb.COMP_KEYS.index("test")
    others = [i for i in range(len(mb.COMP_KEYS)) if i != t]
    assert np.array_equal(base["comps"][..., others], capped["comps"][..., others])
    assert (capped["comps"][..., t] <= base["comps"][..., t] + 1e-12).all()
    assert np.array_equal(base["vis"], capped["vis"]) and np.array_equal(base["must_tier"], capped["must_tier"])
    assert capped["max_rebuild_error"] < 1e-3


def test_compare_quick_run_and_report():
    rep = mc.run(quick=True, write=False, only=["ours_strict", "util_world"])
    assert [c["id"] for c in rep["conditions"]] == ["ours_strict", "util_world"]
    alt = rep["conditions"][1]
    assert set(alt["metrics"]) >= {"platform", "bm25", "keywords_grade", "random", "no_test", "no_guard"}
    for m in mc.METRICS4:
        assert 0 <= alt["metrics"]["platform"][m]["mean"] <= 1
    d = alt["diagnostics"]
    assert abs(sum(d["top10_label_mix"]) - 1) < 0.01 and abs(sum(d["ideal10_label_mix"]) - 1) < 0.01
    assert d["ndcg10_top10_resorted_by_truth"] >= d["ndcg10"] - 1e-9  # пересортировка по истине не ухудшает
    assert d["oracle_within_tiers"]["mrr"] >= alt["metrics"]["platform"]["mrr"]["mean"] - 1e-9
    assert set(rep["not_worse"]) == set(mc.VARIANTS) and rep["not_worse"]["grade_cap"]["checked"]
    md = mc.markdown(rep)
    for part in ("# Подбор при других условиях измерения", "## Почему nDCG@10 ниже MRR", "правило «не хуже»",
                 "модель, не люди", "Условия A"):
        assert part in md
    assert "published" not in rep and not hasattr(mc, "PUBLISHED")


def test_makefile_target():
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "match-bench-compare:" in mk and "app.modules.validation.matching_compare" in mk


@pytest.mark.parametrize("cid", [c["id"] for c in mc.CONDITIONS])
def test_conditions_are_valid_configs(cid):
    c = next(x for x in mc.CONDITIONS if x["id"] == cid)
    cfg = replace(BenchConfig(), **c["cfg"])
    assert cfg.n_needs > 0 and cfg.n_candidates > 0
    assert c["alt"] in (None, "util", "label2")
