"""Я29: тарифы работодателя (лимит приглашений, функции, демо-счёт, «Партнёр ФСП») и блок «Польза для ФСП».

Без TARIFFS_ENABLED ничего не меняется: методы 404, лимита нет, ответы других модулей прежние.
"""
from datetime import UTC, datetime
import json

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref
from tests.test_fsp_cabinet import _login, _platform_demo, analyst_token


@pytest.fixture
def tariffs_on(monkeypatch):
    monkeypatch.setenv("TARIFFS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _cands(client, n: int) -> list[str]:
    return [my_ref(client, candidate_with_category(client, f"t{i}@example.com")) for i in range(n)]


def _invite(client, te, ref):
    return client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te))


def test_pure_rules():
    from app.modules.tariffs import plans as P
    from app.modules.tariffs.service import month_window

    assert P.vat_of(9_900) == 1_785  # НДС 22 % внутри цены: 9900 × 22 / 122
    assert [p["id"] for p in P.PLANS] == ["start", "hire", "partner"] and P.plan("nope")["id"] == "start"
    assert P.plan("start")["price_rub_month"] == 0 and P.plan("partner")["self_service"] is False
    assert P.plan("start")["invites_per_month"] < P.plan("hire")["invites_per_month"] < P.plan("partner")["invites_per_month"]
    # 31.10 22:30 UTC — это уже 01.11 01:30 по Москве: месяц лимита — ноябрь
    s, e = month_window(datetime(2026, 10, 31, 22, 30, tzinfo=UTC))
    assert s == datetime(2026, 10, 31, 21, 0, tzinfo=UTC) and e == datetime(2026, 11, 30, 21, 0, tzinfo=UTC)
    s, _ = month_window(datetime(2026, 10, 11, 10, 0, tzinfo=UTC))
    assert s == datetime(2026, 9, 30, 21, 0, tzinfo=UTC)


def test_flag_off_changes_nothing(client):
    assert client.get("/api/meta").json()["tariffs"]["enabled"] is False
    assert client.get("/api/tariffs").json()["detail"]["code"] == "tariffs_disabled"
    te = employer(client)
    assert client.get("/api/employer/tariff", headers=H(te)).status_code == 404
    refs = _cands(client, 4)
    for ref in refs:  # больше лимита «Старта» — без флага лимита нет
        assert _invite(client, te, ref).status_code == 201
    inv = client.get("/api/employer/invitations", headers=H(te)).json()[0]
    assert "fsp_partner" not in inv["company"]
    ta = analyst_token(client)
    assert client.get("/api/fsp-cabinet/benefit", headers=H(ta)).status_code == 404
    assert client.get("/api/fsp-cabinet/partners", headers=H(ta)).status_code == 404


def test_start_limit_upgrade_with_demo_invoice(client, tariffs_on):
    assert client.get("/api/meta").json()["tariffs"]["enabled"] is True
    pub = client.get("/api/tariffs")
    assert pub.status_code == 200 and pub.json()["candidates_free"] is True and pub.json()["price_is_stub"] is True
    assert [p["id"] for p in pub.json()["plans"]] == ["start", "hire", "partner"]
    te = employer(client)
    st = client.get("/api/employer/tariff", headers=H(te)).json()
    assert st["plan_id"] == "start" and st["is_default"] and st["usage"]["invites_left"] == 3
    refs = _cands(client, 4)
    for ref in refs[:3]:
        assert _invite(client, te, ref).status_code == 201
    r = _invite(client, te, refs[3])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "tariff_limit"
    msg = r.json()["detail"]["message"]
    assert "«Старт»" in msg and "«Найм»" in msg and "Тарифы" in msg
    st = client.get("/api/employer/tariff", headers=H(te)).json()
    assert st["usage"]["invites_used"] == 3 and st["usage"]["invites_left"] == 0
    # «Партнёр ФСП» сам не выбирается; «Найм» — демо-счёт и подключение сразу
    assert client.post("/api/employer/tariff", json={"plan": "partner"}, headers=H(te)).json()["detail"]["code"] == "partner_by_fsp"
    up = client.post("/api/employer/tariff", json={"plan": "hire"}, headers=H(te))
    assert up.status_code == 200, up.text
    b = up.json()
    assert b["plan_id"] == "hire" and b["invoice"]["amount_rub"] == 9_900 and b["invoice"]["vat_rub"] == 1_785
    assert b["invoice"]["status"] == "demo" and b["invoice"]["number"].startswith("Д-") and len(b["invoices"]) == 1
    assert client.post("/api/employer/tariff", json={"plan": "hire"}, headers=H(te)).json()["detail"]["code"] == "plan_same"
    assert _invite(client, te, refs[3]).status_code == 201
    assert client.get("/api/employer/tariff", headers=H(te)).json()["usage"]["invites_left"] == 26
    # обратно на «Старт»: лимит снова 3, все использованы
    assert client.post("/api/employer/tariff", json={"plan": "start"}, headers=H(te)).json()["usage"]["invites_left"] == 0


