"""Обратный канал «Поток» → платформа: этап кандидата в ATS меняет этап приглашения и статус отклика (И10, п. 7)."""
from __future__ import annotations

from app.core.db import SessionLocal
from app.integrations.ats import stages
from app.integrations.ats.models import AtsConnection, AtsStageEvent
from app.integrations.settings import get_isettings
from tests.test_ats_providers import (_accepted, _company_of, ats_http, http, po_client)  # noqa: F401 — фикстуры
from tests.test_day2_rules import H, candidate_with_category, employer
from tests.test_integrations import VAC


def test_map_potok_stage_types():
    assert [stages.map_potok(t, True) for t in ("sourced", "applied", "screening", "custom", None)] == ["review"] * 5
    assert stages.map_potok("interview_client", True) == "interview" and stages.map_potok("interview", None) == "interview"
    assert stages.map_potok("offer", True) == "offer" and stages.map_potok("accepted", True) == "hired"
    assert stages.map_potok("offer", False) == "rejected"  # active=false — отказ на любом этапе


def _pipeline(client, te):
    return client.get("/api/employer/ats/stub/potok/pipeline", headers=H(te)).json()


def _move(client, te, join_id, stage_type=None, decline=False):
    p = next(x for x in _pipeline(client, te) if x["join_id"] == join_id)
    sid = next((s["id"] for s in p["stages"] if s["stage_type"] == stage_type), None)
    r = client.post("/api/employer/ats/stub/potok/move", json={"join_id": join_id, "stage_id": sid, "decline": decline},
                    headers=H(te))
    assert r.status_code == 200, r.text


def _sync(client, te) -> dict:
    r = client.post("/api/employer/ats/stages/sync", headers=H(te))
    assert r.status_code == 200, r.text
    return r.json()


def test_back_channel_invitation_stage_journal_and_push(client, ats_http, monkeypatch):  # noqa: F811
    pushes = []
    monkeypatch.setattr("app.integrations.push.service.send_to_user",
                        lambda db, uid, title, body, url="/", tag=None: pushes.append(title) or 0)
    tc, te, inv = _accepted(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    dl = client.get("/api/employer/ats/deliveries", headers=H(te)).json()
    assert [(d["target"], d["status"]) for d in dl] == [("potok", "ok")]
    pipe = _pipeline(client, te)
    assert len(pipe) == 1 and pipe[0]["stage_name"] == "Новые" and pipe[0]["active"]
    assert {s["stage_type"] for s in pipe[0]["stages"]} == {"sourced", "applied", "interview_client", "offer", "accepted"}
    join = pipe[0]["join_id"]

    first = _sync(client, te)  # первый опрос: этап «Новые» → «На рассмотрении», без push
    assert first["checked"] == 1 and first["changed"] == 1 and first["errors"] == 0 and first["trigger"] == "manual"
    cand = client.get("/api/candidate/invitations", headers=H(tc)).json()
    mine = next(i for i in cand if i["id"] == inv["id"])
    assert mine["status"] == "accepted" and mine["ats_stage"]["title"] == "На рассмотрении"
    assert "stage_name" not in mine["ats_stage"]  # внутреннее название этапа ATS кандидату не показываем
    assert pushes == []

    _move(client, te, join, "interview_client")  # рекрутёр в «Потоке» перевёл на интервью
    assert _sync(client, te)["changed"] == 1
    mine = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv["id"])
    assert mine["status"] == "accepted" and mine["ats_stage"]["stage"] == "interview"  # статус ТЗ сохранён
    emp = next(i for i in client.get("/api/employer/invitations", headers=H(te)).json() if i["id"] == inv["id"])
    assert emp["ats_stage"]["stage_name"] == "Интервью" and emp["ats_stage"]["provider_title"] == "Поток"
    assert pushes == ["Вас пригласили на собеседование"]
    assert _sync(client, te)["changed"] == 0  # повторный опрос без изменений — ничего не пишет

    _move(client, te, join, decline=True)
    assert _sync(client, te)["changed"] == 1
    mine = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv["id"])
    assert mine["ats_stage"]["title"] == "Отказ" and pushes[-1] == "Работодатель завершил рассмотрение"

    j = client.get("/api/employer/ats/stages", headers=H(te)).json()
    assert [(e["prev_stage"], e["stage"]) for e in j["events"]] == [
        ("interview", "rejected"), ("review", "interview"), (None, "review")]
    ev = j["events"][1]
    assert ev["stage_name"] == "Интервью" and ev["stage_type"] == "interview_client" and ev["invitation_id"] == inv["id"]
    assert ev["candidate_ref"] and "Приглашение" in ev["effect"] and ev["status"] == "ok"
    assert j["providers"][0]["linked"] == 1 and j["providers"][0]["info"]["changed"] == 1
    assert "@" not in str(j)  # журнал без ПДн


