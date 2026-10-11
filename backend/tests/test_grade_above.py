"""Я12б (11.10): добор ступенью выше при малом пуле точного уровня (grade_above, match-v1.3, MATCH_GRADE_ABOVE)."""
import uuid

import numpy as np

from app.modules.matching import grade_above as GA
from app.modules.matching.need_parser import parse_need


def _recs(exact=5, above=12):
    return [{"id": "backend.middle", "title": "Backend · Middle", "count": exact, "relation": "exact"},
            {"id": "backend.junior", "title": "Backend · Junior", "count": 40, "relation": "below"},
            {"id": "backend.senior", "title": "Backend · Senior", "count": above, "relation": "above"}]


def test_applies_only_for_small_exact_pool_without_manual_categories(monkeypatch):
    monkeypatch.delenv(GA.FLAG, raising=False)
    assert GA.enabled()  # по умолчанию включено
    got = GA.applies(_recs(), {})
    assert got["exact"]["id"] == "backend.middle" and got["above"]["id"] == "backend.senior"
    assert GA.applies(_recs(exact=GA.MIN_EXACT), {}) is None  # пул точного уровня достаточен — порядок прежний
    assert GA.applies(_recs(above=0), {}) is None  # на ступень выше никого
    assert GA.applies(_recs(), {"categories": ["backend.middle"]}) is None  # работодатель выбрал категории сам
    assert GA.applies([r for r in _recs() if r["relation"] != "exact"], {}) is None  # нет уровня — нет точной
    assert GA.applies([{"id": "backend.senior", "title": "x", "count": 3, "relation": "direction"}], {}) is None
    monkeypatch.setenv(GA.FLAG, "0")
    assert not GA.enabled() and GA.applies(_recs(), {}) is None


def test_merge_keeps_best_exact_first():
    a, b, c, d = object(), object(), object(), object()
    assert GA.merge([a, b], [c, a, d, b]) == [a, b, c, d]
    assert GA.merge([a], [c, a, d]) == [a, c, d]
    assert GA.merge([], [c, d]) == [c, d]


def test_above_category_and_text():
    assert GA.above_category({"direction": "frontend", "grade": "intern"}) == "frontend.junior"
    assert GA.above_category({"direction": "backend", "grade": "middle"}) == "backend.senior"
    assert GA.above_category({"direction": "backend", "grade": "senior"}) is None
    assert GA.above_category({"direction": "backend", "grade": None}) is None
    info = GA.applies(_recs(), {})
    m = GA.meta(info, [{"category_id": "backend.senior"}, {"category_id": "backend.middle"}])
    assert m["applied"] and m["in_top5"] == 1 and m["min_exact"] == 30 and m["keep"] == 2
    assert "меньше 30" in m["text"] and "на ступень выше" in m["text"] and "никогда" not in m["text"]
    assert GA.meta(None, []) == {"on": True, "applied": False}


def _world(client):
    """Точный уровень (Backend · Middle): x — без Kafka; уровень выше (Backend · Senior): s — PostgreSQL и Kafka."""
    from sqlalchemy import delete

    from app.core.db import SessionLocal
    from app.modules.profiles.facts import set_t0_facts
    from app.modules.profiles.models import CandidateFact, EvidenceLevel, FactSource
    from tests.test_day2_rules import H, candidate_with_category

    plan = {"x": ("middle", {"postgresql": 1.0}), "y": ("middle", {"postgresql": 0.67}),
            "s": ("senior", {"postgresql": 1.0, "kafka": 1.0})}
    refs = {}
    for name, (grade, skills) in plan.items():
        t = candidate_with_category(client, email=f"above_{name}@example.com", grade=grade)
        me = client.get("/api/me", headers=H(t)).json()
        uid = uuid.UUID(me["id"])
        with SessionLocal() as db:
            db.execute(delete(CandidateFact).where(CandidateFact.user_id == uid, CandidateFact.kind == "skill"))
            set_t0_facts(db, uid, FactSource.self_report, stack=list(skills))
            set_t0_facts(db, uid, FactSource.resume, stack=[])
            for tag, sc in skills.items():
                db.add(CandidateFact(user_id=uid, kind="skill", key=tag, title=tag, evidence_level=EvidenceLevel.T1,
                                     source=FactSource.test, value={"direction": "backend", "score": sc,
                                                                    "correct": round(sc * 3), "total": 3}))
            db.commit()
        refs[name] = me["candidate"]["public_ref"]
    return refs


