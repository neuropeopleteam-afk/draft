"""Движок теста на банке заданий: адаптивная сессия, дотестирование у порога, скрытие ключей, время ответов,
открытые ответы (LLM по рубрике / «на проверке»), запись в таблицы ответов, запрет досрочного завершения."""
import json
import uuid

import pytest

from app.core.db import SessionLocal
from app.modules.assessment import bank_engine as be
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.grader import GradeOutcome
from tests.conftest import register_and_verify
from tests.test_day2_rules import ONBOARDING, H

CUT = {"junior": -1.0, "middle": 0.0, "senior": 1.0}


def oracle(it: dict, step: int, good: bool):
    """Ответ «знающего» (good) или «не знающего» кандидата по серверному ключу задания."""
    key, fmt = it["key"], it["format"]
    if fmt in ("choose_fix", "mcq_concept"):
        ids = [o["id"] for o in it["public"]["options"]]
        return key["value"] if good else next(i for i in ids if i != key["value"])
    if fmt == "find_bug":
        n = it["public"]["code_lines"]
        return key["value"] if good else (key["value"] % n) + 1
    if fmt == "predict_output":
        return key["value"] if good else "не знаю"
    if fmt == "open_book_3step":
        if step < 3:
            ids = [o["id"] for o in it["public"]["options"] if o.get("step") == step]
            return key["value"][str(step)] if good else next(i for i in ids if i != key["value"][str(step)])
        return ("Подробное объяснение причины дефекта, воспроизведения и исправления при новом условии. " * 3
                if good else "")
    return ("Развёрнутый проектный ответ: требования, ограничения, компромиссы, мониторинг и откат. " * 3
            if good else "")


def run_session(engine: BankEngine, claimed="middle", direction="backend", policy="good"):
    st = engine.start(direction=direction, claimed_grade=claimed, stack_tags=[], seed=12345)
    seen_positions = []
    while True:
        item = engine.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        seen_positions.append((item.position, it["canary"]))
        good = policy == "good" or (policy == "edge" and it["theta_before"] < CUT[claimed])
        fb = engine.answer(st, item.item_id, oracle(it, item.step or 1, good), 1000, step=item.step)
        assert fb.accepted
        assert len(st["items"]) < 40, "сессия не останавливается"
    return st, engine.finish(st), seen_positions


@pytest.fixture
def bank(monkeypatch):
    # Открытые ответы оцениваем «экспертом»-заглушкой: длинный ответ — 0.9, пустой — 0 (LLM в тестах выключен)
    def fake_grade(*, stem, code, step_prompt, rubric, answer, use_llm=True):
        return GradeOutcome(status="scored", score=0.9 if len(answer) > 40 else 0.0, method="llm", model="test")
    monkeypatch.setattr(be, "grade_open", fake_grade)
    return BankEngine()


def test_strong_candidate_confirmed_adaptive_and_canaries(bank):
    st, res, pos = run_session(bank, "middle", "backend", "good")
    assert res.confirmed and res.theta > 0.5, res
    d = res.details
    assert 8 <= d["n_scored"] <= 24 and d["stop_reason"] in ("se_target", "max_items", "pool_exhausted", "time",
                                                               "extension_done")
    # канарейки на позициях 2, 6, 10 и в θ не входят
    assert [p for p, c in pos if c][:3] == [2, 6, 10]
    blocks = {i["block"] for i in st["items"]}
    assert blocks == {"common", "backend"}
    # время ответа зафиксировано сервером по каждому заданию
    assert all(i["time_s"] >= 1 and i["log_t"] is not None for i in st["items"] if i["done"])
    assert res.skills and all(0 <= v["score"] <= 1 for v in res.skills.values())


def test_weak_candidate_not_confirmed(bank):
    _, res, _ = run_session(bank, "senior", "frontend", "bad")
    assert not res.confirmed and res.theta < 0


def test_result_near_cut_triggers_extension(bank):
    st, res, _ = run_session(bank, "middle", "security", "edge")
    ext = res.details["extension"]
    assert ext is not None and 3 <= ext["items"] <= 4, res.details
    assert abs(ext["theta_before"] - CUT["middle"]) < ext["se_before"]
    assert sum(1 for i in st["items"] if i["ext"]) == ext["items"]