def test_back_channel_application_status_changes(client, ats_http):  # noqa: F811
    te = employer(client)
    tc = candidate_with_category(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    v = client.post("/api/employer/vacancies", json=VAC, headers=H(te)).json()
    a = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc)).json()
    client.post(f"/api/employer/applications/{a['id']}/view", headers=H(te))
    r = client.post("/api/employer/ats/push", json={"application_id": a["id"]}, headers=H(te)).json()
    assert r[0]["status"] == "ok"
    join = _pipeline(client, te)[0]["join_id"]
    _sync(client, te)
    _move(client, te, join, "offer")
    assert _sync(client, te)["changed"] == 1
    mine = client.get("/api/candidate/applications", headers=H(tc)).json()[0]
    assert mine["status"] == "accepted" and mine["ats_stage"]["title"] == "Оффер"  # просмотрен → приглашён
    assert [e["status"] for e in mine["events"]][-2:] == ["ats_stage", "accepted"]
    assert mine["events"][-1]["by"] == "ats"
    _move(client, te, join, decline=True)
    _sync(client, te)
    mine = client.get("/api/candidate/applications", headers=H(tc)).json()[0]
    assert mine["status"] == "rejected" and mine["ats_stage"]["stage"] == "rejected"
    j = client.get("/api/employer/ats/stages", headers=H(te)).json()
    assert j["events"][0]["application_id"] == a["id"] and "статус «Отказ»" in j["events"][0]["effect"]


