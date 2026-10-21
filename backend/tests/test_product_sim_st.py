"""Поправка №3 протокола (21.10): «стандартные условия» S-T по параметрам А15 и метрики 6/5/4 грейдов.

Проверяем то, на чём держатся цифры строки S-T: популяция θ ~ N(0,5; 1,0) без класса «ниже Стажёра», доли заявок
65/25/10, истина семейства a × U(0,825; 1,175) и b + N(0; 0,3), склейка шкал для сопоставимости 5 и 4 грейдов.
"""
import numpy as np
import pytest

from app.modules.catalog.seed_data import ALL_GRADE_CUTS
from app.modules.validation import product_sim as ps


def test_merge_scales():
    assert [ps._merge5(g) for g in ps.ORDER_ALL] == [0, 1, 2, 3, 4, 5, 5]
    # 4 ступени: Стажёр = Junior, Lead = Principal; «ниже Стажёра» остаётся отдельно
    assert [ps._merge4(g) for g in ps.ORDER_ALL] == [0, 2, 2, 3, 4, 5, 5]


def test_st_world_family_truth_ranges_and_determinism():
    w = ps.World(5501, "st")
    vals = [w.family_truth(f"fam{i}") for i in range(400)]
    am = np.array([v[0] for v in vals])
    bs = np.array([v[1] for v in vals])
    assert am.min() >= ps.ST_A_RANGE[0] and am.max() <= ps.ST_A_RANGE[1]
    assert abs(bs.mean()) < 0.06 and 0.25 < bs.std() < 0.35
    assert ps.World(5501, "st").family_truth("fam7") == vals[7]  # зависит только от зерна мира и семейства
    assert ps.World(5502, "st").family_truth("fam7") != vals[7]


@pytest.fixture(scope="module")
def st_people():
    sim = ps.Sim(ps.World(5501, "st"), population="st")
    sim.r_pop = np.random.default_rng([5501, 99])
    return [sim.person() for _ in range(3000)]


def test_st_population(st_people):
    th = np.array([p["theta"] for p in st_people])
    assert th.min() >= ALL_GRADE_CUTS["intern"]  # ниже Стажёра — перевыбор
    assert 0.40 < th.mean() < 0.65
    assert all(p["true_grade"] != "none" for p in st_people)
    rank = {g: i for i, g in enumerate(ps.ORDER_ALL)}
    sh = np.array([rank[p["claim"]] - rank[p["true_grade"]] for p in st_people])
    assert set(np.unique(sh)) <= {-1, 0, 1}
    # 65/25/10 — у кандидатов не на краю шкалы направления (на краях заявка точная); допуск на выборку
    inner = np.array([1 < p["order"].index(p["true_grade"]) < len(p["order"]) - 1 for p in st_people])
    assert inner.sum() > 1000
    si = sh[inner]
    assert 0.61 < (si == 0).mean() < 0.69
    assert 0.21 < (si == 1).mean() < 0.29
    assert 0.07 < (si == -1).mean() < 0.13
    edge_top = np.array([p["order"].index(p["true_grade"]) == len(p["order"]) - 1 for p in st_people])
    assert not (sh[edge_top] == 1).any()  # выше верхней ступени заявки нет


def test_st_phase_guard():
    with pytest.raises(SystemExit):
        ps.main(["--phase", "st", "--seeds", "5501", "--n", "1", "--world", "calibrated", "--population", "st",
                 "--bank-a", "mcq=1.5,code=1.5", "--out", "/tmp/_st_guard.json"])
