"""Исправления по аудиту безопасности (К1, К2, В1, повторная отправка кода)."""
import re
import uuid

from app.core.db import SessionLocal
from tests.conftest import register, register_and_verify
from tests.route_walk import iter_routes
from tests.test_day2_rules import H


def _fill(path: str) -> str:
    """/api/admin/x/{pid}/y → /api/admin/x/x/y: любое значение параметра — отказ в правах должен быть раньше поиска."""
    return re.sub(r"\{[^}]+\}", "x", path)


def test_k1_verify_email_of_verified_account_gives_no_token(client):
    register_and_verify(client, "victim@example.com")
    for code in ("000000", "123456"):
        r = client.post("/api/auth/verify-email", json={"email": "victim@example.com", "code": code})
        assert r.status_code == 400 and "access_token" not in r.text
        assert r.json()["error"]["code"] == "invalid_code" if "error" in r.json() else True
    # и для неизвестного адреса — тот же ответ (адреса не перечисляются)
    r = client.post("/api/auth/verify-email", json={"email": "nobody@example.com", "code": "000000"})
    assert r.status_code == 400


def test_k1_token_only_after_correct_code(client):
    r = register(client, "new@example.com", "Passw0rd!", "candidate")
    code = r.json()["dev_verification_code"]
    bad = client.post("/api/auth/verify-email", json={"email": "new@example.com", "code": "999999" if code != "999999" else "111111"})
    assert bad.status_code == 400 and "access_token" not in bad.text
    ok = client.post("/api/auth/verify-email", json={"email": "new@example.com", "code": code})
    assert ok.status_code == 200 and ok.json()["access_token"]
    again = client.post("/api/auth/verify-email", json={"email": "new@example.com", "code": code})  # код погашен
    assert again.status_code == 400 and "access_token" not in again.text


def test_resend_does_not_reset_code_attempts(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "email_code_resend_seconds", 0)
    r = register(client, "slow@example.com", "Passw0rd!", "candidate")
    code = r.json()["dev_verification_code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(get_settings().email_code_max_attempts):
        assert client.post("/api/auth/verify-email", json={"email": "slow@example.com", "code": wrong}).status_code == 400
    r = client.post("/api/auth/resend-code", json={"email": "slow@example.com"})
    assert r.status_code == 202
    new_code = r.json()["dev_verification_code"]
    r = client.post("/api/auth/verify-email", json={"email": "slow@example.com", "code": new_code})
    assert r.status_code == 429 and "access_token" not in r.text


def test_b1_login_bruteforce_limited(client):
    from app.modules.auth import service

    register_and_verify(client, "brute@example.com")
    for _ in range(service.LOGIN_MAX_FAILS):
        assert client.post("/api/auth/login", json={"email": "brute@example.com", "password": "nope-nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "brute@example.com", "password": "Passw0rd!"})
    assert r.status_code == 429  # даже верный пароль — после окна
    service._LOGIN_FAILS.clear()
    assert client.post("/api/auth/login", json={"email": "brute@example.com", "password": "Passw0rd!"}).status_code == 200


def test_k2_jury_expert_is_not_admin_and_sees_only_demo(client):
    from sqlalchemy import select

    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.models import TestSession
    from app.modules.auth.models import User
    from app.modules.jury.seed import run_demo_test

    r = client.post("/api/jury/login", json={"persona": "expert"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "expert"
    x = r.json()["access_token"]
    # /api/admin/* — только у администратора. Обход — через общий хелпер: в FastAPI 0.142 у элементов app.routes
    # нет path (это _IncludedRouter), и прежний перебор по path не находил ни одного маршрута — проверка была пустой.
    assert client.get("/api/admin/sus/summary", headers=H(x)).status_code in (401, 403, 404)
    admin_routes = [r for r in iter_routes(client.app) if r.path.startswith("/api/admin/")]
    assert admin_routes, "обход маршрутов не нашёл /api/admin/* — хелпер tests/route_walk.py сломан"
    for r in admin_routes:
        url = _fill(r.path)
        resp = client.request(r.method, url, headers=H(x), json={})
        assert resp.status_code in (401, 403), (r.method, r.path, resp.status_code)  # не 404/405/422: отказ — до тела
        assert client.request(r.method, url, json={}).status_code == 401, (r.method, r.path)  # и анониму
    # реальный (не демо) кандидат с ответом «на проверке»
    tok = register_and_verify(client, "real@example.com")
    me = client.get("/api/me", headers=H(tok)).json()
    from tests.test_day2_rules import ONBOARDING

    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(tok)).status_code == 200
    with SessionLocal() as db:
        u = db.get(User, uuid.UUID(me["id"]))
        assert not u.is_demo
        run_demo_test(db, u.id, "middle", 0.9, 777, pending_left=1)
        db.commit()
        real_ids = {str(t.id) for t in db.scalars(select(TestSession).where(TestSession.user_id == u.id))}
    assert real_ids
    q = client.get("/api/expert/queue", headers=H(x)).json()
    assert not ({i["session_id"] for i in q["items"]} & real_ids)  # реальные ответы демо-эксперту не видны
    # и оценить сессию реального пользователя нельзя
    sid = next(iter(real_ids))
    with SessionLocal() as db:
        ts = db.get(TestSession, uuid.UUID(sid))
        items = be.BankEngine().review_items(ts.result["state"])
    it = next(i for i in items if i["status"] == "pending")
    crit = {c["id"]: 1.0 for c in it["rubric"]["criteria"]}
    r = client.post("/api/expert/review", headers=H(x), json={"session_id": sid, "token": it["token"], "part": it["part"],
                                                              "criteria": crit})
    assert r.status_code == 404
    # кандидат и работодатель к /api/expert/* не допускаются
    assert client.get("/api/expert/queue", headers=H(tok)).status_code == 403
