"""Я17 п. 2: SUS при n < 5 не выдаётся за результат — «пока недостаточно ответов (n = N)» с датой; ответы
демо-учёток (автотесты, модельные персоны) подписаны «модель, не люди»."""
from __future__ import annotations

from sqlalchemy import update

from app.core.db import SessionLocal
from app.integrations.sus.models import SusResponse
from app.modules.study import stats
from app.modules.validation import criteria as C
from tests.conftest import register_and_verify

H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731


def _answer(client, i: int, answers=(4, 2) * 5):
    t = register_and_verify(client, f"sus-honest{i}@example.com")
    assert client.post("/api/sus", json={"answers": list(answers), "context": "e2e"}, headers=H(t)).status_code == 201


def _sus_proof(client) -> dict:
    return client.get("/api/validation/criteria").json()["criteria"][2]["items"][0]["proof"]


def test_threshold_is_five():
    assert stats.SUS_MIN_N == 5


def test_summary_marks_small_n_and_criteria_shows_no_number(client):
    _answer(client, 0)
    s = client.get("/api/sus/summary").json()
    assert s["n"] == 1 and s["min_n"] == 5 and s["enough"] is False
    assert s["label"] == "пока недостаточно ответов (n = 1)" and s["updated_at"]
    assert s["demo_n"] == 0 and s["demo_note"] is None
    p = _sus_proof(client)
    assert p["kind"] == "link" and p["missing"] and "value" not in p and "ci" not in p
    assert p["label"].startswith("Анкета SUS: пока недостаточно ответов (n = 1, на ") and "балл не показываем" in p["label"]
    assert C._ru_date(s["updated_at"]) in p["label"]
    for i in range(1, 4):
        _answer(client, i)
    p = _sus_proof(client)
    assert p["kind"] == "link" and "(n = 4, на " in p["label"]


def test_five_answers_give_a_number(client):
    for i in range(5):
        _answer(client, i)
    s = client.get("/api/sus/summary").json()
    assert s["n"] == 5 and s["enough"] is True and s["label"] is None and s["mean"] == 75.0
    p = _sus_proof(client)
    assert p["kind"] == "metric" and p["value"] == 75.0 and p["signature"]["n"] == 5
    assert "модель, не люди" not in p["note"]  # демо-ответов нет — и подписи нет


def test_demo_answers_are_labelled_model_not_people(client):
    for i in range(5):
        _answer(client, i)
    with SessionLocal() as db:  # два ответа — с демо-учёток (автотесты, модельные персоны жюри)
        ids = [r.id for r in db.query(SusResponse).order_by(SusResponse.id).limit(2)]
        db.execute(update(SusResponse).where(SusResponse.id.in_(ids)).values(is_demo=True))
        db.commit()
    s = client.get("/api/sus/summary").json()
    assert s["demo_n"] == 2 and "модель, не люди" in s["demo_note"]
    p = _sus_proof(client)
    assert p["kind"] == "metric" and "их ответов 2" in p["note"] and "модель, не люди" in p["note"]
    # без демо-учёток — только люди: 3 < 5, числа снова нет
    s = client.get("/api/sus/summary", params={"include_demo": False}).json()
    assert s["n"] == 3 and s["enough"] is False and s["demo_n"] == 0


def test_ru_date_moscow():
    assert C._ru_date("2026-10-05T22:30:00+00:00") == "06.10.2026"
    assert C._ru_date("2026-10-05T14:07:45.917656") == "05.10.2026"
    assert C._ru_date(None) is None and C._ru_date("не дата") is None
