"""Камера во время теста по согласию (И16, app/modules/proctor): агрегация событий в достоверность, подключение к
общей достоверности (integrity.add_reasons), согласие и права, режимы камеры, приём событий, итог у работодателя,
флаг PROCTOR_CAMERA_ENABLED, агрегат ФСП и демо жюри."""
from __future__ import annotations

import json
import uuid

import pytest

from app.core.db import SessionLocal
from app.modules.assessment import integrity
from app.modules.proctor import rules
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, ONBOARDING

ITEMS = [{"position": p, "token": f"t{p}", "time_s": 60.0, "canary": p in (2, 6)} for p in range(1, 11)]
WIN = [{"from": 1, "to": None, "mid": False}]
OBS = {str(p): {"ms": 60_000, "frames": 85, "face": 80} for p in range(1, 11)}


def ev(pos: int, kind: str, ms: int, faces: int | None = None) -> dict:
    return {"position": pos, "kind": kind, "duration_ms": ms, "faces": faces}


# ------------------------------------------------------------------ агрегация (чистые правила)

def test_no_camera_is_neutral():
    for mode in (None, "declined", "unsupported", "denied"):
        s = rules.aggregate(mode, ITEMS, [], {}, [], None)
        assert s["camera"] is False and s["points"] == 0 and s["reasons"] == [] and s["title"] == "Тест без камеры"
        assert s["remarks"] == [] and s["notes"], mode
    v = rules.employer_view(s)
    assert v == {"mode": "off", "title": "Тест без камеры", "remarks": [], "notes": []}
    # режим камеры без единого окна наблюдения (запись есть, камера так и не включилась) — тоже нейтрально
    assert rules.aggregate("camera", ITEMS, [], {}, [], None)["camera"] is False


def test_camera_without_remarks():
    s = rules.aggregate("camera", ITEMS, [], OBS, WIN)
    assert s["camera"] and s["points"] == 0 and s["remarks"] == []
    assert s["title"] == "Камера: включена, замечаний нет"
    assert s["totals"]["items_watched"] == 10 and s["totals"]["observed_s"] == 600.0
    assert rules.employer_view(s)["mode"] == "on"


def test_short_intervals_ignored():
    evs = [ev(1, "no_face", 2900), ev(2, "multi_face", 1900, 2), ev(3, "blocked", 2999), ev(4, "camera_off", 1000)]
    s = rules.aggregate("camera", ITEMS, evs, OBS, WIN)
    assert s["points"] == 0 and s["remarks"] == []


def test_no_face_thresholds_and_text():
    one = rules.aggregate("camera", ITEMS, [ev(3, "no_face", 15_000)], OBS, WIN)
    assert one["points"] == 0  # 15 с на одном задании — не замечание
    pts1 = rules.aggregate("camera", ITEMS, [ev(3, "no_face", 25_000)], OBS, WIN)
    assert pts1["points"] == 1 and pts1["remarks"] == ["нет лица в кадре 25\u00a0с на 1 задании"]
    two = rules.aggregate("camera", ITEMS, [ev(3, "no_face", 5000), ev(4, "no_face", 5000)], OBS, WIN)
    assert two["points"] == 1 and "на 2 заданиях" in two["remarks"][0]
    long = rules.aggregate("camera", ITEMS, [ev(1, "no_face", 100_000), ev(3, "no_face", 30_000), ev(5, "no_face", 20_000)],
                           OBS, WIN)
    assert long["points"] == 2 and long["remarks"] == ["нет лица в кадре 2,5\u00a0мин на 3 заданиях"]
    assert long["reasons"][0] == (2, "Камера: нет лица в кадре 2,5\u00a0мин на 3 заданиях")
    five = rules.aggregate("camera", ITEMS, [ev(p, "no_face", 4000) for p in range(1, 6)], OBS, WIN)
    assert five["points"] == 2
    # лицо почти не определялось всё время — подсказка про камеру мимо / мало света, а не обвинение
    mostly = rules.aggregate("camera", ITEMS, [ev(p, "no_face", 55_000) for p in range(1, 11)], OBS, WIN)
    assert mostly["points"] == 2 and "камера направлена мимо или мало света" in mostly["remarks"][0]


