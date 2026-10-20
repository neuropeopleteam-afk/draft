"""KF3 «Оффер в один клик»: до 3 слотов собеседования прямо в приглашении (employment_terms.proposed_slots),
принятие с бронированием слота (accept + slot_index → собеседование «назначено»), принятие без слота (слоты
становятся предложением), ошибки слота не принимают приглашение, старый accept без тела работает как раньше."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.hiring import service as hiring_svc
from app.modules.hiring.models import HiringInterview
from app.modules.invitations.models import Invitation
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref
from tests.test_hiring import LINK, _slots

C = "/api/candidate/invitations"
E = "/api/employer/invitations"


def _invite(client, slots=None, cand="kf3-cand@example.com", emp="kf3-hr@corp.ru"):
    tc, te = candidate_with_category(client, email=cand), employer(client, email=emp)
    body = {**INVITE, "candidate_ref": my_ref(client, tc)}
    if slots is not None:
        body["proposed_slots"] = slots
    r = client.post(E, json=body, headers=H(te))
    return tc, te, r


def _one(client, t, inv_id, side="candidate") -> dict:
    return next(i for i in client.get(f"/api/{side}/invitations", headers=H(t)).json() if i["id"] == inv_id)


# ------------------------------------------------------------------ валидация слотов (чистые функции)

def test_validate_slots_pure():
    now = datetime.now(UTC)
    assert hiring_svc.validate_slots(None) == [] and hiring_svc.validate_slots([]) == []
    base = (now + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    raw = [{"starts_at": (base + timedelta(hours=h)).isoformat(), "duration_min": 45, "format": "phone"}
           for h in (4, 0, 2)]
    out = hiring_svc.validate_slots(raw, now)
    assert [s["starts_at"] for s in out] == sorted(s["starts_at"] for s in out)  # по времени
    assert all(s["id"] and s["format"] == "phone" and s["duration_min"] == 45 for s in out)
    # время без пояса — московское: 12:00 МСК = 09:00 UTC
    day = (now + timedelta(days=3)).date().isoformat()
    msk = hiring_svc.validate_slots([{"starts_at": f"{day}T12:00", "duration_min": 60, "format": "phone"}], now)
    assert datetime.fromisoformat(msk[0]["starts_at"]).astimezone(UTC).hour == 9
    for bad, code in [(raw + raw[:1], "slots_count"),
                      ([raw[0], dict(raw[0])], "slots_duplicate"),
                      ([{**raw[0], "starts_at": (now - timedelta(hours=1)).isoformat()}], "slot_past"),
                      ([{**raw[0], "format": "video", "place": None}], "slot_link")]:
        with pytest.raises(Exception) as e:
            hiring_svc.validate_slots(bad, now)
        assert e.value.detail["code"] == code, (code, e.value.detail)


# ------------------------------------------------------------------ работодатель: приглашение со слотами

def test_invitation_stores_proposed_slots(client):
    tc, te, r = _invite(client, slots=_slots(3))
    assert r.status_code == 201, r.text
    inv = r.json()
    terms = inv["employment_terms"]
    assert terms["format"] == "employment" and len(terms["proposed_slots"]) == 3
    assert all(s["id"] and s["place"] == LINK for s in terms["proposed_slots"])
    assert [s["index"] for s in inv["proposed_slots"]] == [0, 1, 2]
    assert not any(s["past"] for s in inv["proposed_slots"]) and "мин" in inv["proposed_slots"][0]["text"]
    # кандидат видит те же слоты в приглашении
    seen = _one(client, tc, inv["id"])
    assert [s["starts_at"] for s in seen["proposed_slots"]] == [s["starts_at"] for s in terms["proposed_slots"]]
    with SessionLocal() as db:
        row = db.get(Invitation, uuid.UUID(inv["id"]))
        assert len(row.employment_terms["proposed_slots"]) == 3


def test_invitation_without_slots_unchanged(client):
    tc, te, r = _invite(client)
    assert r.status_code == 201, r.text
    assert "proposed_slots" not in r.json()["employment_terms"] and r.json()["proposed_slots"] == []
    # старый accept без тела — как раньше, собеседование не создаётся
    a = client.post(f"{C}/{r.json()['id']}/accept", headers=H(tc))
    assert a.status_code == 200 and a.json()["status"] == "accepted"
    assert a.json()["booked_interview"] is None
    assert client.get(f"{C}/{r.json()['id']}/hiring", headers=H(tc)).json()["interview"] is None


@pytest.mark.parametrize("slots,code", [
    (_slots(4), 422),                                    # больше трёх — схема
    (_slots(1, place=None), 422),                        # видеозвонок без ссылки
    (_slots(1, days=90), 422),                           # слишком далеко
])
def test_invitation_bad_slots_rejected(client, slots, code):
    tc, te, r = _invite(client, slots=slots)
    assert r.status_code == code, r.text
    assert client.get(E, headers=H(te)).json() == []  # приглашение не создано


# ------------------------------------------------------------------ кандидат: принять и забронировать слот

def test_accept_with_slot_books_interview(client):
    tc, te, r = _invite(client, slots=_slots(3))
    inv = r.json()
    target = inv["employment_terms"]["proposed_slots"][1]
    a = client.post(f"{C}/{inv['id']}/accept", json={"slot_index": 1}, headers=H(tc))
    assert a.status_code == 200, a.text
    out = a.json()
    assert out["status"] == "accepted"
    iv = out["booked_interview"]
    st = client.get(f"{C}/{inv['id']}/hiring", headers=H(tc)).json()["interview"]
    assert st["id"] == iv["id"] and st["status"] == iv["status"] and st["chosen_slot"] == iv["chosen_slot"]
    assert iv["status"] == "scheduled" and iv["chosen_slot"] == target["id"]
    assert datetime.fromisoformat(iv["starts_at"]) == datetime.fromisoformat(target["starts_at"])
    assert iv["format"] == "video" and iv["place"] == LINK and iv["duration_min"] == 60
    with SessionLocal() as db:
        rows = db.scalars(select(HiringInterview).where(HiringInterview.invitation_id == uuid.UUID(inv["id"]))).all()
        assert len(rows) == 1 and rows[0].status == "scheduled" and rows[0].created_by != rows[0].candidate_user_id
    # работодатель видит назначенное собеседование и событие в истории
    emp = _one(client, te, inv["id"], "employer")
    assert emp["hiring"]["line"].startswith("Собеседование")
    assert client.get(f"{E}/{inv['id']}/hiring", headers=H(te)).json()["interview"]["status"] == "scheduled"
    kinds = [h["status"] for h in emp["history"]]
    assert "interview_scheduled" in kinds and "interview_proposed" in kinds


def test_accept_without_slot_index_turns_slots_into_proposal(client):
    tc, te, r = _invite(client, slots=_slots(2))
    inv = r.json()
    a = client.post(f"{C}/{inv['id']}/accept", json={}, headers=H(tc))
    assert a.status_code == 200, a.text
    iv = a.json()["booked_interview"]
    assert iv["status"] == "proposed" and len(iv["slots"]) == 2
    # выбрать позже — обычным choose
    ch = client.post(f"{C}/{inv['id']}/interviews/{iv['id']}/choose", json={"slot_id": iv["slots"][1]["id"]},
                     headers=H(tc))
    assert ch.status_code == 200 and ch.json()["interview"]["status"] == "scheduled"


def test_accept_bad_slot_index_keeps_invitation_open(client):
    tc, te, r = _invite(client, slots=_slots(2))
    inv_id = r.json()["id"]
    bad = client.post(f"{C}/{inv_id}/accept", json={"slot_index": 2}, headers=H(tc))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "slot_unknown"
    assert client.post(f"{C}/{inv_id}/accept", json={"slot_index": 5}, headers=H(tc)).status_code == 422  # схема: 0–2
    assert _one(client, tc, inv_id)["status"] in ("sent", "viewed")  # не принято наполовину
    # слот уже прошёл — 409, приглашение не принято
    with SessionLocal() as db:
        row = db.get(Invitation, uuid.UUID(inv_id))
        terms = dict(row.employment_terms)
        gone = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        terms["proposed_slots"] = [{**terms["proposed_slots"][0], "starts_at": gone}, terms["proposed_slots"][1]]
        row.employment_terms = terms
        db.commit()
    seen = _one(client, tc, inv_id)["proposed_slots"]
    assert seen[0]["past"] is True and seen[1]["past"] is False
    past = client.post(f"{C}/{inv_id}/accept", json={"slot_index": 0}, headers=H(tc))
    assert past.status_code == 409 and past.json()["detail"]["code"] == "slot_past"
    assert _one(client, tc, inv_id)["status"] in ("sent", "viewed")
    # а будущий слот бронируется; прошедший в собеседование не попадает
    ok = client.post(f"{C}/{inv_id}/accept", json={"slot_index": 1}, headers=H(tc))
    assert ok.status_code == 200, ok.text
    iv = ok.json()["booked_interview"]
    assert iv["status"] == "scheduled" and len(iv["slots"]) == 1


def test_slot_index_without_slots_is_rejected(client):
    tc, te, r = _invite(client)
    inv_id = r.json()["id"]
    bad = client.post(f"{C}/{inv_id}/accept", json={"slot_index": 0}, headers=H(tc))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "slot_unknown"
    assert client.post(f"{C}/{inv_id}/accept", headers=H(tc)).status_code == 200
