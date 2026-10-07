"""ФСП v2, OIDC discovery/маппинг, API реестра и безопасный оффер 16–17."""
from datetime import date, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.integrations.fsp_id import mapping, oidc
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.fsp.rating import details, recency
from app.modules.fsp.registry import mock_passport
from app.modules.profiles.models import CandidateProfile
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, ONBOARDING, pass_test
from tests.test_integrations import fsp, isettings, _login_via_fsp, ISSUER  # fixtures

TODAY = date(2026, 10, 7)


def achievement(**extra):
    return SimpleNamespace(verified=True, event_name="Открытый турнир", event_date=TODAY, place=1,
                           discipline="product", event_level="national", result_title="победитель", **extra)


@pytest.mark.parametrize("discipline", ["algorithmic", "product", "security", "robotics", "uav"])
@pytest.mark.parametrize("level", ["school", "regional", "interregional", "national", "international", "online_selection"])
def test_equal_disciplines_and_event_types(discipline, level):
    a = achievement()
    a.discipline, a.event_level = discipline, level
    assert details([a], today=TODAY)["strength"] == 0.8


def test_result_order_diminishing_and_duplicates():
    def a(place, name):
        x = achievement()
        x.place, x.event_name, x.result_title = place, name, None
        return x
    assert details([a(1, "1")], today=TODAY)["strength"] > details([a(2, "2")], today=TODAY)["strength"] > details([a(7, "3")], today=TODAY)["strength"] > details([a(None, "4")], today=TODAY)["strength"]
    strengths = [details([a(2, str(j)) for j in range(n)], today=TODAY)["strength"] for n in range(1, 8)]
    assert all(x < y for x, y in zip(strengths, strengths[1:]))
    assert strengths[2] - strengths[1] < strengths[1] - strengths[0]
    x = achievement()
    assert details([x, x], today=TODAY)["competitions"] == 1
    x.verified = False
    assert details([x], today=TODAY)["strength"] == 0
    assert details([], today=TODAY)["strength"] == 0


def test_recency_soft_after_twelve_months():
    assert recency(TODAY - timedelta(days=365), TODAY) == 1
    assert 0.7 < recency(TODAY - timedelta(days=730), TODAY) < 1
    assert recency(TODAY + timedelta(days=30), TODAY) == recency(None, TODAY) == 1
    assert recency(TODAY - timedelta(days=20 * 365), TODAY) >= 0.7


def test_discovery_non_keycloak_paths_and_backchannel(isettings, monkeypatch):
    isettings(FSP_OIDC_ISSUER=ISSUER, FSP_OIDC_INTERNAL_BASE="http://kc/realm", FSP_OIDC_DISCOVERY="true")
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, request=httpx.Request("GET", url), json={
            "issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/exchange", "userinfo_endpoint": ISSUER + "/profile",
            "jwks_uri": ISSUER + "/keys"})
    monkeypatch.setattr(oidc.httpx, "get", get)
    oidc._discovery.cache_clear()
    ep = oidc.endpoints()
    assert ep["authorization_endpoint"] == ISSUER + "/authorize"
    assert ep["token_endpoint"] == "http://kc/realm/exchange"
    assert ep["jwks_uri"] == "http://kc/realm/keys"
    assert oidc.endpoints() == ep and len(calls) == 1
    oidc._discovery.cache_clear()


