"""Я26: двухэтапное подтверждение уровня у границы — правило, вторая сессия банка, продукт за флагом
ASSESSMENT_TWO_STAGE_ENABLED (итог кандидата, карточка работодателя), симуляция «одна сессия / две сессии»."""
import json
import random
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.assessment import two_stage as ts
from tests.conftest import register_and_verify
from tests.test_day2_rules import ONBOARDING, H


@pytest.fixture
def flag(monkeypatch):
    def set_(on: bool, **kw):
        monkeypatch.setenv("ASSESSMENT_TWO_STAGE_ENABLED", "true" if on else "false")
        for k, v in kw.items():
            monkeypatch.setenv(f"ASSESSMENT_TWO_STAGE_{k.upper()}", str(v))
        get_settings.cache_clear()
    yield set_
    get_settings.cache_clear()


# ---------------------------------------------------------------- правило

def test_flag_off_by_default():
    get_settings.cache_clear()
    assert get_settings().assessment_two_stage_enabled is False
    assert ts.params()["enabled"] is False


def test_boundary_between_result_and_claimed():
    # подтверждён Middle, P(θ ≥ 0) ≈ 0,6 — «уровень под вопросом» у порога Middle
    b = ts.boundary(0.1, 0.4, "middle", "middle", level=0.8)
    assert b and b.cut_grade == "middle" and b.kind == "keep" and b.lower == "junior"
    # не подтвердил Middle, принят Junior, P(Middle) ≈ 0,4 — «возможно выше» у порога Middle
    b = ts.boundary(-0.1, 0.4, "junior", "middle", level=0.8)
    assert b and b.cut_grade == "middle" and b.kind == "up"
    # уверенно внутри уровня — уточнять нечего
    assert ts.boundary(0.6, 0.3, "middle", "middle", level=0.8) is None
    # выше заявленного — только в режиме above (по умолчанию выкл.)
    assert ts.boundary(1.2, 0.3, "middle", "middle", level=0.8) is None
    b = ts.boundary(1.2, 0.3, "middle", "middle", level=0.8, above=0.6)
    assert b and b.kind == "above" and b.cut_grade == "senior"
    assert ts.boundary(None, 0.3, "middle") is None


def test_final_grade_anchored_on_claimed():
    # до заявленного — P ≥ c₂, выше — P ≥ c↑
    assert ts.final_grade(0.05, 0.35, "middle", 0.5, 0.9) == "middle"
    assert ts.final_grade(-0.05, 0.35, "middle", 0.5, 0.9) == "junior"
    assert ts.final_grade(1.1, 0.3, "middle", 0.5, 0.9) == "middle"  # P(Senior) ≈ 0,63 < 0,9
    assert ts.final_grade(1.6, 0.3, "middle", 0.5, 0.9) == "senior"
    assert ts.final_grade(-3.0, 0.3, "junior", 0.5, 0.9) == "none"


def test_card_note_texts(flag):
    flag(True)
    v = {"two_stage": {"status": "passed", "label": "на границе Middle/Senior", "final_grade": "senior"}}
    assert ts.card_note(v)["text"].startswith("На границе Middle/Senior — уточнение пройдено")
    v["two_stage"].update(status="failed", final_grade="middle")
    assert "не пройдено" in ts.card_note(v)["text"]
    v["two_stage"]["status"] = "offered"
    assert "не проходил" in ts.card_note(v)["text"]
    flag(False)
    assert ts.card_note(v) is None


