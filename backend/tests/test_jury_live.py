"""Идея 13: живая демонстрация для жюри — QR → мини-тест на телефоне → экспресс-категория → подборка →
автоприглашение с push; экран зала; изоляция песочниц, лимиты, ключи заданий не уходят на клиент."""
import json

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from tests.conftest import register_and_verify
from tests.test_day2_rules import H

SECRET_FIELDS = {"key", "state", "seed", "variant_id", "family_id", "x", "answers", "token_hash", "user_id", "sid",
                 "accept", "pool"}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    from app.core.config import get_settings
    from app.integrations.push.service import SENT_LOG

    monkeypatch.setattr(get_settings(), "jury_live_select_delay_s", 0)
    monkeypatch.setattr(get_settings(), "jury_live_invite_delay_s", 0)
    SENT_LOG.clear()


def _login(client, persona, scenario="new"):
    r = client.post("/api/jury/login", json={"persona": persona, "scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()


def _room(client, token):
    r = client.post("/api/jury/live/room", headers=H(token))
    assert r.status_code == 200, r.text
    return r.json()


def _keys(code, token=None):
    """Ключ текущего задания гостя — только из БД (в тестах), наружу он не отдаётся.
    Гость ищется по токену текущего задания: «последний созданный» неоднозначен при одинаковом времени создания."""
    from app.jury_live import mini
    from app.jury_live.models import LiveGuest

    with SessionLocal() as db:
        guests = db.scalars(select(LiveGuest).order_by(LiveGuest.created_at.desc())).all()
        for g in guests:
            it = mini.current(g.state)
            if it is not None and (token is None or it.get("token") == token):
                return it["format"], it["key"]["value"], it["public"]["code_lines"]
        raise AssertionError("гость с таким заданием не найден")


def _answer(client, code, gt, item, correct=True):
    fmt, key, lines = _keys(code, item.get("token"))
    if fmt == "find_bug":
        value = int(key) if correct else (1 if int(key) != 1 else 2)
    else:
        ids = [o["id"] for o in item["options"]]
        value = key if correct else next(i for i in ids if i != key)
    r = client.post(f"/api/jury/live/j/{code}/answer", json={"token": item["token"], "value": value},
                    headers={"X-Guest-Token": gt})
    assert r.status_code == 200, r.text
    return r.json()


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + "/" + k, k
            yield from _walk(v, path + "/" + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _no_secrets(payload):
    bad = [p for p, k in _walk(payload) if k in SECRET_FIELDS]
    assert not bad, bad


def test_live_full_flow_qr_test_selection_invite_push(client):
    from app.integrations.push.service import SENT_LOG
    from app.modules.invitations.models import Invitation

    emp = _login(client, "employer")
    room = _room(client, emp["access_token"])
    code = room["code"]
    assert room["url"].endswith(f"/j/{code}") and len(code) == 6
    assert _room(client, emp["access_token"])["code"] == code  # код зала постоянный
    # QR, манифест и сведения о зале — без авторизации (открываются с телефона)
    svg = client.get(room["qr_svg"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and "<path" in svg.text
    png = client.get(room["qr_png"], params={"download": 1})
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n" and "attachment" in png.headers["content-disposition"]
    man = client.get(f"/api/jury/live/j/{code}/manifest.webmanifest").json()
    assert man["start_url"] == f"/j/{code}?source=pwa" and man["display"] == "standalone"
    pub = client.get(f"/api/jury/live/j/{code.upper()}").json()
    assert pub["open"] and pub["items"] == 3 and {d["id"] for d in pub["directions"]} >= {"backend", "qa"}
    _no_secrets(pub)
    assert client.get("/api/jury/live/j/zzzzzz").status_code == 404

    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "backend"})
    assert r.status_code == 201, r.text
    gt, me = r.json()["token"], r.json()["guest"]
    _no_secrets(r.json()["guest"])
    assert me["stage"] == "testing" and me["item"]["position"] == 1 and me["item"]["total"] == 3
    assert me["item"]["format"] in ("mcq_concept", "choose_fix", "find_bug")
    assert client.get(f"/api/jury/live/j/{code}/me").status_code == 401
    assert client.get(f"/api/jury/live/j/{code}/me", headers={"X-Guest-Token": "x" * 30}).status_code == 401
    # подписка телефона на push (браузерный endpoint — любой https)
    sub = {"endpoint": "https://push.example.org/send/abc123", "keys": {"p256dh": "p" * 20, "auth": "a" * 12}}
    assert client.post(f"/api/jury/live/j/{code}/push", json=sub, headers={"X-Guest-Token": gt}).json()["devices"] == 1
    # чужой токен задания и пустой ответ — не принимаются
    bad = client.post(f"/api/jury/live/j/{code}/answer", json={"token": "nope", "value": "A"},
                      headers={"X-Guest-Token": gt})
    assert bad.status_code == 422
    seen_items = []
    for _ in range(3):
        seen_items.append(me["item"]["token"])
        me = _answer(client, code, gt, me["item"], correct=True)
        _no_secrets(me)
        if me["stage"] == "testing":
            assert "correct" not in json.dumps(me["item"])  # правильность — только в итоге
    assert len(set(seen_items)) == 3
    assert me["stage"] == "invited", me
    res = me["result"]
    assert res["correct"] == 3 and res["answered"] == 3 and res["grade"] in ("middle", "senior")
    assert res["category_id"] == f"backend.{res['grade']}" and res["skills"]
    sel = me["selection"]
    assert sel["rank"] >= 1 and sel["total"] >= sel["rank"] and sel["need_title"].startswith("Живая демонстрация")
    assert any("Экспресс-категория" in x["text"] for x in sel["reasons"])
    inv = me["invite"]
    assert inv["salary_from"] > 0 and inv["salary_to"] <= 1.5 * inv["salary_from"]
    assert inv["company"]["name"].startswith("Демо жюри") and inv["status"] in ("sent", "viewed")
    assert any("мини-тесту" in e["text"] for e in inv["evidence"])
    # push о приглашении — на телефон гостя, ссылка ведёт на страницу мини-теста (без входа на стенд)
    pushes = [p for p in SENT_LOG if p["url"] == f"/j/{code}"]
    assert len(pushes) == 1 and pushes[0]["devices"] == 1
    # экран зала: гость, его место в подборке, «почему», приглашение и лента событий
    feed = client.get("/api/jury/live/room/feed", headers=H(emp["access_token"])).json()
    assert feed["changed"] and feed["counters"]["invited"] == 1 and feed["counters"]["joined"] == 1
    g = feed["guests"][0]
    assert g["stage"] == "invited" and g["selection"]["top"] and any(t["is_self"] for t in g["selection"]["top"])
    assert g["invite"]["push"]["devices"] == 1
    kinds = {e["kind"] for e in feed["events"]}
    assert {"joined", "answered", "finished", "selected", "invited", "push"} <= kinds
    _no_secrets(feed)
    # без изменений экран получает короткий ответ
    same = client.get("/api/jury/live/room/feed", params={"rev": feed["rev"], "since": feed["now"]},
                      headers=H(emp["access_token"])).json()
    assert same == {"changed": False, "rev": feed["rev"], "now": same["now"]}
    # гость увидел приглашение → «просмотрено» у работодателя; принял → контакты открыты, push работодателю
    client.get(f"/api/jury/live/j/{code}/me", params={"visible": 1}, headers={"X-Guest-Token": gt})
    me = client.post(f"/api/jury/live/j/{code}/respond", json={"accept": True}, headers={"X-Guest-Token": gt}).json()
    assert me["stage"] == "accepted"
    assert client.post(f"/api/jury/live/j/{code}/respond", json={"accept": False},
                       headers={"X-Guest-Token": gt}).status_code == 409
    invs = client.get("/api/employer/invitations", headers=H(emp["access_token"])).json()
    mine = next(i for i in invs if i["candidate_ref"] == me["ref"])
    assert mine["status"] == "accepted" and mine["salary_from"] == inv["salary_from"]
    feed = client.get("/api/jury/live/room/feed", headers=H(emp["access_token"])).json()
    assert {"viewed", "accepted"} <= {e["kind"] for e in feed["events"]} and feed["counters"]["accepted"] == 1
    # приглашение — настоящее: в подборке работодателя новая версия с гостем
    with SessionLocal() as db:
        assert db.scalar(select(Invitation).where(Invitation.status == "accepted"))
    needs = client.get("/api/employer/needs", headers=H(emp["access_token"])).json()
    live = next(n for n in needs if n["title"] == sel["need_title"])
    v = client.get(f"/api/employer/needs/{live['id']}/selections/{sel['version']}", headers=H(emp["access_token"])).json()
    assert me["ref"] in {c["ref"] for c in v["results"]}
    # тест закрыт: повторный ответ — 409
    assert client.post(f"/api/jury/live/j/{code}/answer", json={"token": seen_items[-1], "value": "A"},
                       headers={"X-Guest-Token": gt}).status_code == 409


def test_live_zero_correct_no_category_no_invite(client):
    emp = _login(client, "employer")
    code = _room(client, emp["access_token"])["code"]
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "qa"}).json()
    gt, me = r["token"], r["guest"]
    for _ in range(3):
        me = _answer(client, code, gt, me["item"], correct=False)
    assert me["stage"] == "no_category" and me["result"]["grade"] is None and me["invite"] is None
    feed = client.get("/api/jury/live/room/feed", headers=H(emp["access_token"])).json()
    assert feed["counters"]["finished"] == 1 and feed["counters"]["invited"] == 0


def test_live_isolation_reset_clear_and_access(client):
    from app.modules.jury import seed

    a = _login(client, "employer")
    b = _login(client, "employer")
    ra, rb = _room(client, a["access_token"]), _room(client, b["access_token"])
    assert ra["code"] != rb["code"]
    r = client.post(f"/api/jury/live/j/{ra['code']}/start", json={"direction": "backend"}).json()
    gt, me = r["token"], r["guest"]
    for _ in range(3):
        me = _answer(client, ra["code"], gt, me["item"])
    ref = me["ref"]
    seen = lambda t: {c["ref"] for c in client.get("/api/employer/candidates", params={"direction": "backend"},  # noqa: E731
                                                   headers=H(t)).json()["items"]}
    assert ref in seen(a["access_token"])
    assert ref not in seen(b["access_token"])  # чужая песочница гостя не видит
    shared = client.post("/api/jury/login", json={"persona": "employer"}).json()
    assert ref not in seen(shared["access_token"])  # общее демо — тоже
    real = register_and_verify(client, "hr@real.example.org", role="employer", company_name="Настоящая")
    assert ref not in seen(real)
    # гость зала A не виден на экране B, токен гостя A не работает в зале B
    assert client.get("/api/jury/live/room/feed", headers=H(b["access_token"])).json()["counters"]["joined"] == 0
    assert client.get(f"/api/jury/live/j/{rb['code']}/me", headers={"X-Guest-Token": gt}).status_code == 401
    # залы — только у работодателя своей песочницы
    assert client.post("/api/jury/live/room", headers=H(shared["access_token"])).status_code == 403
    cand = _login(client, "candidate", a["scenario"])
    assert client.post("/api/jury/live/room", headers=H(cand["access_token"])).status_code == 403
    assert client.post("/api/jury/live/room").status_code == 401
    assert client.post("/api/jury/live/room", headers=H(real)).status_code == 403
    # сброс своей песочницы удаляет её гостей; код зала прежний — QR на слайде рабочий
    reset = client.post("/api/jury/reset", headers=H(a["access_token"])).json()
    assert _room(client, reset["access_token"])["code"] == ra["code"]
    assert client.get("/api/jury/live/room/feed", headers=H(reset["access_token"])).json()["counters"]["joined"] == 0
    assert client.get(f"/api/jury/live/j/{ra['code']}/me", headers={"X-Guest-Token": gt}).status_code == 401
    # «Очистить зал» — только свой
    client.post(f"/api/jury/live/j/{rb['code']}/start", json={"direction": "frontend"})
    client.post(f"/api/jury/live/j/{ra['code']}/start", json={"direction": "frontend"})
    assert client.post("/api/jury/live/room/clear", headers=H(b["access_token"])).json()["deleted"] == 1
    assert client.get("/api/jury/live/room/feed", headers=H(reset["access_token"])).json()["counters"]["joined"] == 1
    # песочница удалена (вытеснение по лимиту) — зал закрыт; вход с тем же sid возвращает его
    with SessionLocal() as db:
        seed.delete_jury(db, b["scenario"])
    r = client.post(f"/api/jury/live/j/{rb['code']}/start", json={"direction": "backend"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "room_closed"
    assert client.get(f"/api/jury/live/j/{rb['code']}").json()["open"] is False
    again = _login(client, "employer", b["scenario"])
    assert _room(client, again["access_token"])["code"] == rb["code"]
    assert client.post(f"/api/jury/live/j/{rb['code']}/start", json={"direction": "backend"}).status_code == 201


def test_live_rate_limits_and_validation(client, monkeypatch):
    from app.jury_live import router as lr

    emp = _login(client, "employer")
    code = _room(client, emp["access_token"])["code"]
    assert client.post(f"/api/jury/live/j/{code}/start", json={"direction": "devops"}).status_code == 422
    monkeypatch.setattr(lr._guest_ip, "limit", 2)
    assert client.post(f"/api/jury/live/j/{code}/start", json={"direction": "security"}).status_code == 201
    assert client.post(f"/api/jury/live/j/{code}/start", json={"direction": "data_ml"}).status_code == 201
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "frontend"})
    assert r.status_code == 429 and r.headers.get("retry-after")
    # другой адрес — свой лимит, но лимит зала общий
    monkeypatch.setattr(lr._guest_room, "limit", 3)
    ok = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "frontend"},
                     headers={"X-Forwarded-For": "203.0.113.7"})
    assert ok.status_code == 201
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "frontend"},
                    headers={"X-Forwarded-For": "203.0.113.8"})
    assert r.status_code == 429


