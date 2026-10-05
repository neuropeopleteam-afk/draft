from datetime import timedelta

from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from app.modules.auth.models import EmailVerification, User
from tests.conftest import register, register_and_verify


def test_register_candidate_returns_dev_code(client):
    r = register(client, full_name="Иван Петров")
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "candidate" and body["email_verification_required"] is True
    assert body["dev_verification_code"] and len(body["dev_verification_code"]) == 6


def test_password_stored_as_argon2(client):
    register(client)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert "Passw0rd!" not in user.password_hash


def test_register_duplicate_email_conflict(client):
    assert register(client, email="Dup@Example.com").status_code == 201
    r = register(client, email="dup@example.com")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "email_taken"


def test_register_requires_consent(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "a@example.com", "password": "Passw0rd!", "role": "candidate", "consent_processing": False},
    )
    assert r.status_code == 422


def test_register_rejects_weak_password_and_admin_role(client):
    assert register(client, password="onlyletters").status_code == 422
    assert register(client, role="admin").status_code == 422


def test_login_before_verification_forbidden(client):
    register(client)
    r = client.post("/api/auth/login", json={"email": "cand@example.com", "password": "Passw0rd!"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_not_verified"


def test_verify_wrong_code_then_lockout(client):
    register(client)
    for _ in range(5):
        r = client.post("/api/auth/verify-email", json={"email": "cand@example.com", "code": "000000"})
        assert r.status_code in (400, 429)
    r = client.post("/api/auth/verify-email", json={"email": "cand@example.com", "code": "000000"})
    assert r.status_code == 429


def test_verify_expired_code(client):
    code = register(client).json()["dev_verification_code"]
    with SessionLocal() as db:
        v = db.scalar(select(EmailVerification))
        v.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/auth/verify-email", json={"email": "cand@example.com", "code": code})
    assert r.status_code == 400


def test_full_flow_register_verify_login_me(client):
    token = register_and_verify(client)
    r = client.post("/api/auth/login", json={"email": "CAND@example.com", "password": "Passw0rd!"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["is_email_verified"] is True


def test_login_wrong_password(client):
    register_and_verify(client)
    r = client.post("/api/auth/login", json={"email": "cand@example.com", "password": "Wr0ngPass"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_credentials"


def test_oauth2_token_form(client):
    register_and_verify(client)
    r = client.post("/api/auth/token", data={"username": "cand@example.com", "password": "Passw0rd!"})
    assert r.status_code == 200 and r.json()["access_token"]


def test_resend_code_throttled_and_old_code_invalidated(client):
    first = register(client).json()["dev_verification_code"]
    r = client.post("/api/auth/resend-code", json={"email": "cand@example.com"})
    assert r.status_code == 429  # чаще раза в минуту нельзя
    with SessionLocal() as db:
        for v in db.scalars(select(EmailVerification)):
            v.created_at = utcnow() - timedelta(minutes=2)
        db.commit()
    r = client.post("/api/auth/resend-code", json={"email": "cand@example.com"})
    assert r.status_code == 202
    second = r.json()["dev_verification_code"]
    if first != second:
        bad = client.post("/api/auth/verify-email", json={"email": "cand@example.com", "code": first})
        assert bad.status_code == 400
    ok = client.post("/api/auth/verify-email", json={"email": "cand@example.com", "code": second})
    assert ok.status_code == 200


def test_resend_code_unknown_email_does_not_leak(client):
    r = client.post("/api/auth/resend-code", json={"email": "nobody@example.com"})
    assert r.status_code == 202 and r.json()["dev_verification_code"] is None