def test_features_by_plan(client, tariffs_on):
    te = employer(client)
    r = client.post("/api/employer/ats/stub/connect", headers=H(te))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "tariff_feature" and "ATS" in r.json()["detail"]["message"]
    r = client.post("/api/employer/assignments", json={}, headers=H(te))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "tariff_feature"
    assert client.get("/api/employer/ats/settings", headers=H(te)).status_code == 200  # смотреть настройки можно
    client.post("/api/employer/tariff", json={"plan": "hire"}, headers=H(te))
    assert client.post("/api/employer/assignments", json={}, headers=H(te)).status_code == 422  # дальше — проверка полей


def test_partner_request_grant_badge_and_scope(client, tariffs_on):
    te = employer(client)
    [ref] = _cands(client, 1)
    assert _invite(client, te, ref).status_code == 201
    st = client.post("/api/employer/tariff/partner-request", json={"note": "Спонсор регионального этапа"}, headers=H(te))
    assert st.status_code == 200 and st.json()["partner_requested_at"]
    ta = analyst_token(client)
    ov = client.get("/api/fsp-cabinet/partners", headers=H(ta)).json()
    assert ov["partners"] == [] and [r["name"] for r in ov["requests"]] == ["ООО Ромашка"]
    req = ov["requests"][0]
    assert req["request_note"] == "Спонсор регионального этапа" and req["can_manage"] is True
    assert [c["name"] for c in client.get("/api/fsp-cabinet/partners/search?q=Ромаш", headers=H(ta)).json()] == ["ООО Ромашка"]
    g = client.post(f"/api/fsp-cabinet/partners/{req['company_id']}", json={"action": "grant", "note": "Договор №1"},
                    headers=H(ta))
    assert g.status_code == 200 and g.json()["fsp_partner"] and g.json()["plan_id"] == "partner"
    st = client.get("/api/employer/tariff", headers=H(te)).json()
    assert st["plan_id"] == "partner" and st["fsp_partner"] and st["usage"]["invites_limit"] == 100
    assert client.post("/api/employer/tariff", json={"plan": "hire"}, headers=H(te)).json()["detail"]["code"] == "partner_active"
    # метка видна кандидату: в приглашении и в карточке компании
    r = client.post("/api/auth/login", json={"email": "t0@example.com", "password": "Passw0rd!"})
    tc = r.json()["access_token"]
    inv = client.get("/api/candidate/invitations", headers=H(tc)).json()[0]
    assert inv["company"]["fsp_partner"] is True
    assert client.get(f"/api/companies/{req['company_id']}", headers=H(tc)).json()["fsp_partner"] is True
    # работодатель и кандидат метку не выдают
    for t in (te, tc):
        assert client.post(f"/api/fsp-cabinet/partners/{req['company_id']}", json={"action": "revoke"},
                           headers=H(t)).status_code == 403
    rv = client.post(f"/api/fsp-cabinet/partners/{req['company_id']}", json={"action": "revoke"}, headers=H(ta))
    assert rv.status_code == 200 and rv.json()["fsp_partner"] is False and rv.json()["plan_id"] == "start"
    # кабинет ФСП жюри не меняет метку компаний вне своей песочницы
    tj = _login(client, "fsp")["access_token"]
    r = client.post(f"/api/fsp-cabinet/partners/{req['company_id']}", json={"action": "grant"}, headers=H(tj))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "partner_scope"