def test_multi_face_thresholds():
    one = rules.aggregate("camera", ITEMS, [ev(2, "multi_face", 4000, 2)], OBS, WIN)
    assert one["points"] == 1 and one["remarks"] == ["в кадре несколько лиц на 1 задании (4\u00a0с)"]
    assert one["per_item"][1]["faces_max"] == 2
    two = rules.aggregate("camera", ITEMS, [ev(2, "multi_face", 3000, 3), ev(7, "multi_face", 3000, 2)], OBS, WIN)
    assert two["points"] == 2
    long = rules.aggregate("camera", ITEMS, [ev(2, "multi_face", 31_000, 2)], OBS, WIN)
    assert long["points"] == 2


def test_off_thresholds_and_uncovered_items():
    s = rules.aggregate("camera", ITEMS, [ev(1, "blocked", 31_000)], OBS, WIN)
    assert s["points"] == 1 and s["remarks"][0].startswith("камера закрыта или не передавала изображение 31\u00a0с")
    s = rules.aggregate("camera", ITEMS, [ev(1, "blocked", 20_000), ev(2, "camera_off", 20_000), ev(3, "blocked", 20_000)],
                        OBS, WIN)
    assert s["points"] == 2 and "на 3 заданиях" in s["remarks"][0]
    # режим камеры включён, а три задания камера не наблюдала (перезагрузка, сбой, обход) — считается как «камера
    # не передавала изображение»; задание короче 15 с и задание без времени (не отвечено) не проверяются
    obs = {k: v for k, v in OBS.items() if k not in ("4", "5", "6")}
    items = [dict(i) for i in ITEMS]
    items[9]["time_s"] = None
    items[8]["time_s"] = 10.0
    s = rules.aggregate("camera", items, [], obs, WIN)
    assert s["totals"]["off_items"] == 3 and s["points"] == 2
    assert s["per_item"][3]["uncovered_ms"] == 55_000  # 60 с − 5 с запаса на переход между заданиями
    assert s["per_item"][8]["uncovered_ms"] == 0 and s["per_item"][9]["uncovered_ms"] == 0


def test_windows_mid_and_stop_note():
    # камера включена посреди 4-го задания и выключена кандидатом на 8-м: наблюдались задания 4–7; покрытие по 4-му
    # не проверяется; события вне окна не учитываются; у работодателя — заметка о выключении
    win = [{"from": 4, "to": 8, "mid": True}]
    evs = [ev(2, "no_face", 60_000), ev(5, "no_face", 25_000), ev(9, "multi_face", 30_000, 2)]
    s = rules.aggregate("camera", ITEMS, evs, {"5": OBS["5"], "6": OBS["6"], "7": OBS["7"]}, win,
                        {"position": 8, "reason": "user"})
    assert [p["position"] for p in s["per_item"]] == [4, 5, 6, 7]
    assert s["per_item"][0]["uncovered_ms"] == 0 and s["totals"]["multi_face_items"] == 0
    assert s["points"] == 1 and s["remarks"] == ["нет лица в кадре 25\u00a0с на 1 задании"]
    assert s["notes"] == ["камера выключена кандидатом на задании 8 — дальше тест шёл без камеры"]
    v = rules.employer_view(s)
    assert v["notes"] == s["notes"] and v["title"] == "Камера: включена, есть замечания"
    s2 = rules.aggregate("camera", ITEMS, [], OBS, [{"from": 1, "to": 3, "mid": False}], {"position": 3, "reason": "revoked"})
    assert s2["notes"][0].startswith("согласие отозвано на задании 3")


def test_helpers():
    assert rules.dur(40) == "40\u00a0с" and rules.dur(150) == "2,5\u00a0мин" and rules.dur(120) == "2\u00a0мин"
    assert rules.dur(900) == "15\u00a0мин"
    assert rules.on_items(1) == "на 1 задании" and rules.on_items(3) == "на 3 заданиях" and rules.on_items(11) == "на 11 заданиях"
    st = {"items": [{"position": 1, "token": "a", "done": True, "time_s": 12.5}, {"position": 2, "token": "b", "done": False}],
          "current": "b"}
    assert rules.items_from_state(st) == [{"position": 1, "token": "a", "time_s": 12.5, "canary": False},
                                          {"position": 2, "token": "b", "time_s": None, "canary": False}]
    assert rules.current_position(st) == 2
    assert rules.current_position({"items": [{"position": 1, "token": "a", "done": True}]}) == 2
    assert rules.current_position({"item_ids": ["x", "y"], "answers": {"x": {}}}) == 2


