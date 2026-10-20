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


def test_forgot_and_reset_password_flow(client):
    old_token = register_and_verify(client, email="forgot@example.com")
    # запрос кода сброса пароля
    r = client.post("/api/auth/forgot", json={"email": "FORGOT@example.com"})
    assert r.status_code == 202
    code = r.json()["dev_reset_code"]
    assert code and len(code) == 6

    # повторный запрос раньше минуты молча возвращает 202 (не раскрывает наличие адреса в системе)
    r2 = client.post("/api/auth/forgot", json={"email": "forgot@example.com"})
    assert r2.status_code == 202 and r2.json()["dev_reset_code"] is None

    # слабый пароль — 422
    assert client.post(
        "/api/auth/reset",
        json={"email": "forgot@example.com", "code": code, "new_password": "onlyletters"},
    ).status_code == 422

    # неверный код — 400
    bad = client.post(
        "/api/auth/reset",
        json={"email": "forgot@example.com", "code": "000000" if code != "000000" else "999999", "new_password": "NewPassw0rd!"},
    )
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_code"

    # верный код — меняет пароль и отзывает прежние сессии (token_version)
    ok = client.post(
        "/api/auth/reset",
        json={"email": "forgot@example.com", "code": code, "new_password": "NewPassw0rd!"},
    )
    assert ok.status_code == 200 and ok.json()["ok"] is True

    # повторное использование того же кода отклоняется
    reuse = client.post(
        "/api/auth/reset",
        json={"email": "forgot@example.com", "code": code, "new_password": "NewPassw0rd2!"},
    )
    assert reuse.status_code == 400

    # старый токен больше не действует, старый пароль не подходит, новый — работает
    assert client.get("/api/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "forgot@example.com", "password": "Passw0rd!"}).status_code == 401
    login_ok = client.post("/api/auth/login", json={"email": "forgot@example.com", "password": "NewPassw0rd!"})
    assert login_ok.status_code == 200 and login_ok.json()["access_token"]


def test_forgot_unknown_email_and_reset_lockout(client):
    # неизвестный email не раскрывается
    r = client.post("/api/auth/forgot", json={"email": "unknown-user@example.com"})
    assert r.status_code == 202 and r.json()["dev_reset_code"] is None
    assert client.post(
        "/api/auth/reset",
        json={"email": "unknown-user@example.com", "code": "123456", "new_password": "NewPassw0rd!"},
    ).status_code == 400

    # блокировка после 5 неверных попыток ввода кода сброса
    register_and_verify(client, email="lockreset@example.com")
    code = client.post("/api/auth/forgot", json={"email": "lockreset@example.com"}).json()["dev_reset_code"]
    wrong = "000000" if code != "000000" else "999999"
    for _ in range(5):
        resp = client.post(
            "/api/auth/reset",
            json={"email": "lockreset@example.com", "code": wrong, "new_password": "NewPassw0rd!"},
        )
        assert resp.status_code in (400, 429)
    locked = client.post(
        "/api/auth/reset",
        json={"email": "lockreset@example.com", "code": code, "new_password": "NewPassw0rd!"},
    )
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "too_many_attempts"