def test_discovery_failure_no_silent_fallback(client, isettings, monkeypatch):
    isettings(FSP_OIDC_ISSUER=ISSUER, FSP_OIDC_DISCOVERY="true")
    def get(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url), json={"issuer": "https://other"})
    monkeypatch.setattr(oidc.httpx, "get", get)
    oidc._discovery.cache_clear()
    r = client.post("/api/fsp-id/start", json={"intent": "login"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "fsp_discovery_unavailable"
    oidc._discovery.cache_clear()


def test_nested_claims_configurable_without_code(isettings):
    isettings(FSP_OIDC_CLAIMS_MAP='{"fsp_id":"participant.id","fsp_achievements":"participant.results","email":"mail"}')
    claims = {"sub": "sub1", "iss": ISSUER, "participant": {"id": "FSP-770012", "results": []}, "mail": "a@ex.ru"}
    assert mapping.normalize_claims(claims)["fsp_id"] == "FSP-770012"
    assert mapping.normalize_claims(claims)["email"] == "a@ex.ru"
    assert mapping.identity_subject(claims) != mapping.identity_subject({**claims, "iss": "https://other"})
    isettings(FSP_OIDC_CLAIMS_MAP='{"sub":"participant.id"}')
    with pytest.raises(ValueError):
        mapping.normalize_claims(claims)


def test_token_auth_post_and_none(isettings, monkeypatch):
    isettings(FSP_OIDC_ISSUER=ISSUER, FSP_OIDC_DISCOVERY="false",
              FSP_OIDC_CLIENT_SECRET="only-test", FSP_OIDC_TOKEN_AUTH_METHOD="client_secret_post")
    calls = []
    def post(url, **kw):
        calls.append(kw)
        return httpx.Response(200, json={"id_token": "test"})
    monkeypatch.setattr(oidc.httpx, "post", post)
    oidc.exchange_code("c", "v")
    assert calls[0]["auth"] is None and calls[0]["data"]["client_secret"] == "only-test"
    isettings(FSP_OIDC_TOKEN_AUTH_METHOD="none")
    oidc.exchange_code("c", "v")
    assert calls[1]["auth"] is None and "client_secret" not in calls[1]["data"]


def test_registry_contract_mock(client):
    r = client.get("/api/fsp-registry/v1/participants/FSP-770012/achievements")
    assert r.status_code == 200 and r.json() == mock_passport("FSP-770012").model_dump(mode="json")
    a = r.json()["achievements"][0]
    assert a["team"]["members_count"] == 3 and a["result"] == "winner" and "evsk_code" in a
    assert client.get("/api/fsp-registry/v1/participants/FSP-770014/achievements").json()["achievements"] == []
    assert client.get("/api/fsp-registry/v1/participants/REAL-123/achievements").status_code == 404


def test_registry_platform_import_and_idempotence(client, fsp, isettings):
    isettings(FSP_REGISTRY_MODE="mock")
    ticket = _login_via_fsp(client, fsp)
    done = client.post("/api/fsp-id/complete", json={"ticket": ticket, "consent_processing": True}).json()
    token = done["token"]["access_token"]
    p = client.get("/api/me/fsp", headers=H(token)).json()
    assert p["identity_linked"] and p["registry"]["demo"] and p["sport_rank"] == "КМС"
    assert p["rating"]["competitions"] == 1 and p["achievements"][0]["verified"]
    _login_via_fsp(client, fsp)
    uid = uuid.UUID(client.get("/api/me", headers=H(token)).json()["id"])
    with SessionLocal() as db:
        pp = db.scalar(select(FspPassport).where(FspPassport.user_id == uid))
        rows = db.scalars(select(FspAchievement).where(FspAchievement.passport_id == pp.id)).all()
        assert len(rows) == 1 and rows[0].team_result["members_count"] == 3


def test_registry_outage_preserves_history_and_cup_t1(client, fsp, isettings, monkeypatch):
    from app.core.enums import FspEventLevel
    from app.modules.fsp import registry
    token = register_and_verify(client)
    ticket = _login_via_fsp(client, fsp, intent="link", token=token)
    assert client.post("/api/fsp-id/exchange", json={"ticket": ticket}).status_code == 200
    uid = uuid.UUID(client.get("/api/me", headers=H(token)).json()["id"])
    with SessionLocal() as db:
        pp = db.scalar(select(FspPassport).where(FspPassport.user_id == uid))
        db.add(FspAchievement(passport_id=pp.id, discipline="product", event_name="Наш кубок",
                              event_level=FspEventLevel.platform, verified=False, source_ref="cup:123"))
        db.commit()
    _login_via_fsp(client, fsp)
    with SessionLocal() as db:
        assert db.scalar(select(FspAchievement).where(FspAchievement.source_ref == "cup:123"))
    isettings(FSP_REGISTRY_MODE="external", FSP_REGISTRY_BASE_URL="https://registry.example/v1")
    monkeypatch.setattr(registry, "fetch_passport", lambda _: (_ for _ in ()).throw(ValueError("offline")))
    _login_via_fsp(client, fsp)
    p = client.get("/api/me/fsp", headers=H(token)).json()
    assert p["registry_warning"] and len(p["achievements"]) == 1


def _youth(client):
    token = register_and_verify(client)
    client.put("/api/me/onboarding", json=ONBOARDING, headers=H(token))
    pass_test(client, token)
    employer = register_and_verify(client, "hr@example.com", role="employer", company_name="Компания")
    ref = client.get("/api/me/card", headers=H(token)).json()["ref"]
    payload = {"candidate_ref": ref, "position_title": "Стажёр Backend", "offer_description": "Стажировка в команде разработки API",
               "salary_from": 50000, "salary_to": 70000, "contact_method": "hr@example.com"}
    return token, employer, ref, payload


def test_youth_offer_guards_and_acceptance(client):
    token, employer, ref, payload = _youth(client)
    before = client.get("/api/me/card", headers=H(token)).json()["rating_score"]
    patch = {"age_group": "16-17", "parental_consent": False}
    r = client.patch("/api/me/candidate-profile", json=patch, headers=H(token))
    assert r.status_code == 200
    assert client.get("/api/me/card", headers=H(token)).json()["rating_score"] == before
    assert client.post("/api/employer/invitations", json=payload, headers=H(employer)).json()["detail"]["code"] == "parental_consent_required"
    r = client.patch("/api/me/candidate-profile", json={"parental_consent": True}, headers=H(token))
    assert r.json()["candidate"]["parental_consent_at"]
    assert client.post("/api/employer/invitations", json=payload, headers=H(employer)).json()["detail"]["code"] == "youth_offer_restricted"
    terms = {"format": "internship", "reduced_time": True, "employer_acknowledged": True}
    r = client.post("/api/employer/invitations", json={**payload, "employment_terms": terms}, headers=H(employer))
    assert r.status_code == 201, r.text
    inv_id = r.json()["id"]
    assert r.json()["employment_terms"] == terms
    client.patch("/api/me/candidate-profile", json={"parental_consent": False}, headers=H(token))
    assert client.post(f"/api/candidate/invitations/{inv_id}/accept", headers=H(token)).status_code == 422
    client.patch("/api/me/candidate-profile", json={"parental_consent": True}, headers=H(token))
    assert client.post(f"/api/candidate/invitations/{inv_id}/accept", headers=H(token)).status_code == 200


def test_youth_14_15_and_invalid_age(client):
    token, employer, ref, payload = _youth(client)
    client.patch("/api/me/candidate-profile", json={"age_group": "14-15", "parental_consent": True}, headers=H(token))
    assert client.post("/api/employer/invitations", json=payload, headers=H(employer)).json()["detail"]["code"] == "youth_offer_not_supported"
    assert client.patch("/api/me/candidate-profile", json={"age_group": "15"}, headers=H(token)).status_code == 422
    assert client.patch("/api/me/candidate-profile", json={"age_group": None}, headers=H(token)).status_code == 422
    assert client.patch("/api/me/candidate-profile", json={"age_group": "18+"}, headers=H(token)).json()["candidate"]["parental_consent"] is False


def test_fsp_registration_employer_role_bound_to_state(client, fsp):
    r = client.post("/api/fsp-id/start", json={"intent": "login", "registration_role": "employer"})
    q = parse_qs(urlparse(r.json()["authorize_url"]).query)
    cb = client.get("/api/fsp-id/callback", params={"state": q["state"][0], "code": "abc"}, follow_redirects=False)
    ticket = parse_qs(urlparse(cb.headers["location"]).query)["ticket"][0]
    assert client.post("/api/fsp-id/exchange", json={"ticket": ticket}).json()["registration_role"] == "employer"
    r = client.post("/api/fsp-id/complete", json={"ticket": ticket, "consent_processing": True,
                                                "company_name": "ООО Демо ФСП", "registration_role": "admin"})
    token = r.json()["token"]["access_token"]
    me = client.get("/api/me", headers=H(token)).json()
    assert me["role"] == "employer" and me["employer"]["company"]["name"] == "ООО Демо ФСП"
    assert me["candidate"] is None


def test_manual_fsp_id_cannot_import_t2(client):
    token = register_and_verify(client)
    client.post("/api/me/fsp/link", json={"fsp_id": "FSP-770012"}, headers=H(token))
    assert client.post("/api/me/fsp/registry-sync", json={}, headers=H(token)).status_code == 409


def test_demo_registry_sync_preserves_sandbox_identity(client):
    token = client.post("/api/jury/login", json={"persona": "candidate", "scenario": "new"}).json()["access_token"]
    before = client.get("/api/me", headers=H(token)).json()
    r = client.post("/api/me/fsp/registry-sync", json={}, headers=H(token))
    assert r.status_code == 200 and r.json()["registry"]["demo"] is True
    assert r.json()["identity_linked"] is False and r.json()["link_source"] == "demo"
    assert r.json()["rating"]["competitions"] == 1
    assert client.get("/api/me", headers=H(token)).json()["candidate"]["public_ref"] == before["candidate"]["public_ref"]
