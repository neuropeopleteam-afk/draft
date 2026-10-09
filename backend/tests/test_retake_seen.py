"""И26 (09.10, решение руководителя проекта): при повторе семейства ВСЕХ прошлых попыток кандидата по направлению не берутся ни в
основную часть, ни в дотестирование; если новых семейств нет — запасной путь LRU (виденные давнее всего) с новым
вариантом; первая попытка, экспресс и дотестирование предварительного Junior не ломаются."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.assessment.exposure import AppCATSession
from app.modules.validation import sim
from assessment_bank.simulation import Person, make_responder, make_truth
from tests.conftest import register_and_verify
from tests.test_bank_engine import oracle
from tests.test_day2_rules import H, ONBOARDING, make_demo


@pytest.fixture(scope="module")
def world():
    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    return cfg, pool, make_truth(pool, np.random.default_rng(7), misspec=0.5)


def _session(world, *, subpool, seen=None, seed=1, theta=0.6, pool=None, truth=None, direction="backend"):
    cfg, p0, t0 = world
    pool, truth = pool or p0, truth or t0
    resp = make_responder(Person(theta, 0.0, "middle"), truth)
    sess, res = sim.run_session(pool, direction, resp, cfg, None, "middle", subpool, np.random.default_rng(seed),
                                seen=seen)
    return sess, [a.family_id for a in res.administered if not a.canary]


def _seen(history: list[list[str]]) -> dict[str, int]:
    """history — семейства попыток, последняя первой; возраст — номер самой поздней попытки с семейством."""
    return {f: age for age, fams in reversed(list(enumerate(history))) for f in fams}


def _scored(pool, direction="backend"):
    return [i for i in pool if not i.canary and i.block in ("common", direction)]


def test_without_seen_selection_is_unchanged(world):
    """Первая попытка (seen пуст) и сессии без seen — тот же выбор, что раньше."""
    _, a = _session(world, subpool=0, seen=None, seed=11)
    _, b = _session(world, subpool=0, seen={}, seed=11)
    assert a == b and len(a) >= 8


def test_third_and_fourth_skip_all_previous_while_pool_lasts(world):
    """Банк втрое больше (копии семейств с новыми id): пул не кончается — 2-я, 3-я и 4-я попытки не повторяют
    ни одного семейства прошлых попыток, хотя субпулов два и 3-я снова идёт в субпул 1-й."""
    cfg, pool, _ = world
    big = pool + [replace(i, family_id=f"{i.family_id}~{k}") for k in (1, 2) for i in pool if not i.canary]
    truth = make_truth(big, np.random.default_rng(3), misspec=0.5)
    for person in range(4):
        hist: list[list[str]] = []
        for att in range(4):
            sess, fams = _session(world, subpool=att % 2, seen=_seen(hist), seed=100 * person + att,
                                  theta=-0.5 + 0.5 * person, pool=big, truth=truth)
            prev = {f for h in hist for f in h}
            assert not set(fams) & prev, (person, att, set(fams) & prev)
            assert len(fams) >= cfg.min_items
            hist.insert(0, fams)


def test_main_part_lru_takes_oldest_after_all_new_ones(world):
    """Новых семейств мало: сначала берутся все доступные новые (свой субпул, затем другой), затем — виденные давнее
    всего (возраст 2), а семейства последней попытки (возраст 0) не берутся, пока есть старшие."""
    _, pool, _ = world
    fams = [i.family_id for i in _scored(pool)]
    new = set(fams[::12])  # ~6 новых семейств на ~70
    rest = [f for f in fams if f not in new]
    seen = {f: (2 if k % 2 == 0 else 0) for k, f in enumerate(rest)}
    sess, order = _session(world, subpool=0, seen=seen, seed=5)
    picked_new = [k for k, f in enumerate(order) if f in new]
    first_seen = next(k for k, f in enumerate(order) if f in seen)
    assert picked_new and max(picked_new) < first_seen  # новые — раньше любых виденных
    assert all(seen[f] == 2 for f in order if f in seen)  # LRU: только виденные давнее всего
    assert sess.n_scored >= sess.cfg.min_items


def test_extension_lru_skips_last_attempt_and_confirm_takes_all(world):
    """Дотестирование у порога: новых коротких нет — LRU только из попыток до последней; у дотестирования
    предварительного Junior (ext_lru) — по всем, чтобы оно не кончилось без заданий."""
    cfg, pool, _ = world
    fams = [i.family_id for i in _scored(pool)]
    only_last = {f: 0 for f in fams}
    s = AppCATSession(pool, "backend", cfg.cat(), None, "middle", 0, np.random.default_rng(1), seen=only_last)
    assert s._ext_candidates() == []
    s2 = AppCATSession(pool, "backend", cfg.cat(), None, "middle", 0, np.random.default_rng(1),
                       seen={f: k % 3 for k, f in enumerate(fams)})
    ext = s2._ext_candidates()
    assert ext and {s2.seen[i.family_id] for i in ext} == {2}
    s3 = AppCATSession(pool, "backend", cfg.cat(), None, "junior", 0, np.random.default_rng(1), seen=only_last,
                       ext_lru=True)
    assert s3._ext_candidates()


def test_lru_respects_blocks_and_quarantine(world):
    """Запасной путь не берёт субпул на карантине и канарейки; блоки — общий и направление — по отдельности."""
    cfg, pool, _ = world
    fams = [i for i in _scored(pool)]
    seen = {i.family_id: (1 if i.subpool == 1 else 3) for i in fams}
    s = AppCATSession(pool, "backend", cfg.cat(), None, "middle", 0, np.random.default_rng(2), seen=seen,
                      blocked_subpools={1})
    c = s._candidates()
    assert c and all(not i.canary and i.subpool == 0 for i in c)
    assert {i.block for i in c} == {"common", "backend"}


# ------------------------------------------------------------------ движок банка: экспресс и полный тест при исчерпании

@pytest.fixture
def bank(monkeypatch):
    from app.core.config import get_settings
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.grader import GradeOutcome

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm"))
    return be.BankEngine()


def _drive(bank, st):
    while (item := bank.next_item(st)) is not None:
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        assert bank.answer(st, item.item_id, oracle(it, item.step or 1, True), 1500, step=item.step).accepted
    return bank.finish(st)


@pytest.mark.parametrize("mode", ["express", "full"])
def test_engine_all_seen_falls_back_to_lru_with_new_variants(bank, mode):
    """Все семейства направления уже видены: экспресс и полный тест всё равно идут (LRU), задания — новые варианты."""
    probe = bank.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=3, mode=mode)
    sess = bank._rebuild(probe)
    fams = [f for f, i in sess.items.items() if not i.canary]
    seen = {f: k % 2 for k, f in enumerate(fams)}
    seeds = {f: [10_000_123, 20_000_456] for f in fams}
    st = bank.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=3, mode=mode, seen=seen,
                    seen_seeds=seeds)
    assert st["seen"] == seen and st["exclude_ext"] == []
    res = _drive(bank, st)
    scored = [i for i in st["items"] if not i["canary"]]
    assert len(scored) >= (5 if mode == "express" else st["cfg"]["min_items"]), res.details
    assert all(i["repeat"] for i in scored) and all(i["seed"] not in seeds[i["family_id"]] for i in scored)
    if mode == "express":
        assert res.details["mode"] == "express" and res.details["extension"] is None


def test_service_passes_all_previous_attempts_with_age(client, bank):
    """Сервис: seen — семейства всех завершённых попыток по направлению (0 — последняя), seed — для новых
    вариантов; 2-я не повторяет 1-ю; повтор семейства в 3-й и 4-й — только с пометкой repeat и новым вариантом."""
    from app.modules.assessment.attempts import attempt_view, finished_attempts
    from app.modules.auth.models import User
    from app.modules.jury.seed import run_demo_test

    email = "seen-attempts@example.com"
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    make_demo(email)
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == email))
        for k in range(4):
            run_demo_test(db, uid, "middle", 0.9, 8801 + k)
        rows = finished_attempts(db, uid, "backend")
        states = [r.result["state"] for r in rows]
        views = [attempt_view(r) for r in rows]
    fam = [{i["family_id"] for i in st["items"] if not i["canary"]} for st in states]
    assert states[0]["seen"] == {} and not fam[0] & fam[1]
    last = states[3]["seen"]
    for f in fam[2]:
        assert last[f] == 0
    for f in fam[0] - fam[1] - fam[2]:
        assert last[f] == 2
    assert set(states[3]["seen_seeds"]) == set(last)
    for k in (2, 3):
        prev = set().union(*fam[:k])
        for i in states[k]["items"]:
            if not i["canary"] and i["family_id"] in prev:
                assert i["repeat"] and i["seed"] not in states[k]["seen_seeds"][i["family_id"]]
    assert [v["subpool"] for v in views[:3]] in ([0, 1, 0], [1, 0, 1])
