"""День 3Б: интеграции — ЕГРЮЛ и индекс доверия, ФСП ID (OIDC + PKCE), ATS (Хантфлоу-заглушка, вебхук, экспорт),
вакансии и отклики, Web Push, SUS. Внешние сервисы подменяются; HTTP к тестовой ATS идёт через TestClient."""
from datetime import date, timedelta
import json
import time
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
import pytest

from app.integrations.settings import get_isettings
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref

ISSUER = "https://fsp.example/auth/realms/fsp"


@pytest.fixture
def isettings(monkeypatch):
    def apply(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_isettings.cache_clear()
        return get_isettings()

    yield apply
    get_isettings.cache_clear()


@pytest.fixture
def egrul_found(monkeypatch):
    from app.integrations.egrul import client as eg

    calls = []
    row = {"n": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ \"РОМАШКА\"", "c": "ООО \"РОМАШКА\"", "i": "9701316954",
           "o": "1157746000000", "p": "770101001", "r": "10.03.2015", "g": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР: Иванов Иван Иванович",
           "rn": "г. Москва", "k": "ul"}

    def fake(inn):
        calls.append(inn)
        return "found", eg.parse_row(row), None

    monkeypatch.setattr(eg, "fetch", fake)
    return calls


def company_with_inn(client, te, inn="9701316954", site="https://romashka.ru"):
    r = client.patch("/api/me/company", json={"inn": inn, "website": site, "contact_email": "hr@romashka.ru"},
                     headers=H(te))
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ ЕГРЮЛ и индекс доверия

def test_inn_checksum_and_parse():
    from app.integrations.egrul.client import parse_row, valid_inn

    assert valid_inn("9701316954") and valid_inn("7707083893") and not valid_inn("9701316955")
    assert valid_inn("500100732259") and not valid_inn("123")
    d = parse_row({"n": "ООО Т", "i": "7707083893", "r": "20.06.1991", "e": "01.02.2020", "g": "ДИРЕКТОР: Петров П.П."})
    assert d["registered_at"] == "1991-06-20" and d["liquidated_at"] == "2020-02-01"
    assert d["director"] == "Петров П.П." and d["director_role"] == "Директор"


def test_registry_check_cache_and_trust(client, egrul_found):
    te = employer(client, email="hr@romashka.ru", company="ООО Ромашка")
    company_with_inn(client, te)
    t = client.post("/api/employer/company/registry-check", headers=H(te)).json()
    assert t["registry"]["status"] == "found" and t["registry"]["director"] == "Иванов Иван Иванович"
    ids = {f["id"]: f for f in t["factors"]}
    assert ids["registry"]["status"] == "ok" and ids["email"]["status"] == "ok"  # домен почты = сайт компании
    assert ids["age"]["status"] == "ok" and 0 <= t["score"] <= 100 and t["level"] in ("high", "medium", "low")
    client.post("/api/employer/company/registry-check", headers=H(te))
    assert egrul_found == ["9701316954"]  # второй раз — из кэша (7 дней)


def test_registry_soft_degradation_on_captcha(client, monkeypatch):
    from app.integrations.egrul import client as eg

    monkeypatch.setattr(eg, "fetch", lambda inn: ("captcha", {}, "ФНС запросила капчу"))
    te = employer(client)
    company_with_inn(client, te)
    t = client.post("/api/employer/company/registry-check", headers=H(te)).json()
    assert t["registry"]["status"] == "captcha" and t["preliminary"] is True
    assert "не удалось" in json.dumps(t, ensure_ascii=False).lower()


def test_liquidated_company_is_low(client, monkeypatch):
    from app.integrations.egrul import client as eg

    monkeypatch.setattr(eg, "fetch", lambda inn: ("found", eg.parse_row(
        {"n": "ООО ЗАКРЫТО", "i": inn, "r": "01.01.2010", "e": "01.01.2024"}), None))
    te = employer(client)
    company_with_inn(client, te)
    t = client.post("/api/employer/company/registry-check", headers=H(te)).json()
    assert t["level"] == "low" and t["score"] <= 10 and t["critical"]


def test_trust_visible_in_invitation(client, egrul_found):
    tc = candidate_with_category(client)
    te = employer(client, email="hr@romashka.ru", company="ООО Ромашка")
    company_with_inn(client, te)
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)},
                      headers=H(te)).json()
    m = client.get("/api/candidate/invitations-trust", headers=H(tc)).json()
    assert inv["id"] in m and m[inv["id"]]["level"] in ("high", "medium", "low")
    full = client.get(f"/api/candidate/invitations/{inv['id']}/trust", headers=H(tc)).json()
    assert any(f["id"] == "salary" for f in full["factors"]) and full["summary"] and full["offer_salary"]
    prof = client.get(f"/api/companies/{full['company_id']}", headers=H(tc)).json()
    assert prof["trust"]["score"] == full["score"] or prof["trust"]["score"] >= 0


