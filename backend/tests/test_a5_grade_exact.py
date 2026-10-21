"""Выбор работодателя «строго запрошенный грейд» (filters.grade_exact, match-v2; по умолчанию выключен).

Внутри яруса статуса грейда и ступени стека кандидаты идут по вероятности (по θ и SE теста), что уровень именно
запрошенный; никто не скрывается; у каждого с тестом — причина с этой вероятностью. Без выбора порядок — прежний.
"""
from __future__ import annotations

import pytest

from app.modules.matching import ltr, ranking
from app.modules.matching.need_parser import parse_need
from app.modules.validation import bench_world as bw

R = "Строго запрошенный грейд"


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    monkeypatch.setenv("MATCH_V2", "1")


@pytest.fixture(scope="module")
def world():
    w = bw.generate(bw.BenchConfig(seed=20261006, n_needs=8, n_candidates=500))
    bundles = [bw.build_bundle(c.obs, "platform") for c in w.candidates]
    for b in bundles:
        b.profile.city, b.profile.relocation = "Москва", False
    return w, bundles


def _cases(world):
    w, bundles = world
    for n in w.needs:
        req = parse_need(n.text, use_llm=False)
        cat = f"{req['direction']}.{req['grade']}"
        pool = [b for b in bundles if b.profile.current_category_id == cat]
        if len(pool) >= 5:
            yield req, pool


def test_default_off_keeps_order(world):
    checked = 0
    for req, pool in _cases(world):
        a, ia = ranking.order_bundles(pool, req, {})
        b, _ = ranking.order_bundles(pool, req, {"grade_exact": False})
        assert [x[1].profile.public_ref for x in a] == [x[1].profile.public_ref for x in b]
        assert ia["grade_exact"]["on"] is False and ia["grade_exact"]["with_test"] == 0
        assert not any(r.get("requirement") == R for x in a for r in x[3])
        checked += 1
    assert checked >= 3


def test_exact_orders_by_probability_nobody_hidden(world):
    changed = 0
    for req, pool in _cases(world):
        base, _ = ranking.order_bundles(pool, req, {})
        scored, info = ranking.order_bundles(pool, req, {"grade_exact": True})
        assert len(scored) == len(base), "выбор не скрывает кандидатов"
        assert sorted(x[1].profile.public_ref for x in scored) == sorted(x[1].profile.public_ref for x in base)
        assert info["grade_exact"]["on"] is True
        tags = ltr.required_tags(req)
        groups: dict = {}
        for x in scored:
            p = ranking.p_exact(x[1], req)
            reasons = [r for r in x[3] if r.get("requirement") == R]
            if p is None:
                assert not reasons
                continue
            assert 0.0 <= p <= 1.0 and len(reasons) == 1 and reasons[0]["p_exact"] == p
            assert f"{round(p * 100)} %" in reasons[0]["text"]
            k = (ranking.tier(x[1]), ltr.stack_step(ltr.stack_coverage(x[1], tags)))
            groups.setdefault(k, []).append(p)
        for ps in groups.values():
            assert ps == sorted(ps, reverse=True), "в ярусе и ступени стека — по вероятности «именно этот грейд»"
        changed += int([x[1].profile.public_ref for x in scored] != [x[1].profile.public_ref for x in base])
    assert changed > 0, "в мирах разработки выбор меняет порядок"


def test_probability_is_band_mass():
    class T:  # минимальный пакет: только тест
        value = {"theta": 0.5, "se": 0.3}

    class B:
        test = T()

    p = ranking.p_exact(B(), {"grade": "middle"})  # полоса Middle: [0; 1)
    assert 0.85 < p < 0.95
    T.value = {"theta": 1.6, "se": 0.3}
    assert ranking.p_exact(B(), {"grade": "middle"}) < 0.1  # уже за порогом Senior
    T.value = {}
    assert ranking.p_exact(B(), {"grade": "middle"}) is None
