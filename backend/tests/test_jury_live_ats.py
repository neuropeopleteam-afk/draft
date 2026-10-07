"""И10 п. 8: живая демонстрация (QR) → «Принять» на телефоне гостя → передача в ATS песочницы жюри и журнал передач;
затем обратный канал: рекрутёр двигает гостя в демо-«Потоке» → этап виден в приглашении у работодателя и кандидата."""
from __future__ import annotations

from app.integrations.ats import stages
from tests.test_ats_providers import ats_http  # noqa: F401 — фикстура: запросы к заглушкам ATS идут в приложение
from tests.test_day2_rules import H
from tests.test_jury_live import _answer, _fast, _login, _room  # noqa: F401 — _fast: без пауз перед подборкой

TARGETS = {"huntflow", "talantix", "potok", "webhook"}


def _guest_invited(client, emp):
    code = _room(client, emp["access_token"])["code"]
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "backend"})
    assert r.status_code == 201, r.text
    gt, me = r.json()["token"], r.json()["guest"]
    for _ in range(3):
        me = _answer(client, code, gt, me["item"], correct=True)
    assert me["stage"] == "invited", me
    client.get(f"/api/jury/live/j/{code}/me", params={"visible": 1}, headers={"X-Guest-Token": gt})
    return code, gt, me


def _mine(rows, ref):
    return [d for d in rows if d["candidate_ref"] == ref]


def test_live_accept_delivers_to_all_sandbox_ats_and_journal(client, ats_http):  # noqa: F811
    emp = _login(client, "employer")
    te = emp["access_token"]
    prov = {p["code"]: p for p in client.get("/api/employer/ats/providers", headers=H(te)).json()}
    assert all(prov[c]["enabled"] and prov[c]["mode"] == "demo" for c in ("talantix", "potok"))
    joins_before = {p["join_id"] for p in client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()}

    code, gt, me = _guest_invited(client, emp)
    ref = me["ref"]
    # до ответа гостя в ATS ничего не уходит: передача — только после согласия кандидата
    assert _mine(client.get("/api/employer/ats/deliveries", headers=H(te)).json(), ref) == []

    r = client.post(f"/api/jury/live/j/{code}/respond", json={"accept": True}, headers={"X-Guest-Token": gt})
    assert r.status_code == 200 and r.json()["stage"] == "accepted", r.text

    dl = _mine(client.get("/api/employer/ats/deliveries", headers=H(te)).json(), ref)
    assert {d["target"] for d in dl} == TARGETS, dl
    assert all(d["status"] == "ok" and d["trigger"] == "invitation_accepted" and d["error"] is None for d in dl), dl
    inv_id = next(i["id"] for i in client.get("/api/employer/invitations", headers=H(te)).json()
                  if i["candidate_ref"] == ref)
    assert {d["invitation_id"] for d in dl} == {inv_id}
    assert {d["position_title"] for d in dl} == {me["invite"]["position_title"]}

    # в заглушках — карточка гостя; в «Потоке» он на вакансии, этап «Новые»
    rec = client.get("/api/employer/ats/stub/records", headers=H(te)).json()
    assert rec, rec
    pipe = [p for p in client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()
            if p["join_id"] not in joins_before]
    assert len(pipe) == 1 and pipe[0]["active"] and pipe[0]["stage_name"] == "Новые", pipe

    # повторный ответ — 409, журнал без дублей
    assert client.post(f"/api/jury/live/j/{code}/respond", json={"accept": True},
                       headers={"X-Guest-Token": gt}).status_code == 409
    assert len(_mine(client.get("/api/employer/ats/deliveries", headers=H(te)).json(), ref)) == len(TARGETS)

    # обратный канал: рекрутёр перевёл гостя на интервью в демо-«Потоке» → этап в приглашении работодателя
    sid = next(s["id"] for s in pipe[0]["stages"] if s["stage_type"] == "interview_client")
    assert client.post("/api/employer/ats/stub/potok/move", json={"join_id": pipe[0]["join_id"], "stage_id": sid},
                       headers=H(te)).status_code == 200
    res = client.post("/api/employer/ats/stages/sync", headers=H(te)).json()
    assert res["errors"] == 0 and res["changed"] >= 1, res
    emp_inv = next(i for i in client.get("/api/employer/invitations", headers=H(te)).json() if i["id"] == inv_id)
    assert emp_inv["status"] == "accepted" and emp_inv["ats_stage"]["stage"] == "interview"
    assert emp_inv["ats_stage"]["provider_title"] == "Поток"
    j = client.get("/api/employer/ats/stages", headers=H(te)).json()
    assert any(e["candidate_ref"] == ref and e["stage"] == "interview" for e in j["events"]), j["events"]


def test_live_decline_sends_nothing_to_ats(client, ats_http):  # noqa: F811
    emp = _login(client, "employer")
    te = emp["access_token"]
    code, gt, me = _guest_invited(client, emp)
    r = client.post(f"/api/jury/live/j/{code}/respond", json={"accept": False}, headers={"X-Guest-Token": gt})
    assert r.status_code == 200 and r.json()["stage"] == "declined"
    assert _mine(client.get("/api/employer/ats/deliveries", headers=H(te)).json(), me["ref"]) == []


def test_live_accept_ats_down_is_journaled_then_retried(client, ats_http, monkeypatch):  # noqa: F811
    """ATS недоступна (сеть) — гость всё равно принял приглашение; в журнале ошибка, «Повторить» доставляет."""
    from app.integrations.ats import clients

    ok_send = clients._send

    def down(method, url, **kw):
        raise clients.httpx.ConnectError("нет связи")

    from app.integrations.settings import get_isettings

    monkeypatch.setattr(get_isettings(), "ats_max_attempts", 1)  # без пауз между попытками
    monkeypatch.setattr(clients, "_send", down)
    emp = _login(client, "employer")
    te = emp["access_token"]
    code, gt, me = _guest_invited(client, emp)
    r = client.post(f"/api/jury/live/j/{code}/respond", json={"accept": True}, headers={"X-Guest-Token": gt})
    assert r.status_code == 200 and r.json()["stage"] == "accepted"
    dl = _mine(client.get("/api/employer/ats/deliveries", headers=H(te)).json(), me["ref"])
    assert {d["target"] for d in dl} == TARGETS and all(d["status"] == "error" and d["error"] for d in dl), dl

    monkeypatch.setattr(clients, "_send", ok_send)  # связь восстановилась — повтор из журнала
    for d in dl:
        rr = client.post(f"/api/employer/ats/deliveries/{d['id']}/retry", headers=H(te))
        assert rr.status_code == 200, rr.text
    after = _mine(client.get("/api/employer/ats/deliveries", headers=H(te)).json(), me["ref"])
    retried = [d for d in after if d["trigger"] == "retry"]
    assert {d["target"]: d["status"] for d in retried} == dict.fromkeys(TARGETS, "ok"), after
    assert len(after) == 2 * len(TARGETS)  # в журнале видна и ошибка, и успешный повтор
    # в демо-«Потоке» гость один раз — повтор не создаёт дубликат кандидата
    names = [p["applicant"] for p in client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()]
    assert len(names) == len(set(names)), names
    assert "potok" in stages.PROVIDERS_WITH_STAGES
