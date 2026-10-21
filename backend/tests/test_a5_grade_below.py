"""Мягкий запасной режим подборки (match-v2, цикл №4): точного уровня меньше 10 — подтверждённые ступенью ниже идут
после всех кандидатов точного уровня и до яруса «грейд не подтверждён», с причиной; флаг MATCH_GRADE_BELOW=0 — как раньше.
Пул собирает тот же код, что бенчмарк (tools/realdata/bench2.pool_for ↔ ranking.build_selection)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.modules.matching import grade_above, ranking
from app.modules.matching.need_parser import parse_need
from app.modules.validation import bench_world as bw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "realdata"))


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    monkeypatch.setenv("MATCH_V2", "1")


@pytest.fixture(scope="module")
def small():
    w = bw.generate(bw.BenchConfig(seed=20261006, n_needs=10, n_candidates=150))  # ~7 на категорию — режим действует
    bundles = [bw.build_bundle(c.obs, "platform") for c in w.candidates]
    for b in bundles:
        b.profile.city, b.profile.relocation = "Москва", False
    return w, bundles


def _reqs(w):
    import bench2

    return [parse_need(bench2._strip_format(n).text, use_llm=False) for n in w.needs]  # без условий формата, как бенч


def test_below_after_exact_before_unconfirmed_with_reason(small):
    import bench2

    w, bundles = small
    applied = 0
    for req in _reqs(w):
        bcat = grade_above.below_category(req)
        idx, above_id = bench2.pool_for(bundles, req)
        sub = [bundles[k] for k in idx]
        if not bcat or not any(b.category_id == bcat for b in sub):
            continue
        n_exact = sum(1 for b in bundles if b.profile.current_category_id == f"{req['direction']}.{req['grade']}")
        assert n_exact < grade_above.MIN_EXACT_BELOW
        assert all(not b.provisional for b in sub if b.category_id == bcat), "ступенью ниже — только подтверждённые"
        scored, info = ranking.order_bundles(sub, req, {}, above_id=above_id)
        assert info["grade_below"]["applied"] and info["grade_below"]["category"] == bcat
        kinds = []
        for x in scored:
            b = x[1]
            is_below = b.category_id == bcat
            has_reason = any(r.get("requirement") == grade_above.BELOW_REASON_REQ for r in x[3])
            assert has_reason == is_below
            kinds.append(2 if ranking.tier(b) > 0 else (1 if is_below else 0))
        assert kinds == sorted(kinds), "точный уровень → ступенью ниже → «не подтверждён»"
        applied += 1
    assert applied >= 2


def test_flag_off_and_large_pool_unchanged(small, monkeypatch):
    import bench2

    w, bundles = small
    for req in _reqs(w):
        bcat = grade_above.below_category(req)
        monkeypatch.setenv(grade_above.FLAG_BELOW, "0")
        idx0, _ = bench2.pool_for(bundles, req)
        monkeypatch.delenv(grade_above.FLAG_BELOW)
        idx_nob, _ = bench2.pool_for(bundles, req, below=False)
        assert idx0 == idx_nob
        assert not bcat or not any(bundles[k].category_id == bcat for k in idx0)
    # большой пул (≥ 10 точного уровня) — режим не включается
    assert grade_above.below_applies({"direction": "backend", "grade": "middle"}, 10, 5) is None
    assert grade_above.below_applies({"direction": "backend", "grade": "middle"}, 9, 5) == "backend.junior"
    assert grade_above.below_applies({"direction": "backend", "grade": "middle"}, 9, 0) is None
    assert grade_above.below_applies({"direction": "backend", "grade": "middle"}, 9, 5, {"categories": ["x"]}) is None
    assert grade_above.below_category({"direction": "backend", "grade": "intern"}) is None


def test_employer_categories_never_marked_below(small):
    w, bundles = small
    req = {"direction": "backend", "grade": "middle"}
    pool = [b for b in bundles if b.category_id in ("backend.middle", "backend.junior")]
    if not any(b.category_id == "backend.junior" for b in pool):
        pytest.skip("в малом мире нет backend.junior")
    _, info = ranking.order_bundles(pool, req, {"categories": ["backend.middle", "backend.junior"]})
    assert info["grade_below"]["applied"] is False