# ------------------------------------------------------------------ подключение к общей достоверности

def test_add_reasons_keeps_level_without_points():
    base = integrity.assess([{"format": "mcq_concept", "canary": False, "time_s": 30, "time_limit_s": 60, "score": 1,
                              "signals": {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0}}] * 8)
    assert base["level"] == "high"
    out = integrity.add_reasons(base, [], camera={"mode": "off", "title": "Тест без камеры", "remarks": [], "notes": []})
    assert out["level"] == "high" and out["points"] == 0 and out["reasons"] == base["reasons"]
    assert out["camera"]["title"] == "Тест без камеры"
    # дефолтная причина «Сигналов нарушений нет» заменяется причинами камеры; уровень — по сумме баллов
    out = integrity.add_reasons(base, [(1, "Камера: нет лица в кадре 25\u00a0с на 1 задании")], camera={"mode": "on"})
    assert out["level"] == "medium" and out["points"] == 1 and out["reasons"] == ["Камера: нет лица в кадре 25\u00a0с на 1 задании"]
    out = integrity.add_reasons({**base, "points": 2, "level": "medium", "reasons": ["Уход со вкладки"]},
                                [(2, "Камера: в кадре несколько лиц"), (1, "Камера: нет лица")])
    assert out["level"] == "low" and out["points"] == 5
    assert out["reasons"] == ["Уход со вкладки", "Камера: в кадре несколько лиц", "Камера: нет лица"]
    assert "camera" not in integrity.summary_for_employer(out)  # без сводки камеры ключа нет
    emp = integrity.summary_for_employer({**out, "camera": {"mode": "on", "title": "Камера: включена, есть замечания"}})
    assert emp["camera"]["title"] == "Камера: включена, есть замечания"


# ------------------------------------------------------------------ API

def _candidate(client, email="cam@example.com"):
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    return t


def _session(client, t) -> dict:
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", "integrity_ack": True}, headers=H(t))
    assert r.status_code == 201, r.text
    return r.json()


def _answer_all(client, t, s: dict) -> dict:
    sid = s["session_id"]
    n = 0
    while s["item"]:
        it = s["item"]
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t),
                        json={"item_id": it["item_id"], "answer": it["options"][0]["id"], "time_spent_ms": 7000,
                              "signals": {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0}})
        assert r.status_code == 200, r.text
        s = r.json()
        n += 1
        assert n < 40
    return s


def test_consent_text_and_lifecycle(client):
    t = _candidate(client)
    c = client.get("/api/proctor/consent", headers=H(t)).json()
    assert c["active"] is False and c["enabled"] is True and c["current_version"] == c["text"]["version"]
    txt = c["text"]
    assert txt["kind"] == "proctoring" and txt["what"] and txt["stored"] and txt["how_long"] and txt["who_sees"]
    assert "ИНН" in txt["operator"] and "не биометрическая идентификация" in " ".join(txt["what"]).lower()
    raw = json.dumps(txt, ensure_ascii=False)
    for word in ("не отправляются", "Работодатель", "без камеры", "отозвать"):
        assert word in raw, word
    r = client.post("/api/proctor/consent", headers=H(t))
    assert r.status_code == 201 and r.json()["version"] == c["current_version"]
    c = client.get("/api/proctor/consent", headers=H(t)).json()
    assert c["active"] and c["version"] == c["current_version"] and c["granted_at"]
    # повторное согласие — та же запись; в списке согласий кандидата появился новый вид
    client.post("/api/proctor/consent", headers=H(t))
    mine = client.get("/api/me/consents", headers=H(t)).json()
    assert sum(1 for x in mine if x["kind"] == "proctoring" and not x["revoked_at"]) == 1
    r = client.delete("/api/proctor/consent", headers=H(t))
    assert r.status_code == 200 and r.json()["granted"] is False and r.json()["stopped_sessions"] == 0
    assert client.get("/api/proctor/consent", headers=H(t)).json()["active"] is False
    mine = client.get("/api/me/consents", headers=H(t)).json()
    assert [x["revoked_at"] is not None for x in mine if x["kind"] == "proctoring"] == [True]