def test_mini_engine_adaptive_and_bounded():
    from app.jury_live import mini

    for d in mini.DIRECTIONS:
        pool = mini.pool(d)
        assert len(pool) >= 6 and all(p.format in mini.FORMATS and not p.canary for p in pool)
    st = mini.new_state("frontend")
    fams = []
    for k in range(3):
        it = mini.current(st)
        fams.append(it["family_id"])
        pub = mini.public_item(st)
        assert pub["position"] == k + 1 and "key" not in pub
        key = it["key"]["value"]
        assert mini.answer(st, "wrong-token", key) is None
        assert mini.answer(st, it["token"], key if it["format"] != "find_bug" else int(key))
    assert mini.finished(st) and mini.current(st) is None and len(set(fams)) == 3
    r = mini.result(st)
    assert r["correct"] == 3 and r["theta"] > 0.5 and r["grade"] in ("middle", "senior")


def test_qr_matrix_png_svg():
    from app.jury_live import qr

    m = qr.matrix("https://fsp.neuropeople.pro/j/abc234")
    assert len(m) in (25, 29, 33) and all(len(r) == len(m) for r in m)
    assert m[0][:7] == (True,) * 7  # шаблон поиска в углу
    assert qr.png("https://x.example/j/abc234", 4)[:4] == b"\x89PNG"
    assert qr.svg("https://x.example/j/abc234").startswith("<svg")