def _selection(filters=None):
    from app.core.db import SessionLocal
    from app.modules.matching import ranking

    req = parse_need("Backend-разработчик middle: обязательно PostgreSQL и Kafka.", use_llm=False)
    req["grade"] = "middle"
    with SessionLocal() as db:
        return ranking.build_selection(db, req, {"conditions_off": True, **(filters or {})})


def test_selection_adds_above_grade_after_best_exact(client, monkeypatch):
    refs = _world(client)
    monkeypatch.setenv(GA.FLAG, "0")
    off = _selection()
    assert refs["s"] not in [r["ref"] for r in off["results"]] and not off["grade_above"]["applied"]
    monkeypatch.setenv(GA.FLAG, "1")
    on = _selection()
    order = [r["ref"] for r in on["results"]]
    assert on["grade_above"]["applied"] and on["algorithm"] == GA.ALGORITHM
    assert refs["s"] in order
    # первые KEEP мест — лучшие точного уровня; кандидат уровнем выше (покрывает всё обязательное) — сразу за ними
    assert order.index(refs["x"]) < order.index(refs["s"]) and order.index(refs["y"]) < order.index(refs["s"])
    rs = next(r for r in on["results"] if r["ref"] == refs["s"])
    assert rs["category_id"] == "backend.senior" and "на ступень выше" in rs["reasons"][0]["text"]
    cats = {c["id"]: c for c in on["categories"]}
    assert cats["backend.senior"]["in_pool"] and cats["backend.middle"]["in_pool"] and not cats["backend.junior"]["in_pool"]
    # работодатель снял галочку — только точный уровень, как раньше
    manual = _selection({"categories": ["backend.middle"]})
    assert refs["s"] not in [r["ref"] for r in manual["results"]] and not manual["grade_above"]["applied"]


def test_bench_orders_follow_rule():
    """platform_orders(above=True): первые KEEP — лучшие точного уровня (vis 2), затем общий порядок по ярусу
    обязательного, точный раньше при равном ярусе; без above_on — прежний порядок."""
    from app.modules.validation.matching_bench import COMP_KEYS, platform_orders

    m = 5
    comps = np.zeros((1, m, len(COMP_KEYS)))
    comps[0, :, 0] = [0.9, 0.8, 0.7, 0.95, 0.6]  # тест
    sc = {"comps": comps, "has_req": np.array([True]), "provisional": np.zeros(m), "rating": np.zeros(m),
          "ref_rank": np.arange(m), "vis": np.array([[2, 2, 2, 1, 1]], dtype=np.int8),
          "must_tier": np.array([[1, 1, 1, 0, 0]], dtype=np.int8), "core_absent": np.zeros((1, m), dtype=np.int8),
          "above": np.array([[False, False, False, True, False]]), "above_on": np.array([True]),
          "must_tier_wide": np.array([[1, 1, 1, 0, 0]], dtype=np.int8),
          "core_absent_wide": np.zeros((1, m), dtype=np.int8)}
    before = platform_orders(sc, above=False, core=False, must_first=True)[0]
    after = platform_orders(sc, above=True, core=False, must_first=True)[0]
    assert list(before[:3]) == [0, 1, 2]
    assert list(after[:4]) == [0, 1, 3, 2]  # 3 — уровень выше и покрывает всё: сразу после двух лучших точных
    sc["above_on"] = np.array([False])
    assert list(platform_orders(sc, above=True, core=False, must_first=True)[0]) == list(before)
