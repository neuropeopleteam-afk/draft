"""Н8 «Найм после контактов»: собеседование (слоты, выбор, другое время, «прошло», напоминание), оффер (вилка,
встречное, ответ, срок), исход найма (вышел / отказ / не прошёл), этапы в ATS и обратно, права (чужое — 404),
миграция hr01."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import update

from app.core.db import SessionLocal
from app.modules.hiring.models import HiringInterview, HiringOffer
from tests.test_ats_providers import ats_http  # noqa: F401 — фикстура
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref

LINK = "https://meet.example.com/abc-defg"


def E(inv: str) -> str:
    return f"/api/employer/invitations/{inv}"


def C(inv: str) -> str:
    return f"/api/candidate/invitations/{inv}"


def _case(client, accept: bool = True, cand="cand@example.com", emp="hr@corp.ru", company="ООО Ромашка"):
    tc, te = candidate_with_category(client, email=cand), employer(client, email=emp, company=company)
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)}, headers=H(te))
    assert r.status_code == 201, r.text
    inv = r.json()["id"]
    if accept:
        assert client.post(f"{C(inv)}/accept", headers=H(tc)).status_code < 300
    return tc, te, inv


def _slots(n: int = 3, days: int = 2, place: str | None = LINK, fmt: str = "video") -> list[dict]:
    base = (datetime.now(UTC) + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    return [{"starts_at": (base + timedelta(hours=2 * k)).isoformat(), "duration_min": 60, "format": fmt,
             "place": place} for k in range(n)]


def _propose(client, te, inv, slots=None, **kw):
    return client.post(f"{E(inv)}/interviews", json={"slots": _slots() if slots is None else slots, **kw}, headers=H(te))


def _scheduled(client, tc, te, inv) -> dict:
    iv = _propose(client, te, inv).json()["interview"]
    r = client.post(f"{C(inv)}/interviews/{iv['id']}/choose", json={"slot_id": iv["slots"][0]["id"]}, headers=H(tc))
    assert r.status_code == 200, r.text
    return r.json()["interview"]


def _to_past(iid: str, hours: int = 1) -> None:
    import uuid

    with SessionLocal() as db:
        db.execute(update(HiringInterview).where(HiringInterview.id == uuid.UUID(iid))
                   .values(starts_at=datetime.now(UTC) - timedelta(hours=hours)))
        db.commit()


def _offer(client, te, inv, salary=300000, **kw):
    body = {"salary": salary, "start_date": (date.today() + timedelta(days=14)).isoformat(), **kw}
    return client.post(f"{E(inv)}/offer", json=body, headers=H(te))


def _history(client, t, inv, side="candidate") -> list[str]:
    rows = client.get(f"/api/{side}/invitations", headers=H(t)).json()
    return [e["status"] for e in next(i for i in rows if i["id"] == inv)["history"]]


# ------------------------------------------------------------------ собеседование

def test_interview_slots_choose_reschedule_done(client):
    tc, te, inv = _case(client, accept=False)
    r = _propose(client, te, inv)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hiring_not_accepted"
    assert client.post(f"{C(inv)}/accept", headers=H(tc)).status_code < 300

    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    assert st["stage"] == "contact" and st["can"]["propose"] and len(st["presets"]["slots"]) == 3
    assert all(datetime.fromisoformat(s["starts_at"]) > datetime.now(UTC) for s in st["presets"]["slots"])
    assert all(datetime.fromisoformat(s["starts_at"]).weekday() < 5 for s in st["presets"]["slots"])
    assert st["presets"]["slots"][0]["place"] == ""  # ссылку на встречу подставляем только в демо-компаниях

    assert _propose(client, te, inv, slots=[]).status_code == 422
    assert _propose(client, te, inv, slots=_slots(4)).status_code == 422
    past = _slots(1, days=-1)
    assert _propose(client, te, inv, slots=past).json()["detail"]["code"] == "slot_past"
    assert _propose(client, te, inv, slots=_slots(1, days=90)).json()["detail"]["code"] == "slot_far"
    assert _propose(client, te, inv, slots=_slots(1, place=None)).json()["detail"]["code"] == "slot_link"
    assert _propose(client, te, inv, slots=_slots(1, place="meet.example")).json()["detail"]["code"] == "slot_link"
    assert _propose(client, te, inv, slots=_slots(1, place=None, fmt="office")).json()["detail"]["code"] == "slot_address"
    assert _propose(client, te, inv, slots=_slots(1, place=None, fmt="phone")).status_code == 201  # телефон — без адреса
    dup = _slots(1) * 2
    assert _propose(client, te, inv, slots=dup).json()["detail"]["code"] == "slots_duplicate"

    r = _propose(client, te, inv, title="Техническое собеседование", note="Будет тимлид")
    assert r.status_code == 201, r.text
    iv = r.json()["interview"]
    assert iv["status"] == "proposed" and len(iv["slots"]) == 3 and iv["title"] == "Техническое собеседование"
    assert len(r.json()["interviews"]) == 1  # повторное предложение заменяет слоты, а не плодит собеседования

    cs = client.get(f"{C(inv)}/hiring", headers=H(tc)).json()
    assert cs["stage"] == "slots" and cs["can"]["choose"] and "presets" not in cs
    assert client.get("/api/hiring/todo", headers=H(tc)).json()["total"] == 1
    row = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv)
    assert row["hiring"]["stage"] == "slots" and row["hiring"]["todo"] is True

    url = f"{C(inv)}/interviews/{iv['id']}"
    assert client.post(f"{url}/choose", json={"slot_id": "nope"}, headers=H(tc)).status_code == 422
    assert client.post(f"{url}/reschedule", json={"note": "  "}, headers=H(tc)).status_code == 422
    r = client.post(f"{url}/reschedule", json={"note": "После 18:00 в будни"}, headers=H(tc))
    assert r.status_code == 200 and r.json()["interview"]["status"] == "reschedule"
    assert r.json()["interview"]["reschedules_left"] == 2
    todo = client.get("/api/hiring/todo", headers=H(te)).json()
    assert todo["total"] == 1 and todo["items"][0]["kind"] == "reschedule"
    assert client.post(f"{url}/choose", json={"slot_id": iv["slots"][0]["id"]}, headers=H(tc)).status_code == 409

    iv = _propose(client, te, inv, slots=_slots(2, days=3)).json()["interview"]
    assert iv["status"] == "proposed" and iv["candidate_note"] == "После 18:00 в будни"
    r = client.post(f"{url}/choose", json={"slot_id": iv["slots"][1]["id"]}, headers=H(tc))
    assert r.status_code == 200
    got = r.json()["interview"]
    assert got["status"] == "scheduled" and got["starts_at"] == iv["slots"][1]["starts_at"] and got["place"] == LINK
    assert "МСК" in got["starts_text"] and r.json()["stage"] == "interview"

    done = f"{E(inv)}/interviews/{iv['id']}/done"
    r = client.post(done, json={}, headers=H(te))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "interview_not_started"  # до начала — нельзя
    _to_past(iv["id"])
    assert client.get("/api/hiring/todo", headers=H(te)).json()["items"][0]["kind"] == "mark_done"
    r = client.post(done, json={"note": "Сильный кандидат"}, headers=H(te))
    assert r.status_code == 200 and r.json()["stage"] == "interview_done" and r.json()["interview"] is None
    assert client.post(done, json={}, headers=H(te)).status_code == 409
    hist = _history(client, tc, inv)
    assert hist[-5:] == ["interview_proposed", "interview_reschedule", "interview_proposed", "interview_scheduled",
                         "interview_done"]
    assert _history(client, te, inv, "employer")[-1] == "interview_done"  # история видна обеим сторонам


def test_reschedule_limit_and_cancel(client):
    tc, te, inv = _case(client)
    for _ in range(3):
        iv = _propose(client, te, inv).json()["interview"]
        assert client.post(f"{C(inv)}/interviews/{iv['id']}/reschedule", json={"note": "Другое время"},
                           headers=H(tc)).status_code == 200
    iv = _propose(client, te, inv).json()["interview"]
    r = client.post(f"{C(inv)}/interviews/{iv['id']}/reschedule", json={"note": "Ещё раз"}, headers=H(tc))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reschedule_limit"
    assert client.get(f"{C(inv)}/hiring", headers=H(tc)).json()["can"]["reschedule"] is False
    r = client.post(f"{E(inv)}/interviews/{iv['id']}/cancel", json={"note": "Вакансия на паузе"}, headers=H(te))
    assert r.status_code == 200 and r.json()["interview"] is None and r.json()["interviews"][0]["status"] == "cancelled"
    assert client.post(f"{E(inv)}/interviews/{iv['id']}/cancel", json={}, headers=H(te)).status_code == 409
    iv2 = _propose(client, te, inv).json()["interview"]  # после отмены — новое собеседование, второй раунд
    assert iv2["id"] != iv["id"] and iv2["round"] == 2 and iv2["title"] == "Собеседование, этап 2"


def test_choose_past_slot_rejected(client):
    tc, te, inv = _case(client)
    iv = _propose(client, te, inv).json()["interview"]
    import uuid

    with SessionLocal() as db:
        row = db.get(HiringInterview, uuid.UUID(iv["id"]))
        row.slots = [{**s, "starts_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()} for s in row.slots]
        db.commit()
    r = client.post(f"{C(inv)}/interviews/{iv['id']}/choose", json={"slot_id": iv["slots"][0]["id"]}, headers=H(tc))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "slot_past"


def test_interview_reminder_once(client, monkeypatch):
    from app.modules.hiring import reminders

    sent = []
    monkeypatch.setattr(reminders, "send_to_user", lambda db, uid, title, body, url="/", tag=None:
                        sent.append((title, url)) or 1)
    tc, te, inv = _case(client)
    iv = _scheduled(client, tc, te, inv)
    with SessionLocal() as db:
        assert reminders.remind_due(db) == 0  # через двое суток — рано
    _to_past(iv["id"], hours=-3)  # начало через 3 часа
    assert client.get("/api/hiring/todo", headers=H(tc)).json()["items"][0]["kind"] == "interview_soon"
    with SessionLocal() as db:
        assert reminders.remind_due(db) == 1
        assert reminders.remind_due(db) == 0  # один раз
    assert sent == [("Скоро собеседование", "/candidate/invitations"), ("Скоро собеседование", "/employer/invitations")]


def test_demo_company_marks_done_before_start(client):
    from app.modules.profiles.models import Company

    tc, te, inv = _case(client)
    with SessionLocal() as db:
        db.execute(update(Company).values(is_demo=True))
        db.commit()
    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    assert st["rules"]["demo_done_anytime"] and st["presets"]["slots"][0]["place"].startswith("https://")
    iv = _scheduled(client, tc, te, inv)
    assert client.post(f"{E(inv)}/interviews/{iv['id']}/done", json={}, headers=H(te)).status_code == 200


# ------------------------------------------------------------------ оффер

def test_offer_range_counter_and_accept(client):
    tc, te, inv = _case(client)
    assert _offer(client, te, inv, salary=219000).json()["detail"]["code"] == "offer_below_range"
    assert _offer(client, te, inv, salary=950000).json()["detail"]["code"] == "offer_too_high"
    assert _offer(client, te, inv, start_date="2020-01-01").json()["detail"]["code"] == "offer_start_date"
    far = (date.today() + timedelta(days=45)).isoformat()
    assert _offer(client, te, inv, respond_until=far).json()["detail"]["code"] == "offer_respond_until"
    # в другом основании НДФЛ: 200 000 на руки ≈ 229 885 до вычета — не ниже «от» 220 000
    r = _offer(client, te, inv, salary=200000, salary_basis="net")
    assert r.status_code == 201, r.text
    assert client.post(f"{E(inv)}/offer/withdraw", headers=H(te)).status_code == 200
    r = _offer(client, te, inv, salary=320000, comment="Выше вилки за опыт в платежах")  # выше «до» — можно
    assert r.status_code == 201 and r.json()["stage"] == "offer"
    o = r.json()["offer"]
    assert o["status"] == "sent" and o["salary"] == 320000 and o["salary_basis"] == "gross" and o["counters_left"] == 2
    assert _offer(client, te, inv).json()["detail"]["code"] == "offer_open"
    assert client.get("/api/hiring/todo", headers=H(tc)).json()["items"][0]["kind"] == "answer_offer"

    cu = f"{C(inv)}/offer/counter"
    assert client.post(cu, json={"salary": 320000}, headers=H(tc)).json()["detail"]["code"] == "counter_not_higher"
    assert client.post(cu, json={"salary": 490000}, headers=H(tc)).json()["detail"]["code"] == "counter_too_far"
    r = client.post(cu, json={"salary": 350000, "comment": "Есть оффер на 350"}, headers=H(tc))
    assert r.status_code == 201 and r.json()["offer"]["counter"]["salary"] == 350000
    assert client.post(cu, json={"salary": 360000}, headers=H(tc)).json()["detail"]["code"] == "counter_pending"
    assert client.get("/api/hiring/todo", headers=H(te)).json()["items"][0]["kind"] == "counter"
    r = client.post(f"{E(inv)}/offer/counter/decline", json={"note": "Пока 320"}, headers=H(te))
    assert r.status_code == 200 and r.json()["offer"]["status"] == "sent" and r.json()["offer"]["salary"] == 320000
    assert client.post(f"{E(inv)}/offer/counter/decline", json={}, headers=H(te)).status_code == 409
    assert client.post(cu, json={"salary": 340000}, headers=H(tc)).status_code == 201
    r = client.post(f"{E(inv)}/offer/counter/accept", json={}, headers=H(te))
    assert r.status_code == 200
    o = r.json()["offer"]
    assert o["status"] == "accepted" and o["salary"] == 340000 and r.json()["stage"] == "offer_accepted"
    assert [c["status"] for c in o["counters"]] == ["declined", "accepted"]
    assert client.post(f"{C(inv)}/offer/accept", headers=H(tc)).json()["detail"]["code"] == "offer_not_open"
    assert _offer(client, te, inv).json()["detail"]["code"] == "offer_accepted"
    assert _history(client, tc, inv)[-3:] == ["offer_counter", "offer_counter_accepted", "offer_accepted"]


def test_counter_limit_and_candidate_accept(client):
    tc, te, inv = _case(client)
    assert _offer(client, te, inv, salary=300000).status_code == 201
    cu = f"{C(inv)}/offer/counter"
    for s in (330000, 320000):
        assert client.post(cu, json={"salary": s}, headers=H(tc)).status_code == 201
        assert client.post(f"{E(inv)}/offer/counter/decline", json={}, headers=H(te)).status_code == 200
    assert client.post(cu, json={"salary": 310000}, headers=H(tc)).json()["detail"]["code"] == "counter_limit"
    r = client.post(f"{C(inv)}/offer/accept", headers=H(tc))
    assert r.status_code == 200 and r.json()["offer"]["status"] == "accepted" and r.json()["offer"]["salary"] == 300000
    assert client.get("/api/hiring/todo", headers=H(tc)).json()["total"] == 0


def test_offer_decline_closes_case_and_expiry(client):
    tc, te, inv = _case(client)
    assert _offer(client, te, inv).status_code == 201
    r = client.post(f"{C(inv)}/offer/decline", json={"reason": "Выбрал другую компанию"}, headers=H(tc))
    assert r.status_code == 200 and r.json()["stage"] == "declined" and r.json()["outcome"]["title"] == "Отказ кандидата"
    assert r.json()["open"] is False
    r = _propose(client, te, inv)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hiring_closed"
    row = next(i for i in client.get("/api/employer/invitations", headers=H(te)).json() if i["id"] == inv)
    assert row["hiring"]["stage"] == "declined"

    tc2, te2, inv2 = _case(client, cand="c2@example.com", emp="hr2@corp.ru", company="ООО Лютик")
    assert _offer(client, te2, inv2).status_code == 201
    with SessionLocal() as db:
        db.execute(update(HiringOffer).values(respond_until=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
    st = client.get(f"{C(inv2)}/hiring", headers=H(tc2)).json()
    assert st["offer"]["status"] == "expired" and st["stage"] == "contact" and not st["can"]["answer_offer"]
    assert client.post(f"{C(inv2)}/offer/accept", headers=H(tc2)).status_code == 409
    assert "offer_expired" in _history(client, tc2, inv2)
    assert _offer(client, te2, inv2).status_code == 201  # после истечения — новый оффер


# ------------------------------------------------------------------ исход найма

def test_outcome_rules(client):
    tc, te, inv = _case(client)
    out = f"{E(inv)}/outcome"
    r = client.post(out, json={"outcome": "hired"}, headers=H(te))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hire_needs_offer"
    assert client.post(out, json={"outcome": "maybe"}, headers=H(te)).status_code == 422
    _scheduled(client, tc, te, inv)
    r = client.post(out, json={"outcome": "rejected", "note": "Не хватило опыта с Kafka"}, headers=H(te))
    assert r.status_code == 200 and r.json()["stage"] == "rejected" and r.json()["interview"] is None
    assert r.json()["interviews"][0]["status"] == "cancelled" and r.json()["can"]["propose"] is False
    assert client.post(out, json={"outcome": "declined"}, headers=H(te)).json()["detail"]["code"] == "hiring_closed"
    cs = client.get(f"{C(inv)}/hiring", headers=H(tc)).json()
    assert cs["outcome"]["title"] == "Не прошёл" and cs["outcome"]["note"] == "Не хватило опыта с Kafka"
    assert _history(client, tc, inv)[-1] == "hire_rejected"


def test_hired_after_accepted_offer(client):
    tc, te, inv = _case(client)
    assert _offer(client, te, inv).status_code == 201
    client.post(f"{C(inv)}/offer/accept", headers=H(tc))
    r = client.post(f"{E(inv)}/outcome", json={"outcome": "hired"}, headers=H(te))
    assert r.status_code == 200 and r.json()["outcome"]["title"] == "Вышел на работу"
    assert r.json()["outcome"]["start_date"] == (date.today() + timedelta(days=14)).isoformat()  # из оффера
    row = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv)
    assert row["hiring"]["stage"] == "hired" and row["status"] == "accepted"  # статус приглашения по ТЗ не меняется


def test_revoked_contacts_pause_hiring(client):
    tc, te, inv = _case(client)
    assert client.post(f"{C(inv)}/contacts/revoke", headers=H(tc)).status_code == 200
    r = _propose(client, te, inv)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hiring_contacts_revoked"
    assert client.get(f"{E(inv)}/hiring", headers=H(te)).json()["paused"] is True
    assert client.post(f"{C(inv)}/contacts/restore", headers=H(tc)).status_code == 200
    assert _propose(client, te, inv).status_code == 201


# ------------------------------------------------------------------ права

def test_foreign_invitation_is_404_and_roles(client):
    tc, te, inv = _case(client)
    iv = _propose(client, te, inv).json()["interview"]
    tc2 = candidate_with_category(client, email="other@example.com")
    te2 = employer(client, email="hr@other.ru", company="ООО Чужая")
    for m, url, body in [("get", f"{E(inv)}/hiring", None), ("post", f"{E(inv)}/interviews", {"slots": _slots()}),
                         ("post", f"{E(inv)}/interviews/{iv['id']}/done", {}),
                         ("post", f"{E(inv)}/offer", {"salary": 300000, "start_date": "2026-12-01"}),
                         ("post", f"{E(inv)}/outcome", {"outcome": "rejected"})]:
        r = client.request(m.upper(), url, json=body, headers=H(te2))
        assert r.status_code == 404, (url, r.status_code)
    for m, url, body in [("get", f"{C(inv)}/hiring", None),
                         ("post", f"{C(inv)}/interviews/{iv['id']}/choose", {"slot_id": iv["slots"][0]["id"]}),
                         ("post", f"{C(inv)}/offer/accept", None)]:
        r = client.request(m.upper(), url, json=body, headers=H(tc2))
        assert r.status_code == 404, (url, r.status_code)
    # собеседование другого приглашения по своему приглашению — тоже 404
    tc3, te3, inv3 = _case(client, cand="c3@example.com", emp="hr3@corp.ru", company="ООО Третья")
    r = client.post(f"{C(inv3)}/interviews/{iv['id']}/choose", json={"slot_id": iv["slots"][0]["id"]}, headers=H(tc3))
    assert r.status_code == 404
    assert client.get(f"{E(inv)}/hiring", headers=H(tc)).status_code == 403
    assert client.get(f"{C(inv)}/hiring", headers=H(te)).status_code == 403
    assert client.get(f"{C(inv)}/hiring").status_code == 401
    assert client.get("/api/hiring/todo").status_code == 401
    assert client.get("/api/hiring/todo", headers=H(te2)).json()["total"] == 0


# ------------------------------------------------------------------ ATS: этап туда и обратно

def _demo_potok(client, te):
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200


def test_hiring_stages_go_to_potok_and_come_back(client, ats_http, monkeypatch):  # noqa: F811
    pushes = []
    monkeypatch.setattr("app.integrations.push.service.send_to_user",
                        lambda db, uid, title, body, url="/", tag=None: pushes.append(title) or 0)
    tc, te, inv = _case(client, accept=False)
    _demo_potok(client, te)
    assert client.post(f"{C(inv)}/accept", headers=H(tc)).status_code < 300  # авто-передача в «Поток»
    _scheduled(client, tc, te, inv)
    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    assert st["ats"][0]["target"] == "potok" and st["ats"][0]["status"] == "ok", st["ats"]
    assert st["ats"][0]["stage_title"] == "Интервью"
    pipe = client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()
    assert pipe[0]["stage_name"] == "Интервью"
    row = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv)
    assert row["ats_stage"]["stage"] == "interview"  # вернулся обратным каналом — виден кандидату
    assert "Вас пригласили на собеседование" not in pushes  # push об этапе не дублирует уведомление шага найма

    assert _offer(client, te, inv).status_code == 201
    assert client.post(f"{C(inv)}/offer/accept", headers=H(tc)).status_code == 200
    r = client.post(f"{E(inv)}/outcome", json={"outcome": "hired"}, headers=H(te))
    assert r.status_code == 200
    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    assert st["ats"][0]["stage_title"] == "Вышел на работу" and st["ats"][0]["trigger"] == "hiring_hired"
    emp = next(i for i in client.get("/api/employer/invitations", headers=H(te)).json() if i["id"] == inv)
    assert emp["ats_stage"]["stage"] == "hired" and emp["ats_stage"]["stage_name"] == "Вышел на работу"
    cand = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv)
    assert cand["ats_stage"]["title"] == "Вышел на работу" and "stage_name" not in cand["ats_stage"]
    pipe = client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()
    assert pipe[0]["stage_name"] == "Вышел на работу"
    dl = client.get("/api/employer/ats/deliveries", headers=H(te)).json()
    assert [d["trigger"] for d in dl if d["trigger"].startswith("hiring_")] == [
        "hiring_hired", "hiring_offer", "hiring_interview"]
    recs = client.get("/api/employer/ats/stub/records", headers=H(te)).json()
    assert any(r["kind"] == "potok_event" and "Встречный: вышел на работу" in str(r["payload"]) for r in recs)
    j = client.get("/api/employer/ats/stages", headers=H(te)).json()
    assert [e["stage"] for e in j["events"]][:3] == ["hired", "offer", "interview"]


def test_rejected_declines_in_potok(client, ats_http):  # noqa: F811
    tc, te, inv = _case(client, accept=False)
    _demo_potok(client, te)
    client.post(f"{C(inv)}/accept", headers=H(tc))
    r = client.post(f"{E(inv)}/outcome", json={"outcome": "rejected", "note": "Мало опыта"}, headers=H(te))
    assert r.status_code == 200
    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    assert st["ats"][0]["status"] == "ok" and st["ats"][0]["stage_title"] == "Отклонён"
    pipe = client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()
    assert pipe[0]["active"] is False
    row = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv)
    assert row["ats_stage"]["stage"] == "rejected"


def test_all_demo_targets_get_hiring_stage(client, ats_http):  # noqa: F811
    tc, te, inv = _case(client, accept=False)
    assert client.post("/api/employer/ats/demo/connect-all", headers=H(te)).status_code == 200
    client.post(f"{C(inv)}/accept", headers=H(tc))
    _scheduled(client, tc, te, inv)
    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    got = {a["target"]: (a["status"], a["stage_title"]) for a in st["ats"]}
    assert got["potok"] == ("ok", "Интервью") and got["talantix"] == ("ok", "Интервью")
    assert got["huntflow"] == ("ok", "Интервью") and got["webhook"][0] == "ok", got
    recs = client.get("/api/employer/ats/stub/records", headers=H(te)).json()
    hook = next(r for r in recs if r["kind"] == "webhook" and r["payload"].get("event") == "candidate.hiring_stage")
    assert hook["signature_valid"] and hook["payload"]["stage"] == "interview" and hook["payload"]["candidate_ref"]
    assert "Иван" not in str(hook["payload"]) and "111-22-33" not in str(hook["payload"])  # без ПДн
    assert any(r["kind"] == "talantix_transfer" for r in recs)


def test_ats_failure_does_not_block_hiring(client, monkeypatch):
    from app.integrations.ats.models import AtsConnection
    from tests.test_ats_providers import _company_of

    tc, te, inv = _case(client)
    cid = _company_of("hr@corp.ru")
    with SessionLocal() as db:  # «Поток» включён, но токена нет — передача упадёт
        db.add(AtsConnection(company_id=cid, provider="potok", enabled=True, mode="real", vacancy_map={},
                             last_check_info={}))
        from app.integrations.ats.service import company_settings

        company_settings(db, cid)
        db.commit()
    iv = _scheduled(client, tc, te, inv)
    assert iv["status"] == "scheduled"
    st = client.get(f"{E(inv)}/hiring", headers=H(te)).json()
    assert st["ats"][0]["status"] == "error" and st["ats"][0]["error"]


# ------------------------------------------------------------------ миграция

def test_migration_hr01_up_and_down(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from tests.conftest import alembic_config

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "hr01")
    names = set(inspect(create_engine(url)).get_table_names())
    assert {"hiring_interviews", "hiring_offers", "hiring_outcomes"} <= names
    from alembic.script import ScriptDirectory

    command.downgrade(cfg, ScriptDirectory.from_config(cfg).get_revision("hr01").down_revision)
    assert not {"hiring_interviews", "hiring_offers", "hiring_outcomes"} & set(
        inspect(create_engine(url)).get_table_names())
