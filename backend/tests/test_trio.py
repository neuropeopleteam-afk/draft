"""Трёхсторонняя связь: работодатель ↔ кандидат ↔ представитель ФСП (согласие кандидата, маскировка, доступ)."""
from tests.test_contact import _invite
from tests.test_day2_rules import H, candidate_with_category, employer
from tests.test_fsp_cabinet import analyst_token

MASK = "[контакт скрыт до принятия приглашения]"


def test_trio_employer_needs_candidate_consent_and_masks(client):
    tc, te, ta = candidate_with_category(client), employer(client), analyst_token(client)
    inv = _invite(client, tc, te)
    el = client.get("/api/trio/eligible", headers=H(te)).json()
    assert any(x["invitation_id"] == inv["id"] for x in el)
    r = client.post("/api/trio/threads", json={"invitation_id": inv["id"], "topic": "fsp_check",
                                               "body": "Подтвердите разряд, мой номер +7 912 345-67-89"}, headers=H(te))
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "pending" and t["side"] == "employer"
    assert MASK in t["messages"][-1]["body"]
    tid = t["id"]
    # до согласия ФСП канал не видит
    assert client.get(f"/api/trio/threads/{tid}", headers=H(ta)).status_code == 404
    assert all(x["id"] != tid for x in client.get("/api/trio/threads", headers=H(ta)).json())
    # кандидат видит и соглашается
    c = client.get(f"/api/trio/threads/{tid}", headers=H(tc)).json()
    assert c["needs_my_consent"] is True
    assert client.post(f"/api/trio/threads/{tid}/consent", headers=H(te)).status_code == 403
    assert client.post(f"/api/trio/threads/{tid}/consent", headers=H(tc)).json()["status"] == "active"
    f = client.post(f"/api/trio/threads/{tid}/messages", json={"body": "Разряд подтверждён по реестру ФСП"}, headers=H(ta))
    assert f.status_code == 201, f.text
    assert f.json()["messages"][-1]["side"] == "fsp"
    sides = {m["side"] for m in client.get(f"/api/trio/threads/{tid}", headers=H(tc)).json()["messages"]}
    assert {"employer", "fsp", "system"} <= sides
    # чужой работодатель не видит
    assert client.get(f"/api/trio/threads/{tid}", headers=H(employer(client, email="other-emp@example.com"))).status_code == 404
    # закрытие — только чтение
    assert client.post(f"/api/trio/threads/{tid}/close", headers=H(tc)).json()["status"] == "closed"
    assert client.post(f"/api/trio/threads/{tid}/messages", json={"body": "ещё"}, headers=H(te)).status_code == 409


def test_trio_candidate_creates_active(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    t = client.post("/api/trio/threads", json={"invitation_id": inv["id"]}, headers=H(tc)).json()
    assert t["status"] == "active" and t["participants"][2]["joined"] is True
    again = client.post("/api/trio/threads", json={"invitation_id": inv["id"]}, headers=H(te))
    assert again.json()["id"] == t["id"]


def test_trio_role_guards(client):
    from app.core.enums import UserRole
    from tests.test_access_matrix import _real_user

    ta = analyst_token(client)
    tx = _real_user("trio-expert@example.org", UserRole.expert)
    assert client.get("/api/trio/threads", headers=H(tx)).status_code == 403
    assert client.get("/api/trio/eligible", headers=H(ta)).status_code == 403
    assert client.post("/api/trio/threads", json={}, headers=H(ta)).status_code == 403