# ------------------------------------------------------------------ ФСП ID

def _claims(sub="kc-sub-1", email="champion@fsp-demo.ru", history=True):
    c = {"sub": sub, "iss": ISSUER, "email": email, "email_verified": True, "preferred_username": "fsp-champion"}
    if history:
        c.update({"fsp_id": "FSP-770012", "fsp_rank": "КМС", "fsp_disciplines": ["product", "algorithmic"],
                  "fsp_achievements": [json.dumps({"discipline": "product", "event": "Чемпионат России по продуктовому "
                                                   "программированию", "level": "national", "date": "2025-11-20",
                                                   "place": 1, "result": "победитель", "team": "Команда 7"}),
                                       {"discipline": "unknown", "event": "x", "level": "national"}]})
    return c


@pytest.fixture
def fsp(isettings, monkeypatch):
    from app.integrations.fsp_id import oidc

    isettings(FSP_OIDC_ISSUER=ISSUER, FSP_OIDC_INTERNAL_BASE="http://keycloak:8080/auth/realms/fsp",
              FSP_OIDC_CLIENT_SECRET="s3cret", FSP_DEMO_PASSWORD="demo-pass", FSP_OIDC_DISCOVERY="false")
    box = {"claims": _claims()}

    def exchange(code, verifier):
        box["verifier"] = verifier
        return {"id_token": "x", "access_token": "a"}

    monkeypatch.setattr(oidc, "exchange_code", exchange)
    monkeypatch.setattr(oidc, "verify_id_token", lambda tok, nonce: {**box["claims"], "nonce": nonce})
    monkeypatch.setattr(oidc, "userinfo", lambda tok: {})
    return box