def test_card_note_oral_defense_changes_mark_not_level(flag, monkeypatch):
    """п. 4: устная защита (модуль interview) меняет пометку «на границе», уровень — нет."""
    flag(True)
    base = {"two_stage": {"status": "offered", "label": "на границе Junior/Middle", "grade_before": "junior"},
            "grade": "junior"}
    monkeypatch.setenv("INTERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    assert ts.card_note({**base, "defense": {"verdict": "confirmed"}})["oral"] is None
    monkeypatch.setenv("INTERVIEW_ENABLED", "true")
    get_settings.cache_clear()
    n = ts.card_note({**base, "defense": {"verdict": "confirmed"}})
    assert n["oral"] == "confirmed" and n["text"] == "На границе Junior/Middle — подтверждено устной защитой"
    n = ts.card_note({**base, "defense": {"verdict": "discrepancies"}})
    assert n["oral"] == "check" and n["text"].endswith("требует проверки")
    assert ts.card_note({**base, "defense": {"verdict": "insufficient"}})["oral"] is None
    assert ts.card_note({**base, "defense": {"verdict": "confirmed", "example": True}})["oral"] is None
    done = {**base, "two_stage": {**base["two_stage"], "status": "passed", "final_grade": "middle"},
            "defense": {"verdict": "discrepancies"}}
    n = ts.card_note(done)
    assert "уточнение пройдено" in n["text"] and n["text"].endswith("устная защита: требует проверки")
    assert n["final_grade"] == "middle"  # уровень — по тесту


# ---------------------------------------------------------------- вторая сессия банка

def _run(eng, st, rnd, target, oracle):
    while True:
        item = eng.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        good = rnd.random() < (0.85 if it["theta_before"] < target else 0.3)
        assert eng.answer(st, item.item_id, oracle(it, item.step or 1, good), 1000, step=item.step).accepted
    return eng.finish(st)


def test_bank_refine_session_short_new_items_at_cut(monkeypatch):
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.bank_engine import BankEngine
    from app.modules.assessment.grader import GradeOutcome
    from tests.test_bank_engine import oracle

    monkeypatch.setattr(be, "grade_open", lambda **k: GradeOutcome(
        status="scored", score=0.9 if len(k["answer"]) > 40 else 0.0, method="llm", model="test"))
    eng = BankEngine()
    rnd = random.Random(5)
    st = eng.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=5)
    res = _run(eng, st, rnd, 0.0, oracle)
    prev = dict(st, final_theta=res.theta, final_se=res.se)
    refine = {"grade": "middle", "cut_grade": "middle", "lower": "junior", "cut": 0.0, "p": 0.6, "kind": "keep",
              "level": 0.8, "items": 6, "minutes": 15, "confirm": 0.5, "confirm_up": 0.9, "floor": False,
              "source_session_id": "x"}
    st2 = eng.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=105, refine_from=prev,
                    refine=refine)
    assert st2["mode"] == "refine" and st2["prior"] and st2["cfg"]["cuts_only"] == "middle"
    assert all("key" not in i and "public" not in i for i in st2["prior"])
    res2 = _run(eng, st2, rnd, 0.0, oracle)
    new = [i for i in st2["items"] if i["done"] and not i["canary"]]
    assert 1 <= len(new) <= 6
    assert not ({i["family_id"] for i in new} & {i["family_id"] for i in st2["prior"]})
    assert all(i["time_limit_s"] <= 300 for i in new)
    o = res2.details["two_stage"]
    assert o["new_items"] == len(new) and o["cut_grade"] == "middle" and o["label"] == "на границе Junior/Middle"
    assert o["final_grade"] == ts.final_grade(o["theta"], o["se"], "middle", 0.5, 0.9)
    assert o["passed"] == (o["final_grade"] in ("middle", "senior"))
    assert res2.details["n_scored"] == len(new) + sum(1 for i in st2["prior"] if not i.get("canary"))
    assert res2.se <= res.se + 0.05


# ---------------------------------------------------------------- продукт через API

def _onboard(client, email):
    t = register_and_verify(client, email=email)
    client.put("/api/me/onboarding", json={**ONBOARDING, "experience_years": 4}, headers=H(t))
    from app.modules.auth.models import User

    with SessionLocal() as db:
        uid = db.scalar(select(User).where(User.email == email)).id
    return t, uid


def _reset(uid):
    from app.modules.profiles.models import CandidateProfile, CandidateSpecialization

    with SessionLocal() as db:
        p = db.get(CandidateProfile, uid)
        p.current_category_id = p.current_grade_id = p.current_direction_id = None
        p.grade_locked_until, p.grade_provisional = None, False
        for r in db.scalars(select(CandidateSpecialization).where(CandidateSpecialization.user_id == uid)):
            r.grade_id = r.category_id = r.locked_until = r.confirmed_at = None
            r.status = "declared"
        db.commit()


def _answer_all(db, service, sess, rnd, target, oracle):
    while True:
        item = service.next_item(db, sess)
        if item is None:
            break
        it = next(i for i in sess.result["state"]["items"] if i["token"] == item.item_id)
        good = rnd.random() < (0.85 if it["theta_before"] < target else 0.3)
        service.submit_answer(db, sess, item.item_id, oracle(it, item.step or 1, good), 1000, step=item.step)
    return service.finish_session(db, sess)