def test_camera_requires_consent_and_modes(client):
    t = _candidate(client)
    s = _session(client, t)
    sid = s["session_id"]
    r = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"
    assert client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "selfie"}, headers=H(t)).status_code == 422
    # без камеры: нейтральный режим, событий не принимает
    r = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "unsupported", "reason": "нет WebAssembly SIMD"},
                    headers=H(t))
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["mode"] == "unsupported" and v["camera_active"] is False and v["summary"]["title"] == "Тест без камеры"
    r = client.post(f"/api/proctor/sessions/{sid}/events", json={"events": [], "observed": []}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "camera_not_enabled"
    # согласие → камера включена посреди теста: окно с текущего задания и признаком mid
    client.post("/api/proctor/consent", headers=H(t))
    r = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera", "client": {"model": "blaze_face_short_range",
                    "fps": 1.4, "backend": "cpu", "secret": "x" * 100}}, headers=H(t))
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["mode"] == "camera" and v["camera_active"] and v["windows"] == [{"from": 1, "to": None, "mid": False}]
    assert v["consent_version"] == client.get("/api/proctor/consent", headers=H(t)).json()["current_version"]
    # повторный старт (перезагрузка страницы) — то же окно, resumes += 1
    v = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t)).json()
    assert v["resumes"] == 1 and len(v["windows"]) == 1
    # кнопка «выключить камеру» → окно закрыто, события больше не принимаются, тест продолжается
    v = client.post(f"/api/proctor/sessions/{sid}/stop", json={"reason": "user"}, headers=H(t)).json()
    assert v["camera_active"] is False and v["windows"][0]["to"] == 1
    r = client.post(f"/api/proctor/sessions/{sid}/events", json={"events": [], "observed": []}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "camera_stopped"
    assert client.get(f"/api/assessment/sessions/{sid}", headers=H(t)).json()["status"] == "in_progress"
    with SessionLocal() as db:
        from app.modules.proctor.models import ProctorSession

        ps = db.scalar(__import__("sqlalchemy").select(ProctorSession))
        assert ps.client == {"model": "blaze_face_short_range", "fps": "1.4", "backend": "cpu"}  # без лишних ключей


def test_events_recorded_and_result_for_candidate(client):
    t = _candidate(client)
    client.post("/api/proctor/consent", headers=H(t))
    s = _session(client, t)
    sid, first = s["session_id"], s["item"]["item_id"]
    assert client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t)).status_code == 200
    r = client.post(f"/api/proctor/sessions/{sid}/events", headers=H(t), json={
        "events": [{"item_id": first, "kind": "no_face", "duration_ms": 26_000, "at_ms": 1},  # время явно неверное → не хранится
                   {"item_id": first, "kind": "multi_face", "duration_ms": 1000, "faces": 2},  # короче MIN_MS — хранится, не считается
                   {"item_id": "foreign", "kind": "no_face", "duration_ms": 90_000},  # чужой токен — отбрасывается
                   {"item_id": first, "kind": "camera_off", "duration_ms": 3_600_000}],  # верхняя граница схемы
        "observed": [{"item_id": first, "ms": 20_000, "frames": 28, "face": 10}, {"item_id": "foreign", "ms": 5}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 3, "events_total": 3, "dropped": 0}
    # невалидные значения — 422 от схемы (отрицательная длительность, больше часа, неизвестный вид, больше 100 событий)
    for bad in ({"item_id": first, "kind": "no_face", "duration_ms": -1}, {"item_id": first, "kind": "no_face", "duration_ms": 3_600_001},
                {"item_id": first, "kind": "yawn", "duration_ms": 5000}):
        assert client.post(f"/api/proctor/sessions/{sid}/events", headers=H(t), json={"events": [bad]}).status_code == 422, bad
    many = [{"item_id": first, "kind": "no_face", "duration_ms": 5000}] * 101
    assert client.post(f"/api/proctor/sessions/{sid}/events", headers=H(t), json={"events": many}).status_code == 422
    v = client.get(f"/api/proctor/sessions/{sid}", headers=H(t)).json()
    assert len(v["events"]) == 3 and v["events"][0]["at"] is None and v["events"][0]["counted"] is True
    assert v["events"][1]["counted"] is False and v["events"][2]["duration_s"] == rules.MAX_EVENT_MS / 1000
    assert v["items"][0]["observed_s"] == 20.0 and v["items"][0]["no_face_s"] == 26.0
    assert v["summary"]["title"] == "Камера: включена, есть замечания"
    s = _answer_all(client, t, s)
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    assert "camera" not in json.dumps(res["details"])  # ответ finish кандидату — только ход теста (как раньше)
    with SessionLocal() as db:
        from app.modules.assessment.models import TestSession
        from app.modules.proctor.models import ProctorSession

        ts = db.get(TestSession, uuid.UUID(sid))
        cam = ts.result["engine_result"]["details"]["camera"]
        assert cam["mode"] == "on" and cam["title"] == "Камера: включена, есть замечания"
        assert cam["remarks"][0].startswith("камера закрыта или не передавала изображение")
        ps = db.scalar(__import__("sqlalchemy").select(ProctorSession))
        assert ps.finished_at is not None and ps.summary["points"] >= 2 and "per_item" not in ps.summary
    # завершённая сессия: события больше не принимаются, итог виден в «моих тестах»
    r = client.post(f"/api/proctor/sessions/{sid}/events", json={"events": [], "observed": []}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "session_closed"
    mine = client.get("/api/proctor/me/sessions", headers=H(t)).json()
    assert mine[0]["session_id"] == sid and mine[0]["mode"] == "camera" and mine[0]["events"] == 3
    assert mine[0]["summary"]["mode"] == "on"


def test_revoke_closes_window_mid_test(client):
    t = _candidate(client)
    client.post("/api/proctor/consent", headers=H(t))
    s = _session(client, t)
    sid = s["session_id"]
    client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t))
    # ответили на одно задание → текущее задание 2
    it = s["item"]
    client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t),
                json={"item_id": it["item_id"], "answer": it["options"][0]["id"]})
    r = client.delete("/api/proctor/consent", headers=H(t))
    assert r.json()["stopped_sessions"] == 1
    v = client.get(f"/api/proctor/sessions/{sid}", headers=H(t)).json()
    assert v["camera_active"] is False and v["windows"] == [{"from": 1, "to": 2, "mid": False}]
    assert v["summary"]["notes"] == ["согласие отозвано на задании 2 — дальше тест шёл без камеры"]
    r = client.post(f"/api/proctor/sessions/{sid}/events", json={"events": [], "observed": []}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "camera_stopped"
    # включить снова без согласия нельзя; тест при этом идёт
    r = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"
    assert client.get(f"/api/assessment/sessions/{sid}", headers=H(t)).json()["item"] is not None


def test_permissions(client):
    t = _candidate(client)
    sid = _session(client, t)["session_id"]
    other = _candidate(client, "other@example.com")
    emp = register_and_verify(client, email="emp@example.com", role="employer")
    for path, method, body in ((f"/api/proctor/sessions/{sid}/start", "post", {"mode": "declined"}),
                               (f"/api/proctor/sessions/{sid}/events", "post", {"events": []}),
                               (f"/api/proctor/sessions/{sid}/stop", "post", {"reason": "user"}),
                               (f"/api/proctor/sessions/{sid}", "get", None)):
        kw = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=H(emp), **kw).status_code == 403, path  # работодатель
        assert getattr(client, method)(path, headers=H(other), **kw).status_code == 404, path  # чужая сессия
        assert getattr(client, method)(path, **kw).status_code == 401, path
    assert client.get("/api/proctor/consent", headers=H(emp)).status_code == 403
    assert client.get(f"/api/proctor/sessions/{uuid.uuid4()}", headers=H(t)).status_code == 404
    assert client.get("/api/proctor/stats", headers=H(t)).status_code == 403
    assert client.get("/api/proctor/stats", headers=H(emp)).status_code == 403
    from tests.test_fsp_cabinet import analyst_token

    a = analyst_token(client)
    r = client.get("/api/proctor/stats?days=30", headers=H(a))
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["period_days"] == 30 and st["k_min"] == 5 and st["tests_finished"] == 0 and st["enabled"] is True
    assert st["modes"]["camera"] == 0 and st["camera_share"] is None


