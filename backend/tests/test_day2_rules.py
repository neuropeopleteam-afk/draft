"""День 2: ключевые правила платформы — видимость, лимит 30 дней, правило 90 дней, обязательная вилка,
вырезание ПДн, разбор потребности без LLM, заглушка теста."""
from datetime import timedelta
import io
import uuid

import pytest

from app.core.db import SessionLocal, utcnow
from tests.conftest import register_and_verify

H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731

ONBOARDING = {
    "direction": "backend", "stack": [{"tag": "python", "level": 3}, {"tag": "postgresql", "level": 2},
                                      {"tag": "fastapi", "level": 2}],
    "experience_years": 3, "roles": ["developer"], "work_format": "remote", "city": "Казань",
    "salary_min_hidden": 250000, "privacy": {}, "consent_publication": True,
}


def correct_index(session_id: str, item_id: str) -> int:
    from app.modules.assessment.engine import StubEngine
    from app.modules.assessment.models import TestSession

    with SessionLocal() as db:
        st = db.get(TestSession, uuid.UUID(session_id)).result["state"]
    items = StubEngine()._items(st)
    pos = [i["id"] for i in items].index(item_id)
    return st["option_order"][pos].index(items[pos]["key"])


def pass_test(client, token, grade="middle", correct=True) -> dict:
    r = client.post("/api/assessment/sessions", json={"claimed_grade": grade}, headers=H(token))
    assert r.status_code == 201, r.text
    s = r.json()
    while s["item"]:
        it = s["item"]
        ans = correct_index(s["session_id"], it["item_id"]) if correct else \
            (correct_index(s["session_id"], it["item_id"]) + 1) % len(it["options"])
        r = client.post(f"/api/assessment/sessions/{s['session_id']}/answers",
                        json={"item_id": it["item_id"], "answer": ans}, headers=H(token))
        assert r.status_code == 200, r.text
        s = r.json()
    r = client.post(f"/api/assessment/sessions/{s['session_id']}/finish", headers=H(token))
    assert r.status_code == 200, r.text
    return r.json()


def candidate_with_category(client, email="cand@example.com", grade="middle", **onb) -> str:
    t = register_and_verify(client, email=email)
    r = client.put("/api/me/onboarding", json={**ONBOARDING, **onb}, headers=H(t))
    assert r.status_code == 200, r.text
    res = pass_test(client, t, grade)
    assert res["confirmed"] and res["category_id"] == f"backend.{grade}", res
    client.patch("/api/me/candidate-profile", json={"full_name": "Иван Петров", "phone": "+7 900 111-22-33"},
                 headers=H(t))
    return t


def employer(client, email="hr@corp.ru", company="ООО Ромашка") -> str:
    return register_and_verify(client, email=email, role="employer", company_name=company)


def my_ref(client, t) -> str:
    return client.get("/api/me", headers=H(t)).json()["candidate"]["public_ref"]


INVITE = {"position_title": "Python-разработчик", "offer_description": "Разработка API платёжного сервиса, команда 6 человек.",
          "salary_from": 220000, "salary_to": 300000, "contact_method": "Telegram @hr_corp"}


# ------------------------------------------------------------------ правило 90 дней

def test_grade_rules_pure():
    from app.modules.assessment.rules import apply_result, check_can_start

    now = utcnow()
    assert check_can_start(None, None, "middle", now, sandbox=False).allowed
    locked = check_can_start("middle", now + timedelta(days=10), "senior", now, sandbox=False)
    assert not locked.allowed and locked.code == "grade_locked"
    assert check_can_start("middle", now + timedelta(days=10), "senior", now, sandbox=True).allowed
    assert check_can_start("middle", now - timedelta(days=1), "senior", now, sandbox=False).allowed
    first = apply_result(None, "middle", True, now, False)
    assert first.changed and first.reason == "initial" and first.locked_until == now + timedelta(days=90)
    up = apply_result("middle", "senior", True, now, False)
    assert up.changed and up.reason == "retest_up"
    fail = apply_result("senior", "senior", False, now, False)
    assert not fail.changed and fail.new_grade == "senior"  # принудительного понижения нет
    assert apply_result("middle", "senior", True, now, True).reason == "sandbox"