def test_public_item_never_contains_keys(bank):
    st = bank.start(direction="data_ml", claimed_grade="junior", stack_tags=[], seed=7)
    for _ in range(12):
        item = bank.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        blob = json.dumps(item.__dict__, ensure_ascii=False)
        for secret in ("answer_key", "rubric", "explanation", it["family_id"], it["variant_id"], f'"{it["seed"]}"'):
            assert secret not in blob
        if it["format"] in ("choose_fix", "mcq_concept"):
            assert {o["id"] for o in item.options} == {o["id"] for o in it["public"]["options"]}
        bank.answer(st, item.item_id, oracle(it, item.step or 1, True), 500, step=item.step)


def test_seeds_are_secret_and_unique(bank):
    seeds = set()
    for k in range(5):
        st = bank.start(direction="qa", claimed_grade="middle", stack_tags=[], seed=k)
        item = bank.next_item(st)
        it = st["items"][0]
        assert it["seed"] >= be.SEED_MIN or it["canary"]
        seeds.add(it["seed"])
        assert item.position == 1
    assert len(seeds) == 5


def test_open_answer_pending_without_llm():
    eng = BankEngine()  # настоящий grader, LLM выключен (LLM_DISABLED=true в conftest)
    st = eng.start(direction="backend", claimed_grade="senior", stack_tags=[], seed=99)
    pending = 0
    for _ in range(40):
        item = eng.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        eng.answer(st, item.item_id, oracle(it, item.step or 1, True), 800, step=item.step)
        if it["format"] in ("open_answer", "open_book_3step") and it["done"]:
            pending += any(v is None for v in it["x"])
            assert all(g is None or g["status"] == "pending" for g in it["grading"])
    res = eng.finish(st)
    assert res.details["pending_review"] == pending
    if pending:
        assert "на проверке" in res.explanation


def test_wrong_step_or_foreign_token_rejected(bank):
    st = bank.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=5)
    item = bank.next_item(st)
    assert not bank.answer(st, "чужой-токен", "A").accepted
    assert not bank.answer(st, item.item_id, "A", step=3).accepted or item.step == 3
    assert not bank.answer(st, item.item_id, {"value": "Z" * 30000} if item.answer_kind == "line" else 10**9).accepted \
        or item.answer_kind == "text"


def test_skill_map_targets_exist_in_catalog():
    from app.modules.assessment import skill_map
    from app.modules.catalog.seed_data import STACK

    targets = set(skill_map._GLOBAL.values()) | {v for d in skill_map._BY_DIRECTION.values() for v in d.values()}
    assert targets <= set(STACK), targets - set(STACK)


# ------------------------------------------------------------------ через API

def _state(session_id: str) -> dict:
    from app.modules.assessment.models import TestSession

    with SessionLocal() as db:
        return db.get(TestSession, uuid.UUID(session_id)).result["state"]


def test_api_bank_session_end_to_end(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm"))
    t = register_and_verify(client, email="bank@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    sid = s["session_id"]
    assert s["engine"].startswith("bank-") and s["item"]["adaptive"]
    # досрочно завершить нельзя
    assert client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()["detail"]["code"] == \
        "test_not_complete"
    n = 0
    while s["item"]:
        it_pub = s["item"]
        st = _state(sid)
        it = next(i for i in st["items"] if i["token"] == it_pub["item_id"])
        raw = json.dumps(s, ensure_ascii=False)
        for secret in ("answer_key", "rubric", it["family_id"], it["variant_id"]):
            assert secret not in raw
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json={
            "item_id": it_pub["item_id"], "answer": oracle(it, it_pub["step"] or 1, True), "step": it_pub["step"],
            "time_spent_ms": 4000})
        assert r.status_code == 200, r.text
        s = r.json()
        n += 1
        assert n < 80
    assert s["can_finish"]
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    assert res["confirmed"] and res["category_id"] == "backend.middle", res
    assert res["details"]["n_scored"] >= 8 and "preknowledge" not in res["details"]
    status = client.get("/api/assessment/status", headers=H(t)).json()
    assert status["current"]["category_id"] == "backend.middle" and "state" not in json.dumps(status)
    # нормализованная запись: выданные варианты и ответы с временем
    from sqlalchemy import func, select

    from app.modules.assessment.models import TaskVariant, TestAnswer, TestSessionItem

    with SessionLocal() as db:
        n_items = db.scalar(select(func.count()).select_from(TestSessionItem))
        answers = db.scalars(select(TestAnswer)).all()
        assert n_items == len(answers) == len([i for i in _state(sid)["items"] if i["done"]])
        assert all(a.time_spent_ms >= 1000 for a in answers)
        assert db.scalar(select(func.count()).select_from(TaskVariant)) >= 1
    card = client.get("/api/me/card", headers=H(t)).json()
    assert card["test"]["engine"].startswith("bank-")