def test_feature_flag_disables_camera(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "proctor_camera_enabled", False)
    assert client.get("/api/meta").json()["proctor_camera"] is False
    t = _candidate(client)
    assert client.get("/api/proctor/consent", headers=H(t)).json()["enabled"] is False
    r = client.post("/api/proctor/consent", headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "camera_disabled"
    s = _session(client, t)
    sid = s["session_id"]
    r = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "camera_disabled"
    # тест без записи о камере проходит полностью; итог — нейтральная пометка
    s = _answer_all(client, t, s)
    assert client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).status_code == 200
    with SessionLocal() as db:
        from app.modules.assessment.models import TestSession

        cam = db.get(TestSession, uuid.UUID(sid)).result["engine_result"]["details"]["camera"]
        assert cam == {"mode": "off", "title": "Тест без камеры", "remarks": [], "notes": []}


# ------------------------------------------------------------------ банк заданий: итог у работодателя

class _Clock:
    """Часы движка банка: каждый ответ «занимает» половину рекомендуемого времени по часам сервера — иначе
    мгновенные ответы теста дали бы «аномально быстро», и влияние камеры на достоверность было бы не видно."""

    def __init__(self):
        self.offset = 0.0

    def time(self):
        import time

        return time.time() + self.offset


@pytest.fixture
def bank_api(monkeypatch):
    from app.core.config import get_settings
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.grader import GradeOutcome

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm"))
    clock = _Clock()
    monkeypatch.setattr(be, "time", clock)
    # те же часы — у приёма событий камеры (ограничение наблюдения по заданию считается от времени сессии)
    from datetime import UTC, datetime

    from app.modules.proctor import service as proctor_service

    monkeypatch.setattr(proctor_service, "utcnow", lambda: datetime.fromtimestamp(clock.time(), UTC))
    return clock


