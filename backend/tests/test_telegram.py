"""Тесты модуля уведомлений в Telegram: привязка по одноразовому коду, доставка с кнопками и ответ на приглашение."""
from __future__ import annotations

from app.core.db import SessionLocal
from app.modules.invitations.models import Invitation
from app.modules.telegram import service as tg_svc
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, ONBOARDING


def test_telegram_link_webhook_and_invitation_buttons(client, monkeypatch):
    sent_calls: list[tuple[str, dict]] = []

    def fake_api_call(method: str, payload: dict):
        sent_calls.append((method, payload))
        return {"ok": True, "result": {"message_id": 101}}

    monkeypatch.setattr(tg_svc, "_api_call", fake_api_call)

    cand_tok = register_and_verify(client, "tg-cand@example.org")
    emp_tok = register_and_verify(client, "tg-emp@example.org", role="employer", company_name="ТехКомп")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(cand_tok)).status_code == 200
    cand_ref = client.get("/api/me/card", headers=H(cand_tok)).json()["ref"]

    # 1. Без токена на сервере статус честно показывает configured=False, но код привязки выпускается
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    r = client.get("/api/telegram/status", headers=H(cand_tok))
    assert r.status_code == 200
    assert r.json()["configured"] is False
    assert r.json()["linked"] is False

    r = client.post("/api/telegram/link", headers=H(cand_tok))
    assert r.status_code == 201
    data = r.json()
    code = data["code"]
    assert code and data["deep_link"].endswith(f"?start={code}")

    # 2. Вебхук /start <code> привязывает чат кандидата
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN_FOR_PYTEST")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "fsp_draft_test_bot")
    w = client.post("/api/telegram/webhook", json={
        "message": {
            "text": f"/start {code}",
            "chat": {"id": 777888999, "username": "ivan_dev", "first_name": "Иван"},
            "from": {"id": 777888999, "username": "ivan_dev", "first_name": "Иван"},
        }
    })
    assert w.status_code == 200 and w.json()["action"] == "linked"

    st = client.get("/api/telegram/status", headers=H(cand_tok)).json()
    assert st["configured"] is True
    assert st["linked"] is True
    assert st["tg_username"] == "ivan_dev"

    # 3. Проверочное уведомление
    t = client.post("/api/telegram/test", headers=H(cand_tok))
    assert t.status_code == 200 and t.json()["sent"] == 1

    # 4. Работодатель отправляет приглашение кандидату → в Telegram уходит сообщение с кнопками «Открыть», «Принять», «Отклонить»
    sent_calls.clear()
    inv_res = client.post("/api/employer/invitations", headers=H(emp_tok), json={
        "candidate_ref": cand_ref,
        "position_title": "Senior Python Engineer",
        "offer_description": "Разработка высоконагруженных сервисов на FastAPI и PostgreSQL.",
        "salary_from": 240_000,
        "salary_to": 320_000,
        "contact_method": "Telegram или почта",
    })
    assert inv_res.status_code == 201, inv_res.text
    inv_id = inv_res.json()["id"]

    msg_calls = [p for m, p in sent_calls if m == "sendMessage" and str(p.get("chat_id")) == "777888999"]
    assert msg_calls, "Приглашение должно быть доставлено в Telegram привязанному кандидату"
    kb_rows = msg_calls[-1]["reply_markup"]["inline_keyboard"]
    assert len(kb_rows) == 2
    assert kb_rows[1][0]["callback_data"] == f"inv_accept:{inv_id}"
    assert kb_rows[1][1]["callback_data"] == f"inv_decline:{inv_id}"

    # 5. Нажатие «Принять» прямо в Telegram переводит приглашение в статус accepted и открывает контакты
    cb = client.post("/api/telegram/webhook", json={
        "callback_query": {
            "id": "cb-1",
            "data": f"inv_accept:{inv_id}",
            "from": {"id": 777888999},
            "message": {"message_id": 101, "chat": {"id": 777888999}},
        }
    })
    assert cb.status_code == 200
    assert cb.json()["status"] == "accepted"

    with SessionLocal() as db:
        inv_obj = db.get(Invitation, inv_res.json()["id"]) if False else None
    emp_invs = client.get("/api/employer/invitations", headers=H(emp_tok)).json()
    matched = next(x for x in emp_invs if x["id"] == inv_id)
    assert matched["status"] == "accepted"
    assert matched.get("contacts") is not None

    # 6. Отвязка Telegram
    u = client.delete("/api/telegram/link", headers=H(cand_tok))
    assert u.status_code == 200 and u.json()["linked"] is False