def test_jury_defaults_and_demo_benefit(client, tariffs_on):
    """Песочница жюри: свой «Найм» (лимит не мешает), второй работодатель — партнёр ФСП; демо — три партнёра,
    «Найм» с демо-счетами, демо-наймы; блок «Польза для ФСП» без персональных данных, малые группы скрыты."""
    from app.modules.hiring.models import HiringOutcome
    from app.modules.tariffs import demo
    from app.modules.tariffs.models import CompanyTariff

    _platform_demo()
    j = _login(client, "employer")
    st = client.get("/api/employer/tariff", headers=H(j["access_token"])).json()
    assert st["plan_id"] == "hire" and st["is_default"] and st["usage"]["invites_left"] > 0
    with SessionLocal() as db:
        assert demo.has_demo(db) and demo.has_demo_hires(db)  # вход жюри досоздал демо тарифов
        rows = db.scalars(select(CompanyTariff)).all()
        assert sum(r.fsp_partner for r in rows) == 3 and sum(not r.fsp_partner for r in rows) == 4
    tf = _login(client, "fsp", j.get("scenario"))["access_token"]
    ov = client.get("/api/fsp-cabinet/partners", headers=H(tf)).json()
    names = [p["name"] for p in ov["partners"]]
    assert {"Демо: КиберЩит", "Демо: ПромИИ", "Демо: ЭдТех Лаб"} <= set(names)
    assert any(n.startswith("Демо жюри:") for n in names)  # «Логистика Онлайн» своей песочницы — партнёр по умолчанию
    ta = analyst_token(client)
    rep = client.get("/api/fsp-cabinet/benefit", headers=H(ta)).json()
    flat = json.dumps(rep, ensure_ascii=False)
    assert "@demo.invalid" not in flat and "CND-" not in flat and "Демо жюри" not in flat
    assert rep["invitations"] >= 100 and 0 < rep["fsp_bonus_share"] < 1
    assert rep["total"]["candidates_fsp"] >= 5 and rep["total"]["invited_fsp"] >= 5
    assert {p["name"] for p in rep["partners"]} == {"Демо: КиберЩит", "Демо: ПромИИ", "Демо: ЭдТех Лаб"}
    assert rep["partners_total"]["companies"] == 3 and rep["partners_total"]["invitations"] > 0
    assert {p["id"]: p["companies"] for p in rep["plans"]}["partner"] == 3
    for part in ("regions", "directions"):  # вторичное подавление: не бывает ровно одной скрытой группы
        rows_ = rep[part]
        assert rows_ and sum(1 for r in rows_ if r["candidates_fsp"] is None) != 1
        for r in rows_:
            for k in ("candidates_fsp", "invited_fsp", "accepted_fsp", "hired_fsp"):
                assert r[k] is None or r[k] == 0 or r[k] >= 5
    assert any(r["title"] == "Москва" for r in rep["regions"])
    with SessionLocal() as db:
        n_h = len(db.scalars(select(HiringOutcome).where(HiringOutcome.note == demo.MARK)).all())
        assert n_h > 0
    csv = client.get("/api/fsp-cabinet/benefit/export.csv", headers=H(ta))
    assert csv.status_code == 200 and "Партнёр ФСП" in csv.text and "Регион" in csv.text and "@" not in csv.text
    with SessionLocal() as db:  # удаление демо — чистое
        out = demo.delete_demo(db)
        assert out["tariffs"] == 7 and out["hired"] == n_h and not demo.has_demo(db)


def test_benefit_small_groups(client, tariffs_on):
    te = employer(client)
    refs = _cands(client, 2)
    for ref in refs:
        assert _invite(client, te, ref).status_code == 201
    ta = analyst_token(client)
    rep = client.get("/api/fsp-cabinet/benefit", headers=H(ta)).json()
    assert rep["total"]["candidates_fsp"] == 0 and rep["fsp_bonus_share"] is None and rep["partners"] == []
    assert all(r["invited_fsp"] in (0, None) for r in rep["regions"])
    flat = json.dumps(rep, ensure_ascii=False)
    for secret in ("Иван", "Петров", "@example.com", *refs):
        assert secret not in flat