def test_stub_test_assigns_category_and_90_day_lock_with_jury_bypass(client):
    t = candidate_with_category(client)
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["current"]["category_id"] == "backend.middle" and st["lock_active"] and not st["can_retest_now"]
    assert st["grade_history"][0]["reason"] == "initial"
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "senior"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "grade_locked"
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    res = pass_test(client, t, "senior")
    assert res["grade_changed"] and res["current_grade"] == "senior"
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["grade_history"][0]["reason"] == "sandbox"


def test_failed_test_does_not_downgrade(client):
    t = candidate_with_category(client)
    client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t))
    res = pass_test(client, t, "senior", correct=False)
    assert not res["confirmed"] and res["current_grade"] == "middle"


def test_onboarding_required_before_test(client):
    t = register_and_verify(client, email="new@example.com")
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "junior"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "onboarding_required"


# ------------------------------------------------------------------ видимость

def test_card_is_anonymous_and_contacts_hidden_until_accept(client):
    tc = candidate_with_category(client)
    te = employer(client)
    found = client.get("/api/employer/candidates", params={"direction": "backend"}, headers=H(te)).json()
    assert found["total"] == 1
    card = found["items"][0]
    flat = str(card)
    for secret in ("Иван", "Петров", "cand@example.com", "111-22-33", "250000"):
        assert secret not in flat
    assert card["market_range"]["from"] > 0  # работодатель видит рынок категории, не минимум кандидата
    ref = card["ref"]
    detail = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert detail["contacts"] is None and "salary_min_hidden" not in str(detail)
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te)).json()
    assert inv["contacts"] is None and inv["evidence"], inv
    # Чужая компания не видит контактов и после принятия
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    r = client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    detail = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert detail["contacts"]["email"] == "cand@example.com" and detail["contacts"]["full_name"] == "Иван Петров"
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te2)).json()["contacts"] is None
    hist = [e["status"] for e in client.get("/api/employer/invitations", headers=H(te)).json()[0]["history"]]
    assert hist == ["sent", "viewed", "accepted"]


def test_candidate_sees_only_own_invitations(client):
    tc = candidate_with_category(client)
    tc2 = candidate_with_category(client, email="other@example.com")
    te = employer(client)
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)},
                      headers=H(te)).json()
    assert client.get(f"/api/candidate/invitations/{inv['id']}", headers=H(tc2)).status_code == 404
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc2)).status_code == 404
    assert client.get("/api/candidate/invitations", headers=H(tc2)).json() == []
    assert client.get("/api/employer/invitations", headers=H(tc)).status_code == 403
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.post(f"/api/employer/invitations/{inv['id']}/withdraw", headers=H(te2)).status_code == 404


def test_revoking_publication_hides_profile(client):
    tc = candidate_with_category(client)
    te = employer(client)
    assert client.get("/api/employer/candidates", headers=H(te)).json()["total"] == 1
    assert client.delete("/api/me/consents/publication", headers=H(tc)).status_code == 200
    assert client.get("/api/employer/candidates", headers=H(te)).json()["total"] == 0


def test_privacy_hides_fields(client):
    tc = candidate_with_category(client)
    te = employer(client)
    client.put("/api/me/privacy", json={"privacy": {"show_city": False}}, headers=H(tc))
    card = client.get("/api/employer/candidates", headers=H(te)).json()["items"][0]
    assert card["city"] is None and "Казань" not in str(card)


# ------------------------------------------------------------------ вилка и лимит 30 дней

@pytest.mark.parametrize("bad", [
    {"salary_from": None, "salary_to": 300000}, {"salary_from": 200000}, {"salary_from": 300000, "salary_to": 200000},
    {"salary_from": 0, "salary_to": 100000},
])
def test_salary_range_required(client, bad):
    tc = candidate_with_category(client)
    te = employer(client)
    body = {**INVITE, "candidate_ref": my_ref(client, tc)}
    body.pop("salary_from"), body.pop("salary_to")
    body.update({k: v for k, v in bad.items() if v is not None})
    assert client.post("/api/employer/invitations", json=body, headers=H(te)).status_code == 422
    probe = {"candidate_refs": [my_ref(client, tc)], "title": "Мини-задача", "task_text": "Опишите, как ускорить медленный SQL-запрос с JOIN.",
             **{k: v for k, v in bad.items() if v is not None}}
    assert client.post("/api/employer/probes", json=probe, headers=H(te)).status_code == 422