def _run_bank(client, t, sid, s, on_item=None, clock=None):
    from tests.test_bank_engine import _state, oracle

    while s["item"]:
        it_pub = s["item"]
        it = next(i for i in _state(sid)["items"] if i["token"] == it_pub["item_id"])
        spent_ms = int(it_pub["time_limit_s"] * 500)
        if clock is not None:  # время на задание прошло, браузер отправляет наблюдение и ответ
            clock.offset += spent_ms / 1000
        if on_item:
            on_item(it_pub, spent_ms)
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json={
            "item_id": it_pub["item_id"], "answer": oracle(it, it_pub["step"] or 1, True), "step": it_pub["step"],
            "time_spent_ms": 4000, "signals": {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0}})
        assert r.status_code == 200, r.text
        s = r.json()
    return client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()


def test_bank_camera_without_remarks_in_employer_card(client, bank_api):
    t = _candidate(client, "bankcam@example.com")
    client.post("/api/proctor/consent", headers=H(t))
    s = _session(client, t)
    sid = s["session_id"]
    assert client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t)).status_code == 200
    seen = []

    def observe(it_pub, spent_ms):  # браузер: камера наблюдала каждое задание всё его время, лицо в кадре
        r = client.post(f"/api/proctor/sessions/{sid}/events", headers=H(t), json={"events": [], "observed": [
            {"item_id": it_pub["item_id"], "ms": spent_ms, "frames": spent_ms // 700, "face": spent_ms // 700}]})
        assert r.status_code == 200, r.text
        seen.append(it_pub["item_id"])

    res = _run_bank(client, t, sid, s, observe, bank_api)
    assert res["confirmed"], res
    card = client.get("/api/me/card", headers=H(t)).json()
    integ = card["test"]["integrity"]
    assert integ["level"] == "high" and integ["camera"]["title"] == "Камера: включена, замечаний нет"
    assert integ["camera"]["mode"] == "on" and integ["camera"]["remarks"] == []
    raw = json.dumps(card, ensure_ascii=False)
    assert "per_item" not in raw and "observed" not in raw  # работодателю — только итог
    with SessionLocal() as db:
        from app.modules.assessment.models import TestSession

        d = db.get(TestSession, uuid.UUID(sid)).result["engine_result"]["details"]
        assert d["integrity"]["points"] == 0 and d["camera"]["mode"] == "on"
        assert d["integrity"]["reasons"][0].startswith("Сигналов нарушений нет")
    # грейд и θ камера не меняет: подтверждён, категория присвоена
    assert card["category"]["id"] == "backend.middle"


def test_bank_camera_remarks_lower_integrity_only(client, bank_api):
    t = _candidate(client, "bankcam2@example.com")
    client.post("/api/proctor/consent", headers=H(t))
    s = _session(client, t)
    sid = s["session_id"]
    client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "camera"}, headers=H(t))
    seen = []

    def observe(it_pub, spent_ms):  # на первых трёх заданиях в кадре было два лица; остальное — норма
        if it_pub["item_id"] not in seen:
            seen.append(it_pub["item_id"])
        evs = ([{"item_id": it_pub["item_id"], "kind": "multi_face", "duration_ms": 4000, "faces": 2}]
               if len(seen) <= 3 and it_pub["item_id"] == seen[-1] and (it_pub["step"] or 1) == 1 else [])
        r = client.post(f"/api/proctor/sessions/{sid}/events", headers=H(t), json={"events": evs, "observed": [
            {"item_id": it_pub["item_id"], "ms": spent_ms, "frames": spent_ms // 700, "face": spent_ms // 700}]})
        assert r.status_code == 200, r.text

    res = _run_bank(client, t, sid, s, observe, bank_api)
    assert res["confirmed"], res  # замечания камеры не меняют решение по грейду
    integ = client.get("/api/me/card", headers=H(t)).json()["test"]["integrity"]
    assert integ["level"] == "medium" and integ["camera"]["title"] == "Камера: включена, есть замечания"
    assert integ["camera"]["remarks"] == ["в кадре несколько лиц на 3 заданиях (12\u00a0с)"]
    assert integ["reasons"] == ["Камера: в кадре несколько лиц на 3 заданиях (12\u00a0с)"]
    # обратная связь кандидату показывает ту же достоверность с причиной камеры
    fb = client.get("/api/assessment/feedback", headers=H(t)).json()
    assert fb["session"]["integrity"]["camera"]["mode"] == "on"
    # тот же кандидат: «мои тесты» — события и итог
    mine = client.get("/api/proctor/me/sessions", headers=H(t)).json()
    assert mine[0]["events"] == 3 and mine[0]["summary"]["title"] == "Камера: включена, есть замечания"


def test_bank_without_camera_neutral(client, bank_api):
    t = _candidate(client, "bankcam3@example.com")
    s = _session(client, t)
    sid = s["session_id"]
    r = client.post(f"/api/proctor/sessions/{sid}/start", json={"mode": "declined"}, headers=H(t))
    assert r.status_code == 200
    res = _run_bank(client, t, sid, s, clock=bank_api)
    assert res["confirmed"], res
    integ = client.get("/api/me/card", headers=H(t)).json()["test"]["integrity"]
    assert integ["level"] == "high" and integ["camera"] == {"mode": "off", "title": "Тест без камеры", "remarks": [],
                                                           "notes": []}
    assert integ["reasons"][0].startswith("Сигналов нарушений нет")


# ------------------------------------------------------------------ демо жюри и агрегат ФСП

def test_jury_seed_camera_and_fsp_stats(client):
    tok = client.post("/api/jury/login", json={"persona": "candidate"}).json()["access_token"]
    mine = client.get("/api/proctor/me/sessions", headers=H(tok)).json()
    assert mine and mine[0]["mode"] == "camera" and mine[0]["summary"]["title"] == "Камера: включена, замечаний нет"
    tok2 = client.post("/api/jury/login", json={"persona": "candidate_nofsp"}).json()["access_token"]
    mine2 = client.get("/api/proctor/me/sessions", headers=H(tok2)).json()
    assert mine2 and mine2[0]["mode"] == "declined" and mine2[0]["summary"]["title"] == "Тест без камеры"
    # работодатель жюри видит итог камеры в карточках подборки: у Марии — включена, у Ильи — без камеры
    e = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]
    needs = client.get("/api/employer/needs", headers=H(e)).json()
    titles = set()
    for n in needs:
        for ver in client.get(f"/api/employer/needs/{n['id']}", headers=H(e)).json()["versions"]:
            sel = client.get(f"/api/employer/needs/{n['id']}/selections/{ver['version']}", headers=H(e)).json()
            titles |= {((r.get("card") or {}).get("test") or {}).get("integrity", {}).get("camera", {}).get("title")
                       for r in sel["results"]}
    assert {"Камера: включена, замечаний нет", "Тест без камеры"} <= titles, titles
    f = client.post("/api/jury/login", json={"persona": "fsp"}).json()["access_token"]
    st = client.get("/api/proctor/stats", headers=H(f)).json()
    assert st["tests_finished"] >= 2 and st["modes"]["camera"] is None  # группа меньше 5 скрыта