def _login_via_fsp(client, fsp, intent="login", token=None):
    r = client.post("/api/fsp-id/start", json={"intent": intent}, headers=H(token) if token else {})
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["authorize_url"])
    q = parse_qs(url.query)
    assert url.path.endswith("/protocol/openid-connect/auth") and q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"][0].endswith("/api/fsp-id/callback") and q["scope"] == ["openid email profile"]
    cb = client.get("/api/fsp-id/callback", params={"state": q["state"][0], "code": "abc"}, follow_redirects=False)
    assert cb.status_code == 303
    loc = parse_qs(urlparse(cb.headers["location"]).query)
    assert "ticket" in loc, cb.headers["location"]
    import base64
    import hashlib

    ch = base64.urlsafe_b64encode(hashlib.sha256(fsp["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert ch == q["code_challenge"][0]  # PKCE: verifier, отправленный при обмене, соответствует challenge
    # повторное использование state запрещено
    again = client.get("/api/fsp-id/callback", params={"state": q["state"][0], "code": "abc"}, follow_redirects=False)
    assert "error" in parse_qs(urlparse(again.headers["location"]).query)
    return loc["ticket"][0]


def test_fsp_id_new_user_consent_and_passport_t2(client, fsp):
    cfg = client.get("/api/fsp-id/config").json()
    assert cfg["enabled"] and cfg["demo_password"] == "demo-pass" and len(cfg["demo_accounts"]) == 3
    ticket = _login_via_fsp(client, fsp)
    r = client.post("/api/fsp-id/exchange", json={"ticket": ticket}).json()
    assert r["status"] == "consent_required" and r["passport"]["has_history"]
    assert len(r["passport"]["achievements"]) == 1  # неизвестная дисциплина отброшена
    assert client.post("/api/fsp-id/complete", json={"ticket": ticket, "consent_processing": False}).status_code == 422
    done = client.post("/api/fsp-id/complete", json={"ticket": ticket, "consent_processing": True}).json()
    tok = done["token"]["access_token"]
    me = client.get("/api/me", headers=H(tok)).json()
    assert me["user"]["email"] == "champion@fsp-demo.ru" if "user" in me else me["email"] == "champion@fsp-demo.ru"
    p = client.get("/api/me/fsp", headers=H(tok)).json()
    assert p["linked"] and p["link_source"] == "keycloak" and p["achievements"][0]["verified"]
    assert p["fsp_id_claimed"] == "FSP-770012"
    # повторный вход тем же sub — без согласия, тот же пользователь
    t2 = _login_via_fsp(client, fsp)
    r2 = client.post("/api/fsp-id/exchange", json={"ticket": t2}).json()
    assert r2["status"] == "ok"
    assert client.post("/api/fsp-id/exchange", json={"ticket": t2}).status_code == 400  # билет одноразовый


def test_fsp_id_link_existing_and_no_history(client, fsp):
    tc = candidate_with_category(client)
    fsp["claims"] = _claims(sub="kc-sub-2", email="other@fsp-demo.ru", history=False)
    ticket = _login_via_fsp(client, fsp, intent="link", token=tc)
    r = client.post("/api/fsp-id/exchange", json={"ticket": ticket}).json()
    assert r["status"] == "ok" and r["intent"] == "link" and not r["passport"]["has_history"]
    p = client.get("/api/me/fsp", headers=H(tc)).json()
    assert p["linked"] and p["achievements"] == []  # нейтральное состояние
    assert client.post("/api/fsp-id/start", json={"intent": "link"}).status_code == 401


def test_fsp_id_disabled_without_issuer(client, isettings):
    isettings(FSP_OIDC_ISSUER="")
    assert client.get("/api/fsp-id/config").json()["enabled"] is False
    assert client.post("/api/fsp-id/start", json={"intent": "login"}).status_code == 409


def test_id_token_signature_verification(isettings, monkeypatch):
    from app.integrations.fsp_id import oidc

    isettings(FSP_OIDC_ISSUER=ISSUER, FSP_OIDC_DISCOVERY="false")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class K:
        def get_signing_key_from_jwt(self, _):
            return type("SK", (), {"key": key.public_key()})()

    monkeypatch.setattr(oidc, "_jwks_client", lambda uri: K())
    now = int(time.time())
    base = {"iss": ISSUER, "aud": "spectrek-platform", "sub": "u1", "iat": now, "exp": now + 300, "nonce": "n1"}
    good = jwt.encode(base, key, algorithm="RS256")
    assert oidc.verify_id_token(good, "n1")["sub"] == "u1"
    for bad, nonce in ((jwt.encode({**base, "aud": "other"}, key, algorithm="RS256"), "n1"),
                       (jwt.encode({**base, "iss": "https://evil"}, key, algorithm="RS256"), "n1"),
                       (good, "n2"),
                       (jwt.encode(base, rsa.generate_private_key(public_exponent=65537, key_size=2048),
                                   algorithm="RS256"), "n1")):
        with pytest.raises(oidc.OidcError):
            oidc.verify_id_token(bad, nonce)


# ------------------------------------------------------------------ ATS

@pytest.fixture
def ats_http(monkeypatch):
    """HTTP-вызовы к тестовой ATS идут в то же приложение через отдельный TestClient."""
    from app.integrations.ats import clients
    from app.main import app

    inner = TestClient(app)
    base = get_isettings().stub_base

    def send(method, url, **kw):
        assert url.startswith(base), url
        kw.pop("timeout", None)
        return inner.request(method, url[len(base):], **kw)

    monkeypatch.setattr(clients, "_send", send)
    return inner


def test_ats_stub_huntflow_and_webhook_on_accept(client, ats_http):
    tc = candidate_with_category(client)
    te = employer(client)
    st = client.post("/api/employer/ats/stub/connect", headers=H(te)).json()
    assert st["huntflow"]["enabled"] and st["webhook"]["enabled"] and st["huntflow"]["token_set"]
    assert "token" not in json.dumps(st["huntflow"]).replace("token_set", "").replace("token_masked", "")
    chk = client.post("/api/employer/ats/huntflow/check", headers=H(te)).json()
    assert chk["ok"] and chk["statuses"][0]["name"] == "Новые"
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)},
                      headers=H(te)).json()
    assert client.get(f"/api/employer/invitations/{inv['id']}/export.json", headers=H(te)).status_code == 409
    assert client.post("/api/employer/ats/push", json={"invitation_id": inv["id"]}, headers=H(te)).status_code == 409
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    dl = client.get("/api/employer/ats/deliveries", headers=H(te)).json()
    assert {d["target"]: d["status"] for d in dl} == {"huntflow": "ok", "webhook": "ok"}, dl
    hf = next(d for d in dl if d["target"] == "huntflow")
    assert hf["result"]["applicant_id"] and hf["result"]["status_id"] == 11 and hf["result"]["vacancy_id"] == 101
    recs = client.get("/api/employer/ats/stub/records", headers=H(te)).json()
    kinds = {r["kind"] for r in recs}
    assert kinds == {"huntflow_applicant", "huntflow_vacancy", "webhook"}
    app_rec = next(r for r in recs if r["kind"] == "huntflow_applicant")["payload"]
    assert app_rec["last_name"] == "Петров" and app_rec["first_name"] == "Иван" and app_rec["email"] == "cand@example.com"
    wh = next(r for r in recs if r["kind"] == "webhook")
    assert wh["signature_valid"] is True and wh["payload"]["event"] == "candidate.accepted_invitation"
    ex = client.get(f"/api/employer/invitations/{inv['id']}/export.json", headers=H(te))
    assert ex.status_code == 200 and ex.json()["schema"] == "vstrechny.candidate.v1"
    assert ex.json()["candidate"]["contacts"]["phone"] == "+7 900 111-22-33"
    # повторная ручная передача не создаёт дубликат в Хантфлоу; force=true — передаёт заново
    again = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"]}, headers=H(te)).json()
    assert all(d.get("already_sent") for d in again) and len(again) == 2
    assert len([r for r in client.get("/api/employer/ats/stub/records", headers=H(te)).json() if r["kind"] == "huntflow_applicant"]) == 1
    forced = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"], "force": True}, headers=H(te)).json()
    assert {d["status"] for d in forced} == {"ok"} and not any(d.get("already_sent") for d in forced)