def test_invitation_limit_30_days(client):
    from app.modules.invitations.models import Invitation

    tc = candidate_with_category(client)
    te = employer(client)
    ref = my_ref(client, tc)
    first = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te))
    assert first.status_code == 201
    client.post(f"/api/candidate/invitations/{first.json()['id']}/decline", json={}, headers=H(tc))
    second = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te))
    assert second.status_code == 409 and second.json()["detail"]["code"] == "invitation_cooldown"
    # Другая компания может пригласить
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te2)).status_code == 201
    # Через 31 день — снова можно
    with SessionLocal() as db:
        inv = db.get(Invitation, uuid.UUID(first.json()["id"]))
        inv.created_at = utcnow() - timedelta(days=31)
        db.commit()
    assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te)).status_code == 201


def test_probe_flow_creates_t1_fact(client):
    tc = candidate_with_category(client)
    te = employer(client)
    ref = my_ref(client, tc)
    r = client.post("/api/employer/probes", json={
        "candidate_refs": [ref], "title": "Оптимизация запроса", "answer_mode": "approach",
        "task_text": "Запрос с JOIN по двум таблицам работает 8 секунд. Опишите план диагностики.",
        "salary_from": 200000, "salary_to": 260000}, headers=H(te))
    assert r.status_code == 201 and len(r.json()["created"]) == 1
    pid = r.json()["created"][0]["id"]
    assert client.get(f"/api/candidate/probes/{pid}", headers=H(tc)).json()["status"] == "viewed"
    bad = client.post(f"/api/candidate/probes/{pid}/answer", json={"mode": "solution", "text": "код решения ..."},
                      headers=H(tc))
    assert bad.status_code == 422
    ok = client.post(f"/api/candidate/probes/{pid}/answer",
                     json={"mode": "approach", "text": "EXPLAIN ANALYZE, индексы по ключам JOIN, статистика."}, headers=H(tc))
    assert ok.status_code == 200
    rv = client.post(f"/api/employer/probes/{pid}/review", json={"verdict": "strong"}, headers=H(te))
    assert rv.status_code == 200 and rv.json()["status"] == "reviewed"
    card = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert card["probes"] and card["probes"][0]["level"] == "T1"


# ------------------------------------------------------------------ подборка

def test_need_selection_versions_and_explanations(client):
    candidate_with_category(client)
    te = employer(client)
    r = client.post("/api/employer/needs", json={
        "text": "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL, желательно Kafka. Удалённо, 200–280 тыс."},
        headers=H(te))
    assert r.status_code == 201, r.text
    need = r.json()
    assert need["requirements"]["direction"] == "backend" and need["requirements"]["grade"] == "middle"
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    assert v1["total"] == 1 and v1["categories"][0]["id"] == "backend.middle" and v1["categories"][0]["count"] == 1
    reasons = v1["results"][0]["reasons"]
    assert any(x["level"] == "T1" for x in reasons) and all("level" in x for x in reasons)
    v2 = client.post(f"/api/employer/needs/{need['id']}/selections",
                     json={"parent_version": 1, "filters": {"fsp_only": True}}, headers=H(te)).json()
    assert v2["version"] == 2 and v2["parent_version"] == 1 and v2["total"] == 0
    # Прежняя версия не потеряна
    assert client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()["total"] == 1
    assert [v["version"] for v in client.get(f"/api/employer/needs/{need['id']}", headers=H(te)).json()["versions"]] == [1, 2]