def test_api_two_stage_offer_refine_and_employer_note(client, monkeypatch, flag):
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment import service
    from app.modules.assessment.grader import GradeOutcome
    from app.modules.assessment.models import TestSession
    from app.modules.profiles.models import CandidateFact
    from tests.test_bank_engine import oracle

    monkeypatch.setattr(be, "grade_open", lambda **k: GradeOutcome(
        status="scored", score=0.9 if len(k["answer"]) > 40 else 0.0, method="llm", model="test"))
    flag(True, level=0.9)
    t, uid = _onboard(client, "twostage@example.com")
    # флаг включён, но полного теста нет — уточнять нечего
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", "mode": "refine"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "refine_unavailable"
    for seed in range(2, 16):
        rnd = random.Random(seed)
        with SessionLocal() as db:
            sess = service.start_session(db, uid, "middle", "bank")
            out = _answer_all(db, service, sess, rnd, 0.0, oracle)
            sid = sess.id
        if out.get("two_stage") and out["two_stage"]["available"]:
            break
        _reset(uid)
    else:
        pytest.skip("не нашли итог «на границе» на 14 сидах")
    off = out["two_stage"]
    assert off["status"] == "offered" and off["label"].startswith("на границе ")
    assert off["boundary"]["cut_grade"] in ("junior", "middle") and off["minutes"] == 15
    # итог по запросу — то же предложение
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert r.status_code == 200 and r.json()["two_stage"]["available"] is True
    # работодатель (если тест присвоил категорию) видит пометку «уточнение не проходил»
    with SessionLocal() as db:
        facts = db.scalars(select(CandidateFact).where(CandidateFact.user_id == uid,
                                                       CandidateFact.kind == "test_result")).all()
        if facts:
            assert facts[0].value["two_stage"]["status"] == "offered"
    # уточнение: отдельная сессия, только короткие новые задания
    r = client.post("/api/assessment/sessions", json={"claimed_grade": out["claimed_grade"], "mode": "refine",
                                                      "integrity_ack": True}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["mode"] == "refine" and s["total"] <= 8 and s["answered"] == 0 and s["item"]["extension"]
    # повторный запрос возвращает ту же сессию
    r2 = client.post("/api/assessment/sessions", json={"claimed_grade": out["claimed_grade"], "mode": "refine"},
                     headers=H(t))
    assert r2.json()["session_id"] == s["session_id"]
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert r.json()["two_stage"]["status"] == "in_progress" and not r.json()["two_stage"]["available"]
    with SessionLocal() as db:
        rs = db.get(TestSession, uuid.UUID(s["session_id"]))
        assert rs.result["state"]["refine"]["source_session_id"] == str(sid)
        out2 = _answer_all(db, service, rs, random.Random(99), 0.0, oracle)
    assert out2["mode"] == "refine"
    v = out2["two_stage"]
    assert v["status"] in ("passed", "failed") and v["refine"]["new_items"] >= 1
    assert v["refine"]["source_session_id"] == str(sid)
    assert "обеих сессий" in out2["explanation"]
    f = v["refine"]["final_grade"]
    if f != "none":
        assert out2["claimed_grade"] == f and out2["confirmed"]
    # первая сессия: уточнение пройдено, нового нет
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert r.json()["two_stage"]["status"] == "done" and r.json()["two_stage"]["outcome"]["final_grade"] == f
    r = client.post("/api/assessment/sessions", json={"claimed_grade": out["claimed_grade"], "mode": "refine"},
                    headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "refine_unavailable"
    with SessionLocal() as db:
        facts = db.scalars(select(CandidateFact).where(CandidateFact.user_id == uid,
                                                       CandidateFact.kind == "test_result")).all()
        if facts:
            assert facts[0].value["two_stage"]["status"] == v["status"]
            note = ts.card_note(facts[0].value)
            assert note and ("пройдено" in note["text"])
    # флаг выключен — блока нет, режим недоступен
    flag(False)
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert "two_stage" not in r.json() or r.json()["two_stage"] is None
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", "mode": "refine"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "two_stage_disabled"


# ---------------------------------------------------------------- симуляция

def test_simulation_report_committed_and_signed():
    from app.modules.validation import two_stage as vs

    rep = json.loads(vs.OUT.read_text(encoding="utf-8"))
    assert rep["signature"]["commit"] and "модель" in rep["caveat"].lower() or "синтетика" in rep["caveat"].lower()
    base = next(p for p in rep["points"] if not p["point"]["items"])
    assert base["metrics"]["share_refined"] == 0
    for p in rep["points"]:
        m = p["metrics"]
        assert 0 <= m["exact"] <= 1 and 0 <= m["share_refined"] <= 1 and m["minutes_mean"] >= base["metrics"]["minutes_mean"] - 0.01
    assert rep["choice"]["key"] in {p["key"] for p in rep["points"]}
    c = vs.compact(rep)
    assert c["one_session"]["exact"] == base["metrics"]["exact"] and c["choice"]


def test_simulation_tiny_run_smoke():
    """Механика симуляции на 4 кандидатах одного направления (без записи)."""
    from app.modules.validation import two_stage as vs

    pts = [vs.one_session(), vs._v()]
    rows = vs.run_task((pts, 0, "backend", 4, 0, 4))
    assert {r["key"] for r in rows} == {vs.key(p) for p in pts}