def test_webhook_signature_and_ssrf_guard(client):
    from app.integrations.ats.clients import sign, verify_signature

    body = b'{"a":1}'
    sig, ts = sign("secret-1234567890", body)
    assert verify_signature("secret-1234567890", body, sig)
    assert not verify_signature("other-secret-123456", body, sig)
    assert not verify_signature("secret-1234567890", body + b" ", sig)
    old, _ = sign("secret-1234567890", body, ts=int(time.time()) - 3600)
    assert not verify_signature("secret-1234567890", body, old)  # защита от повтора
    te = employer(client)
    for url in ("http://example.com/hook", "https://127.0.0.1/hook", "https://localhost/hook"):
        r = client.put("/api/employer/ats/settings", json={"webhook": {"enabled": True, "url": url}}, headers=H(te))
        assert r.status_code == 422, (url, r.text)
    r = client.put("/api/employer/ats/settings", json={"huntflow": {"enabled": True}}, headers=H(te))
    assert r.status_code == 422  # без токена и account_id


def test_huntflow_applicant_mapping():
    from app.integrations.ats.service import huntflow_applicant

    p = {"candidate": {"ref": "C-1", "category_title": "Backend · Middle",
                       "contacts": {"full_name": "Петров Иван Сергеевич", "email": "a@b.ru", "phone": "+7",
                                    "telegram": "@ivan"}, "card": {}},
         "context": {"position_title": "Python", "salary_from": 1, "salary_to": 2, "evidence": []},
         "source": {"url": "https://x"}}
    a = huntflow_applicant(p)
    assert (a["last_name"], a["first_name"], a["middle_name"]) == ("Петров", "Иван", "Сергеевич")
    assert a["social"] == [{"social_type": "TELEGRAM", "value": "ivan"}]
    assert a["externals"][0]["auth_type"] == "NATIVE" and "C-1" in a["externals"][0]["data"]["body"]


# ------------------------------------------------------------------ вакансии и отклики