def test_t0_does_not_affect_score():
    """Заявленный (T0) навык не повышает скор — только подтверждённый (T1)."""
    from types import SimpleNamespace as NS

    from app.core.enums import WorkFormat
    from app.modules.matching.ranking import score_candidate
    from app.modules.profiles.facts import Bundle

    prof = NS(current_direction_id="backend", current_grade_id="middle", work_format=WorkFormat.any, privacy={},
              rating_score=0.5)
    req = {"direction": "backend", "grade": "middle", "stack_required": [{"tag": "kafka", "weight": 1.0}],
           "stack_desired": []}
    plain = Bundle(profile=prof)
    declared = Bundle(profile=prof)
    declared.t0["stack"].append(NS(key="kafka", title="Kafka", source=NS(value="self_report")))
    s1, _, _ = score_candidate(plain, req)
    s2, _, reasons = score_candidate(declared, req)
    assert s1 == s2
    assert any(r["level"] == "T0" and "Kafka" in r["requirement"] for r in reasons)


# ------------------------------------------------------------------ ПДн, разбор без LLM, резюме, PDF

def test_pii_redaction():
    from app.modules.resume.pii import redact

    text = ("Петров Иван Сергеевич\nPython-разработчик\nТел.: +7 (912) 345-67-89, ivan.petrov@mail.ru, t.me/ivan_dev\n"
            "Опыт 4 года: FastAPI, PostgreSQL, Docker.")
    r = redact(text)
    for s in ("Петров", "Иван", "345-67-89", "ivan.petrov@mail.ru", "ivan_dev"):
        assert s not in r.text, (s, r.text)
    assert "FastAPI" in r.text and r.summary["email"] == 1


def test_need_parser_without_llm(monkeypatch):
    from app.core.config import get_settings
    from app.modules.llm.client import chat_json
    from app.modules.matching.need_parser import parse_need

    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    assert chat_json("s", "u").ok is False  # LLM не настроен → запасной путь
    r = parse_need("Junior frontend: JavaScript, HTML/CSS, React. Желательно TypeScript. Гибрид, 120–160 тыс. ₽")
    assert r["method"] == "rules" and r["direction"] == "frontend" and r["grade"] == "junior"
    tags = [x["tag"] for x in r["stack_required"]]
    assert "javascript" in tags and "java" not in tags and r["stack_desired"][0]["tag"] == "typescript"
    assert (r["salary_from"], r["salary_to"], r["work_format"]) == (120000, 160000, "hybrid")
    get_settings.cache_clear()


def _pdf_bytes(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from app.modules.pdf.profile_pdf import _fonts

    font, _ = _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont(font, 11)
    y = 800
    for ln in lines:
        c.drawString(50, y, ln)
        y -= 16
    c.save()
    return buf.getvalue()


def test_resume_upload_redacts_and_extracts(client):
    t = register_and_verify(client, email="res@example.com")
    pdf = _pdf_bytes(["Смирнова Анна Викторовна", "Frontend-разработчик", "anna.smirnova@yandex.ru, +7 999 123-45-67",
                      "Опыт работы 3 года: React, TypeScript, Next.js, HTML/CSS.", "Коммуникабельна, умею работать в команде."])
    r = client.post("/api/me/resume", files={"file": ("cv.pdf", pdf, "application/pdf")}, headers=H(t))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["pii_found"]["email"] == "anna.smirnova@yandex.ru"
    assert "anna.smirnova" not in j["text_preview"] and "123-45-67" not in j["text_preview"]
    assert {"react", "typescript"} <= {s["tag"] for s in j["extracted"]["stack"]} and j["evidence_level"] == "T0"
    assert client.post("/api/me/resume", files={"file": ("x.pdf", b"hello", "application/pdf")},
                       headers=H(t)).status_code == 415
    assert client.post(f"/api/me/resume/{j['id']}/apply", json={}, headers=H(t)).status_code == 200


def test_profile_pdf(client):
    t = candidate_with_category(client)
    r = client.get("/api/me/profile.pdf", headers=H(t))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")


def test_meta_and_selfhosted_docs(client):
    m = client.get("/api/meta").json()
    assert m["product_name"] and m["operator"]["inn"] == "<реквизит>"
    html = client.get("/api/docs").text
    assert "/api/static/apidocs/swagger-ui-bundle.js" in html and "cdn" not in html.lower()
    assert client.get("/api/static/apidocs/swagger-ui-bundle.js").status_code == 200
    assert "redoc.standalone.js" in client.get("/api/redoc").text
