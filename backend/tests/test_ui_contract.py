"""Контракт с интерфейсом: поля, которые читают страницы кабинетов, присутствуют в ответах API.

Сквозной путь: кандидат (опрос → тест → категория) → работодатель (компания → потребность → подборка →
зонд → приглашение) → кандидат принимает → работодатель видит контакты.
"""
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref


def keys(d: dict, *names: str):
    missing = [n for n in names if n not in d]
    assert not missing, f"нет полей {missing} в {sorted(d)}"


def test_ui_contract_end_to_end(client):
    tc = candidate_with_category(client)
    ref = my_ref(client, tc)
    me = client.get("/api/me", headers=H(tc)).json()["candidate"]
    keys(me, "public_ref", "onboarding_completed_at", "current_category_id", "visible_to_employers", "phone", "telegram")

    onb = client.get("/api/me/onboarding", headers=H(tc)).json()
    keys(onb, "answers", "options")
    keys(onb["answers"], "privacy", "salary_min_hidden")
    assert onb["options"]["privacy_fields"] and {"id", "title"} <= set(onb["options"]["privacy_fields"][0])

    cons = client.get("/api/me/consents", headers=H(tc)).json()
    assert cons and {"kind", "granted_at", "revoked_at", "version"} <= set(cons[0])
    keys(client.get("/api/legal/consents/processing").json(), "title", "text")
    keys(client.get("/api/meta").json()["operator"], "email")
    keys(client.get("/api/me/fsp", headers=H(tc)).json(), "linked", "note", "achievements", "fsp_id_claimed")
    keys(client.get("/api/me/card", headers=H(tc)).json(), "ref", "category", "test", "fsp", "stack_declared", "market_range")
    tags = client.get("/api/catalog/stack-tags").json()
    assert {"id", "title", "direction_id"} <= set(tags[0])

    te = employer(client)
    assert client.patch("/api/me/company", json={"description": "Платёжный сервис", "city": "Москва"},
                        headers=H(te)).status_code == 200
    parsed = client.post("/api/employer/needs/parse", json={"text": "Нужен middle Python-разработчик, PostgreSQL, FastAPI"},
                         headers=H(te)).json()
    keys(parsed, "direction", "grade", "stack_required", "stack_desired", "work_format", "salary_from", "salary_to", "method")
    req = {k: v for k, v in parsed.items() if k not in ("method", "llm")}
    need = client.post("/api/employer/needs", json={"text": "Нужен middle Python-разработчик, PostgreSQL, FastAPI",
                                                    "requirements": req}, headers=H(te))
    assert need.status_code == 201, need.text
    nid = need.json()["id"]
    lst = client.get("/api/employer/needs", headers=H(te)).json()
    keys(lst[0], "id", "title", "raw_text", "requirements", "versions", "created_at")
    keys(client.get(f"/api/employer/needs/{nid}", headers=H(te)).json(), "title", "raw_text", "versions")
    sel = client.get(f"/api/employer/needs/{nid}/selections/1", headers=H(te)).json()
    keys(sel, "version", "parent_version", "filters", "requirements", "categories", "total", "results", "created_at")
    keys(sel["categories"][0], "id", "title", "count", "relation", "market_range")
    keys(sel["results"][0], "ref", "score", "reasons", "card")
    keys(sel["results"][0]["reasons"][0], "requirement", "level", "text")

    cats = client.get("/api/employer/categories", headers=H(te)).json()
    keys(cats[0], "id", "title", "direction", "count")
    found = client.get("/api/employer/candidates?direction=backend&stack=python&stack_level=t1", headers=H(te)).json()
    assert found["total"] == 1 and found["items"][0]["ref"] == ref

    pr = client.post("/api/employer/probes", json={
        "candidate_refs": [ref], "need_id": nid, "title": "Медленный запрос", "answer_mode": "any", "time_limit_min": 30,
        "task_text": "Запрос с JOIN по двум таблицам выполняется 8 секунд. Опишите план.",
        "salary_from": 200000, "salary_to": 280000}, headers=H(te)).json()
    keys(pr, "created", "skipped")
    pid = pr["created"][0]["id"]
    cp = client.get("/api/candidate/probes", headers=H(tc)).json()
    keys(cp[0], "id", "title", "company", "salary_from", "salary_to", "deadline_at", "status")
    one = client.get(f"/api/candidate/probes/{pid}", headers=H(tc)).json()
    keys(one, "task_text", "answer_mode", "time_limit_min", "events", "answer", "review")
    client.post(f"/api/candidate/probes/{pid}/answer", json={"mode": "approach", "text": "EXPLAIN ANALYZE, индексы."},
                headers=H(tc))
    ep = client.get("/api/employer/probes", headers=H(te)).json()
    keys(ep[0], "candidate_ref", "candidate_category", "answer", "events", "status")
    rv = client.post(f"/api/employer/probes/{pid}/review", json={"verdict": "strong"}, headers=H(te)).json()
    keys(rv["review"], "verdict_title")

    det = client.get(f"/api/employer/candidates/{ref}?need_id={nid}", headers=H(te)).json()
    keys(det, "match", "can_invite", "invite_available_at", "invitation_cooldown_days", "my_invitations", "my_probes",
         "contacts", "market_range")
    assert det["contacts"] is None
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref, "need_id": nid, "probe_id": pid},
                      headers=H(te))
    assert inv.status_code == 201, inv.text
    iid = inv.json()["id"]
    ci = client.get("/api/candidate/invitations", headers=H(tc)).json()
    keys(ci[0], "id", "position_title", "company", "salary_from", "salary_to", "created_at", "status", "below_my_minimum")
    full = client.get(f"/api/candidate/invitations/{iid}", headers=H(tc)).json()
    keys(full, "offer_description", "contact_method", "evidence", "history")
    assert full["evidence"] and all("level" in e for e in full["evidence"])
    assert client.post(f"/api/candidate/invitations/{iid}/accept", json={}, headers=H(tc)).json()["status"] == "accepted"
    ei = client.get("/api/employer/invitations", headers=H(te)).json()
    keys(ei[0], "candidate_ref", "candidate_category", "contacts", "history", "decline_reason")
    assert ei[0]["contacts"]["phone"] == "+7 900 111-22-33"
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()["contacts"]["full_name"] == "Иван Петров"

    # Чужой кандидат не видит приглашение
    other = register_and_verify(client, email="other@example.com")
    assert client.get(f"/api/candidate/invitations/{iid}", headers=H(other)).status_code == 404
