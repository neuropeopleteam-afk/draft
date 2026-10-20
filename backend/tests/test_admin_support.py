"""Тесты мини-админки (/api/admin/*), службы поддержки (/api/support) и заявок на тариф (/api/tariffs/request)."""
from __future__ import annotations

import uuid

from app.core.db import SessionLocal
from app.core.enums import UserRole
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.auth.service import issue_token
from tests.conftest import register_and_verify


def _admin_token() -> str:
    with SessionLocal() as db:
        u = User(
            email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("AdminPass123!"),
            role=UserRole.admin,
            is_email_verified=True,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return issue_token(u).access_token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_support_ticket_flow_and_admin_resolve(client):
    meta = client.get("/api/support")
    assert meta.status_code == 200
    assert meta.json()["support_email"] and len(meta.json()["categories"]) >= 4

    # гость без почты -> 422
    assert client.post("/api/support", json={"subject": "Вопрос", "message": "Текст обращения"}).status_code == 422

    # гость с почтой -> 201
    g = client.post(
        "/api/support",
        json={"email": "guest@example.com", "name": "Гость", "category": "general", "subject": "Вопрос гостя", "message": "Подскажите условия"},
    )
    assert g.status_code == 201
    gid = g.json()["ticket"]["id"]

    # вошедший кандидат -> почта берётся из профиля, обращение видно в /api/support/my
    tc = register_and_verify(client, email="sup-cand@example.com", full_name="Мария Тест")
    c_resp = client.post(
        "/api/support",
        json={"category": "technical", "subject": "Не приходит код", "message": "Проверьте доставку писем"},
        headers=_h(tc),
    )
    assert c_resp.status_code == 201
    tid = c_resp.json()["ticket"]["id"]
    my = client.get("/api/support/my", headers=_h(tc))
    assert my.status_code == 200
    assert [x["id"] for x in my.json()["items"]] == [tid]

    # не-админ не имеет доступа к /api/admin/*
    assert client.get("/api/admin/requests", headers=_h(tc)).status_code == 403

    # админ видит оба обращения и отвечает
    ta = _admin_token()
    reqs = client.get("/api/admin/requests", headers=_h(ta)).json()
    ids = {x["id"] for x in reqs["support_tickets"]}
    assert {gid, tid} <= ids

    res = client.post(
        "/api/admin/requests/support-resolve",
        json={"ticket_id": tid, "status": "resolved", "admin_reply": "Проблема исправлена, проверьте вход."},
        headers=_h(ta),
    )
    assert res.status_code == 200
    assert res.json()["ticket"]["status"] == "resolved"
    assert res.json()["ticket"]["admin_reply"] == "Проблема исправлена, проверьте вход."

    # кандидат видит ответ администратора в своих обращениях
    my_after = client.get("/api/support/my", headers=_h(tc)).json()["items"][0]
    assert my_after["status"] == "resolved" and "исправлена" in my_after["admin_reply"]


def test_tariff_request_and_admin_approval(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("TARIFFS_ENABLED", "true")
    get_settings.cache_clear()
    try:
        te = register_and_verify(client, email="emp-req@example.com", role="employer", company_name="ООО Вектор")
        # изначально тариф «Старт»
        st0 = client.get("/api/employer/tariff", headers=_h(te)).json()
        assert st0["plan_id"] == "start"

        # отправка заявки на тариф «Найм» НЕ включает тариф автоматически
        r = client.post(
            "/api/tariffs/request",
            json={"plan": "hire", "contact_phone": "+7 999 000-11-22", "comment": "Нужно 30 приглашений и Поток"},
            headers=_h(te),
        )
        assert r.status_code == 201
        req_id = r.json()["request"]["id"]
        assert r.json()["request"]["status"] == "pending"
        assert r.json()["request"]["company_name"] == "ООО Вектор"

        # тариф всё ещё «Старт» до одобрения админом
        st1 = client.get("/api/employer/tariff", headers=_h(te)).json()
        assert st1["plan_id"] == "start"

        # работодатель видит свою заявку
        my_reqs = client.get("/api/tariffs/requests/my", headers=_h(te)).json()["items"]
        assert len(my_reqs) == 1 and my_reqs[0]["id"] == req_id and my_reqs[0]["status"] == "pending"

        # администратор одобряет заявку -> тариф «Найм» включается
        ta = _admin_token()
        approve = client.post(
            "/api/admin/requests/tariff-resolve",
            json={"request_id": req_id, "action": "approve", "admin_note": "Договор согласован"},
            headers=_h(ta),
        )
        assert approve.status_code == 200
        assert approve.json()["request"]["status"] == "approved"

        st2 = client.get("/api/employer/tariff", headers=_h(te)).json()
        assert st2["plan_id"] == "hire" and st2["usage"]["invites_limit"] == 30
    finally:
        get_settings.cache_clear()


def test_admin_overview_funnel_users_companies_and_flags(client):
    tc = register_and_verify(client, email="f-cand@example.com", full_name="Кандидат Воронки")
    te = register_and_verify(client, email="f-emp@example.com", role="employer", company_name="Компания Воронки")
    ta = _admin_token()

    ov = client.get("/api/admin/overview", headers=_h(ta))
    assert ov.status_code == 200
    body = ov.json()
    assert body["users_real"] >= 3
    assert body["companies_real"] >= 1
    assert "funnel" in body and body["funnel"]["totals"]["registrations"] >= 3
    assert len(body["funnel"]["by_day"]) == 14

    users = client.get("/api/admin/users?q=f-cand", headers=_h(ta)).json()["items"]
    assert len(users) == 1 and users[0]["email"] == "f-cand@example.com"
    cand_id = users[0]["id"]

    # блокировка и разблокировка пользователя
    blk = client.post("/api/admin/users/status", json={"user_id": cand_id, "is_active": False}, headers=_h(ta))
    assert blk.status_code == 200 and blk.json()["is_active"] is False
    assert client.get("/api/me", headers=_h(tc)).status_code == 401
    unblk = client.post("/api/admin/users/status", json={"user_id": cand_id, "is_active": True}, headers=_h(ta))
    assert unblk.status_code == 200 and unblk.json()["is_active"] is True

    # нельзя заблокировать самого себя
    me_admin = client.get("/api/me", headers=_h(ta)).json()
    assert client.post("/api/admin/users/status", json={"user_id": me_admin["id"], "is_active": False}, headers=_h(ta)).status_code == 409

    # компании и прямое переключение тарифа админом
    comps = client.get("/api/admin/companies?q=Воронки", headers=_h(ta)).json()["items"]
    assert len(comps) == 1
    cid = comps[0]["id"]
    set_p = client.post(
        "/api/admin/companies/tariff",
        json={"company_id": cid, "plan": "partner", "note": "Генеральный партнёр"},
        headers=_h(ta),
    )
    assert set_p.status_code == 200 and set_p.json()["plan_id"] == "partner" and set_p.json()["fsp_partner"] is True

    # переключение флага jury_mode и возврат обратно
    f0 = client.get("/api/admin/flags", headers=_h(ta)).json()["jury_mode"]
    f_off = client.post("/api/admin/flags", json={"jury_mode": False}, headers=_h(ta)).json()
    assert f_off["jury_mode"] is False
    f_on = client.post("/api/admin/flags", json={"jury_mode": True}, headers=_h(ta)).json()
    assert f_on["jury_mode"] == f0