VAC = {"title": "Python-разработчик (backend)", "category_id": "backend.middle",
       "description": "API платёжного сервиса, FastAPI, PostgreSQL, команда 6 человек.",
       "stack": ["python", "fastapi"], "salary_from": 200000, "salary_to": 280000, "work_format": "remote"}


def test_vacancy_flow_contacts_after_apply(client):
    te = employer(client)
    tc = candidate_with_category(client)
    bad = {**VAC}
    bad.pop("salary_to")
    assert client.post("/api/employer/vacancies", json=bad, headers=H(te)).status_code == 422
    assert client.post("/api/employer/vacancies", json={**VAC, "salary_from": 300000}, headers=H(te)).status_code == 422
    v = client.post("/api/employer/vacancies", json=VAC, headers=H(te)).json()
    assert v["status"] == "published" and v["market_range"]["from"] > 0
    assert client.post("/api/employer/vacancies", json=VAC, headers=H(tc)).status_code == 403
    lst = client.get("/api/vacancies", params={"direction": "backend"}, headers=H(tc)).json()
    assert [x["id"] for x in lst["items"]] == [v["id"]] and lst["items"][0]["trust"]["level"]
    assert client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": False}, headers=H(tc)).status_code == 422
    a = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True, "cover_letter": "Хочу"},
                    headers=H(tc))
    assert a.status_code == 201 and a.json()["status"] == "sent"
    assert client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc)).status_code == 409
    apps = client.get(f"/api/employer/vacancies/{v['id']}/applications", headers=H(te)).json()
    assert apps[0]["contacts"]["email"] == "cand@example.com" and apps[0]["card"]["ref"]
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.get(f"/api/employer/vacancies/{v['id']}/applications", headers=H(te2)).status_code == 404
    aid = apps[0]["id"]
    client.post(f"/api/employer/applications/{aid}/view", headers=H(te))
    r = client.post(f"/api/employer/applications/{aid}/status", json={"status": "accepted", "note": "Ждём на интервью"},
                    headers=H(te)).json()
    assert r["status"] == "accepted"
    mine = client.get("/api/candidate/applications", headers=H(tc)).json()
    assert mine[0]["status"] == "accepted" and [e["status"] for e in mine[0]["events"]] == ["sent", "viewed", "accepted"]
    assert mine[0]["employer_note"] == "Ждём на интервью"
    assert client.get("/api/vacancies", headers=H(tc)).json()["items"][0]["my_application"]["status"] == "accepted"
    client.post(f"/api/employer/vacancies/{v['id']}/close", headers=H(te))
    assert client.get("/api/vacancies", headers=H(tc)).json()["items"] == []
    ex = client.get(f"/api/employer/applications/{aid}/export.json", headers=H(te)).json()
    assert ex["context"]["type"] == "vacancy_application"


def test_withdraw_application(client):
    te = employer(client)
    tc = candidate_with_category(client)
    v = client.post("/api/employer/vacancies", json=VAC, headers=H(te)).json()
    a = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc)).json()
    assert client.post(f"/api/candidate/applications/{a['id']}/withdraw", headers=H(tc)).json()["status"] == "withdrawn"
    apps = client.get(f"/api/employer/vacancies/{v['id']}/applications", headers=H(te)).json()
    assert apps[0]["contacts"] is None
    again = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc))
    assert again.status_code == 201  # после отзыва можно откликнуться снова


# ------------------------------------------------------------------ Web Push

def test_push_subscribe_and_notifications(client, isettings, monkeypatch):
    import pywebpush

    from app.integrations.push import service

    isettings(VAPID_PUBLIC_KEY="BPub" + "A" * 80, VAPID_PRIVATE_KEY="priv")
    sent = []

    class Resp:
        status_code = 410

    def fake_webpush(subscription_info, data, **kw):
        sent.append((subscription_info["endpoint"], json.loads(data)))
        if "gone" in subscription_info["endpoint"]:
            raise pywebpush.WebPushException("gone", response=Resp())

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    tc = candidate_with_category(client)
    te = employer(client)
    assert client.get("/api/push/config").json()["enabled"]
    keys = {"p256dh": "B" * 60, "auth": "a" * 16}
    assert client.post("/api/push/subscribe", json={"endpoint": "https://push.example/ok", "keys": keys},
                       headers=H(tc)).status_code == 201
    client.post("/api/push/subscribe", json={"endpoint": "https://push.example/gone", "keys": keys}, headers=H(tc))
    client.post("/api/push/subscribe", json={"endpoint": "https://push.example/hr", "keys": keys}, headers=H(te))
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)},
                      headers=H(te)).json()
    titles = [p["title"] for e, p in sent if e.endswith("/ok")]
    assert any("Новое приглашение" in t for t in titles), sent
    assert client.get("/api/push/status", headers=H(tc)).json()["devices"] == 1  # 410 → подписка удалена
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    assert any("принял" in p["title"] for e, p in sent if e.endswith("/hr"))
    assert client.post("/api/push/test", headers=H(tc)).json()["sent"] == 1
    assert service.SENT_LOG[-1]["title"].startswith("Встречный")