def test_poller_claims_once_and_skips_companies_without_links(client, ats_http, monkeypatch):  # noqa: F811
    tc, te, inv = _accepted(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te2)).status_code == 200
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    monkeypatch.setattr(get_isettings(), "ats_stage_poll_s", 300)
    assert stages.sync_due() == 1  # компания без переданных кандидатов не опрашивается
    assert stages.sync_due() == 0  # интервал ещё не прошёл
    cid = _company_of("hr@corp.ru")
    with SessionLocal() as db:
        assert not stages.claim(db, cid, "potok", 300)  # второй воркер строку не возьмёт
        conn = db.get(AtsConnection, (cid, "potok"))
        assert conn.stages_sync_info["trigger"] == "poll" and conn.stages_sync_info["checked"] == 1
        assert db.query(AtsStageEvent).count() == 1
    started = []

    class FakeThread:
        def __init__(self, target, name, daemon):
            started.append((name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(stages, "_started", False)
    monkeypatch.setattr(stages.threading, "Thread", FakeThread)
    assert stages.start_poller() is True and stages.start_poller() is False  # один поток на процесс
    assert started == [("ats-stage-poller", True)]


def test_potok_client_join_state_and_fallback(http):  # noqa: F811
    http.on("GET", r"/jobs/5/ajs_joins\.json$", (200, {"objects": [{"id": 9, "job_id": 5, "applicant_id": 7,
                                                                   "stage": {"id": 51, "stage_type": "offer"},
                                                                   "active": False}]}))
    st = po_client().join_state(5, 7)
    assert st == {"id": 9, "stage_id": 51, "stage_type": "offer", "active": False, "source": "ajs_joins"}
    assert http.calls[0]["params"] == {"applicant_id": 7}
    # метод недоступен компании — этап из карточки кандидата (признака отказа там нет)
    http.on("GET", r"/jobs/5/ajs_joins\.json$", (403, {"errors": "forbidden"}))
    http.on("GET", r"/applicants/7\.json$", (200, {"id": 7, "ajs_joins": [
        {"id": 9, "job": {"id": 5, "name": "Backend", "stage_name": "Интервью"},
         "stage": {"id": 52, "name": "Интервью", "serial": 3, "stage_type": "interview_client"}}]}))
    st = po_client().join_state(5, 7)
    assert st["stage_type"] == "interview_client" and st["stage_name"] == "Интервью" and st["active"] is None
    http.on("GET", r"/jobs/5/ajs_joins\.json$", (200, {"objects": []}))
    assert po_client().join_state(5, 7) is None
    # пример ответа в спецификации — «stage_id» без объекта stage: тип этапа тогда берётся из GET /jobs/{id}.json
    http.on("GET", r"/jobs/5/ajs_joins\.json$", (200, {"objects": [{"id": 9, "job_id": 5, "applicant_id": 7,
                                                                   "stage_id": 53, "active": True}]}))
    assert po_client().join_state(5, 7) == {"id": 9, "stage_id": 53, "stage_type": None, "active": True,
                                            "source": "ajs_joins"}


def test_back_channel_errors_logged_once(client, ats_http, monkeypatch):  # noqa: F811
    tc, te, inv = _accepted(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    from app.integrations.ats.clients import AtsError
    from app.integrations.ats.providers import potok

    def boom(self, job_id, applicant_id):
        raise AtsError("«Поток»: токен недействителен (401)", 401)

    monkeypatch.setattr(potok.PotokClient, "join_state", boom)
    for _ in range(3):
        r = _sync(client, te)
        assert r["errors"] == 1 and "401" in r["error"]
    ev = client.get("/api/employer/ats/stages", headers=H(te)).json()["events"]
    assert len(ev) == 1 and ev[0]["status"] == "error"  # одна и та же ошибка не размножается
    # кнопка не чаще 12 раз в минуту
    codes = [client.post("/api/employer/ats/stages/sync", headers=H(te)).status_code for _ in range(12)]
    assert 429 in codes
    # двигать кандидата из кабинета — только в демо-«Потоке»
    with SessionLocal() as db:
        db.get(AtsConnection, (_company_of("hr@corp.ru"), "potok")).mode = "real"
        db.commit()
    r = client.post("/api/employer/ats/stub/potok/move", json={"join_id": 1, "decline": True}, headers=H(te))
    assert r.status_code == 409


def test_potok_stub_back_channel_methods_match_spec_subset(client, ats_http):  # noqa: F811
    """Заглушка «Потока» отвечает на методы обратного канала по docs/ats/potok-api-v3.subset.json (схемы ответа и
    тела), а клиент обратного канала читает её ответ так же, как ответ настоящего API."""
    import json
    from pathlib import Path

    from tests.test_ats_providers import _schema_ok, _stub_key

    spec = json.loads((Path(__file__).resolve().parents[2] / "docs" / "ats" / "potok-api-v3.subset.json")
                      .read_text())["paths"]
    tc, te, inv = _accepted(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    row = _pipeline(client, te)[0]
    auth = {"Authorization": f"Bearer ptk.{_stub_key(client, te)}"}
    base = "/api/ats-stub/potok/api/v3"

    r = ats_http.get(f"{base}/jobs/{row['job_id']}/ajs_joins.json", params={"applicant_id": row["applicant_id"]},
                     headers=auth)
    assert r.status_code == 200, r.text
    _schema_ok(r.json(), spec["/jobs/{job_id}/ajs_joins.json"]["get"]["responseBody"])
    obj = r.json()["objects"][0]
    assert obj["id"] == row["join_id"] and obj["stage"]["stage_type"] and obj["active"] is True

    url = f"{base}/jobs/{row['job_id']}/{row['applicant_id']}/decline.json"
    assert ats_http.post(url, json={"decline": {"author_id": 1}}, headers=auth).status_code == 422  # без причины
    body = {"decline": {"author_id": 1, "declination_reason_id": 12, "comment": "не подходит"}}
    _schema_ok(body, spec["/jobs/{job_id}/{applicant_id}/decline.json"]["post"]["requestBody"])
    d = ats_http.post(url, json=body, headers=auth)
    assert d.status_code == 200 and d.json() == {"result": "success"}
    _schema_ok(d.json(), spec["/jobs/{job_id}/{applicant_id}/decline.json"]["post"]["responseBody"])
    assert ats_http.get(f"{base}/jobs/{row['job_id']}/ajs_joins.json", params={"applicant_id": row["applicant_id"]},
                        headers=auth).json()["objects"][0]["active"] is False
    res = _sync(client, te)
    assert res["changed"] == 1 and res["errors"] == 0
    mine = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv["id"])
    assert mine["ats_stage"]["stage"] == "rejected" and mine["status"] == "accepted"  # статус ТЗ не трогаем
