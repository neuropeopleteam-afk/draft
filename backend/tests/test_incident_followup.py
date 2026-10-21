"""Сквозной тест «инцидент как доп. этап для Senior и Lead» (решение владельца 21.10; интерфейс А4 ↔ А9):
попытка Senior на настоящем движке банка через API → вердикт «нужен доп. этап» у порога Senior с ссылкой на инцидент
«Полигона» → итог инцидента (пройден / не пройден) через assessment.service.apply_followup_stage → вердикт
confirmed / not_confirmed в итоге попытки, грейд присваивается обычным путём; повторный доп. этап — отказ."""
import json
import uuid

import pytest

from app.core.db import SessionLocal
from app.modules.assessment import bank_engine as be
from app.modules.assessment import service
from app.modules.assessment.grader import GradeOutcome
from tests.conftest import register_and_verify
from tests.test_bank_engine import oracle
from tests.test_day2_rules import ONBOARDING, H

CUT_SENIOR = 1.0


def _state(sid: str) -> dict:
    from app.modules.assessment.models import TestSession

    with SessionLocal() as db:
        return db.get(TestSession, uuid.UUID(sid)).result["state"]


def _borderline_senior(client, email: str) -> tuple[str, dict, str]:
    """Кандидат на границе Senior: отвечает верно, пока оценка ниже порога, и неверно, когда выше («edge»)."""
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "senior"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    sid = s["session_id"]
    n = 0
    while s["item"]:
        it_pub = s["item"]
        it = next(i for i in _state(sid)["items"] if i["token"] == it_pub["item_id"])
        good = it["theta_before"] < CUT_SENIOR
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json={
            "item_id": it_pub["item_id"], "answer": oracle(it, it_pub["step"] or 1, good), "step": it_pub["step"],
            "time_spent_ms": 60000})
        assert r.status_code == 200, r.text
        s = r.json()
        n += 1
        assert n < 90
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    return sid, res, t


@pytest.fixture
def bank_api(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(get_settings(), "assessment_confirm_level", 0.8)
    monkeypatch.setattr(get_settings(), "assessment_two_stage_confirm", 0.5)
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored",
                                                                   score=0.9 if len(kw.get("answer") or "") > 40 else 0.0,
                                                                   method="llm"))
    return client


def _find_borderline(client, tag: str):
    for k in range(6):  # движок адаптивный: граница почти всегда «спорная», но берём первую такую попытку
        sid, res, t = _borderline_senior(client, f"inc-{tag}-{k}@example.com")
        v = res.get("verdict") or {}
        if v.get("status") == "needs_followup" and not v.get("oral_defense_required"):
            return sid, res, t
    pytest.skip("не удалось получить спорный порог Senior за 6 попыток")


@pytest.mark.parametrize("passed", [True, False])
def test_incident_followup_end_to_end(bank_api, passed):
    client = bank_api
    sid, res, t = _find_borderline(client, "p" if passed else "f")
    v = res["verdict"]
    # п. 1: спорный порог Senior + инцидент направления backend → доп. этап — инцидент «Полигона»
    assert v["followup_kind"] == "incident"
    assert v["followup_url"] == f"/warroom?followup={sid}#architecture"
    assert v["followup_minutes"] > 0 and v.get("followup_incident_id")
    raw = json.dumps(res, ensure_ascii=False)
    assert "answer_key" not in raw and "rubric" not in raw
    stage = {"incident_id": v["followup_incident_id"], "score": 0.92 if passed else 0.2, "passed": passed,
             "measures_ok": passed, "code_ok": passed, "justification_ok": passed, "minutes": 25, "integrity": {}}
    with SessionLocal() as db:
        out = service.apply_followup_stage(db, sid, stage)
    nv = out["verdict"]
    assert nv["status"] == ("confirmed" if passed else "not_confirmed")
    assert nv["mode"] == "refine" and nv["followup_applied"] is True
    assert "на людях ещё не откалиброван" in nv["explanation_ru"]
    assert (nv["p_claimed"] > nv["p_before"]) if passed else (nv["p_claimed"] < nv["p_before"])
    # итог попытки (то, что видит кандидат и что читает карточка работодателя) — новый вердикт
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t)).json()
    assert r["verdict"]["status"] == nv["status"]
    status = client.get("/api/assessment/status", headers=H(t)).json()
    cat = (status.get("current") or {}).get("category_id")
    assert (cat == "backend.senior") if passed else (cat != "backend.senior")
    # одна попытка доп. этапа на тест
    with SessionLocal() as db, pytest.raises(Exception):
        service.apply_followup_stage(db, sid, stage)


def test_incident_cheating_signals_lead_to_oral_defense_not_ban(bank_api):
    client = bank_api
    sid, res, t = _find_borderline(client, "c")
    stage = {"incident_id": res["verdict"]["followup_incident_id"], "score": 0.95, "passed": True,
             "measures_ok": True, "code_ok": True, "justification_ok": True, "minutes": 4,
             "integrity": {"signals": {"paste_items": 3, "not_typed_items": 2, "focus_lost_items": 3, "hidden_s": 120}}}
    with SessionLocal() as db:
        nv = service.apply_followup_stage(db, sid, stage)["verdict"]
    assert nv["status"] == "needs_followup" and nv["oral_defense_required"] is True
    assert nv["followup_kind"] == "oral_defense"


def test_junior_middle_keep_short_block():
    from app.modules.assessment import sprt

    v = sprt.compute_verdict([], {}, "middle", theta=0.05, se=0.35, confirmed=False, assigned_grade="junior").as_dict()
    assert v["status"] == "needs_followup"
    v2 = sprt.attach_incident_followup(v, attempt_id="x", direction="backend")
    assert v2["followup_kind"] == "stage2" and "followup_url" not in v2
    v3 = sprt.compute_verdict([], {}, "senior", theta=1.0, se=0.35, confirmed=False, assigned_grade="middle").as_dict()
    assert sprt.attach_incident_followup(v3, attempt_id="x", direction="analyst")["followup_kind"] == "stage2"