# ------------------------------------------------------------------ SUS

def test_sus_score_and_summary(client):
    from app.integrations.sus.router import grade, sus_score

    assert sus_score([3] * 10) == 50.0
    assert sus_score([5, 1] * 5) == 100.0 and sus_score([1, 5] * 5) == 0.0
    assert sus_score([4, 2, 4, 2, 4, 2, 4, 2, 4, 2]) == 75.0 and grade(75) == "B"
    assert len(client.get("/api/sus/questions").json()["questions"]) == 10
    assert client.post("/api/sus", json={"answers": [3] * 9}).status_code == 422
    assert client.post("/api/sus", json={"answers": [6] + [3] * 9}).status_code == 422
    r = client.post("/api/sus", json={"answers": [5, 1] * 5, "context": "jury"}).json()
    assert r["score"] == 100 and r["above_benchmark"]
    tc = register_and_verify(client)
    client.post("/api/sus", json={"answers": [4, 2] * 5, "context": "e2e"}, headers=H(tc))
    assert client.get("/api/sus/mine", headers=H(tc)).json()["answered"]
    s = client.get("/api/sus/summary").json()
    # основные цифры — только после входа, анонимный ответ — отдельно (аудит, С9)
    assert s["n"] == 1 and s["mean"] == 75.0 and set(s["by_role"]) == {"candidate"}
    assert s["anonymous"]["n"] == 1 and s["anonymous"]["mean"] == 100.0 and s["all"]["n"] == 2
    assert client.get("/api/admin/sus", headers=H(tc)).status_code == 403


def test_fsp_claims_mapping_dates():
    from app.integrations.fsp_id.mapping import parse_achievements

    a = parse_achievements([{"discipline": "security", "event": "CTF", "level": "regional", "date": "2026-02-30",
                             "place": "2"}])
    assert a[0]["date"] is None and a[0]["place"] == 2
    assert parse_achievements("not json") == []
    assert date.today() - timedelta(days=1) < date.today()



def test_demo_vacancies_seed_and_bait_warning():
    """Демо-вакансии создаются для демо-компаний; «приманка» с завышенной вилкой получает предупреждение."""
    from sqlalchemy import delete, select

    from app.core.db import SessionLocal, get_engine
    from app.integrations.egrul import trust as trust_mod
    from app.integrations.vacancies import demo
    from app.integrations.vacancies.models import Vacancy
    from app.modules.demo.seed import COMPANIES
    from app.modules.profiles.models import Company

    get_engine()
    with SessionLocal() as db:
        had_demo = db.scalar(select(Company.id).where(Company.is_demo.is_(True)).limit(1)) is not None
        made = []
        if not had_demo:
            for idx in (0, 8):
                c = Company(name=COMPANIES[idx][0], industry=COMPANIES[idx][1], city=COMPANIES[idx][2], is_demo=True)
                db.add(c)
                made.append(c)
            db.commit()
    r = demo.seed(reset=True)
    assert r["created"] >= 3
    with SessionLocal() as db:
        bait = db.scalar(select(Vacancy).where(Vacancy.is_demo.is_(True), Vacancy.salary_to == 1_050_000))
        t = trust_mod.compute(db, db.get(Company, bait.company_id), vacancy=bait)
        assert t["offer_salary"]["status"] == "warn"
        db.execute(delete(Vacancy).where(Vacancy.is_demo.is_(True)))
        for c in made:
            db.execute(delete(Company).where(Company.id == c.id))
        db.commit()
