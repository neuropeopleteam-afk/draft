"""QR-демо жюри в мире из 500 кандидатов (Ф1, С-1): гость вне первых 60 в подборке получает место и приглашение."""
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from tests.test_day2_rules import H
from tests.test_jury_live import _answer, _login, _room


@pytest.fixture
def _fast_live(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "jury_live_select_delay_s", 0)
    monkeypatch.setattr(get_settings(), "jury_live_invite_delay_s", 0)


def test_qr_guest_gets_place_and_invite_in_world_of_500(client, _fast_live, monkeypatch):
    """Гость после мини-теста получает приглашение и своё настоящее место, даже если оно ниже окна подборки
    (на стенде Backend: из 139 — гость не попадал в топ-60, и приглашения не было).
    После Ф2 условия живой потребности («Удалённо») применяются сразу, и в мире из 500 в выдаче остаётся около 60
    удалённых кандидатов направления — окно сужено до 10, чтобы место гостя гарантированно оказалось за его пределами."""
    from app.jury_live import service as S

    monkeypatch.setattr(S, "SELECTION_LIMIT", 10)
    from app.jury_live.models import LiveGuest
    from app.modules.demo.seed import seed
    from app.modules.matching.models import SelectionVersion

    with SessionLocal() as db:
        assert seed(db)["candidates"] >= 500
    emp = _login(client, "employer")
    code = _room(client, emp["access_token"])["code"]
    places = {}
    for direction in ("backend", "frontend"):
        r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": direction}).json()
        gt, me = r["token"], r["guest"]
        for _ in range(3):
            me = _answer(client, code, gt, me["item"], correct=True)
        sel = me["selection"]
        # приглашение — по правилу экрана: каждому, кому мини-тест дал экспресс-категорию
        assert me["stage"] == "invited" and me["invite"] and me["invite"]["salary_from"] > 0, (direction, me["stage"])
        assert isinstance(sel["rank"], int) and 1 <= sel["rank"] <= sel["total"] and sel["total"] > S.SELECTION_LIMIT
        assert f"{sel['rank']}-м месте из {sel['total']}" in me["invite"]["offer_description"]
        places[direction] = sel["rank"]
    # хотя бы у одного направления место за пределами окна подборки — на этом и падало (С-1)
    assert max(places.values()) > S.SELECTION_LIMIT, places
    feed = client.get("/api/jury/live/room/feed", headers=H(emp["access_token"])).json()
    assert feed["counters"]["invited"] == 2
    for g in feed["guests"]:
        top = g["selection"]["top"]
        own = [t for t in top if t["is_self"]]
        assert len(own) == 1 and own[0]["rank"] == g["selection"]["rank"]  # свой ряд на экране зала — с настоящим местом
        assert "-м месте из —" not in str(g)
    texts = [e["text"] for e in feed["events"] if e["kind"] == "selected"]
    assert texts and all("место" in t and "None" not in t and " -м" not in t for t in texts)
    # сохранённая версия подборки содержит гостя со своим местом, а не только первые 60
    with SessionLocal() as db:
        guests = db.scalars(select(LiveGuest)).all()
        for g in guests:
            v = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == uuid.UUID(g.selection["need_id"]),
                                                         SelectionVersion.version == g.selection["version"]))
            row = next(x for x in v.results if x["ref"] == g.ref)
            assert row["rank"] == g.selection["rank"]
            assert len(v.results) <= S.SELECTION_LIMIT + 1


def test_qr_guest_invited_even_when_rank_unknown(client, _fast_live, monkeypatch):
    """Если места нет вовсе (гостя нет в выдаче), приглашение всё равно уходит, а текст — без «на -м месте»."""
    from app.modules.matching import ranking

    real = ranking.build_selection

    def without_guest(db, req, filters, limit=30, include_refs=()):
        out = real(db, req, filters, limit=limit)
        out["results"] = out["results"][:limit]
        return out

    monkeypatch.setattr(ranking, "build_selection", without_guest)
    emp = _login(client, "employer")
    code = _room(client, emp["access_token"])["code"]
    monkeypatch.setattr("app.jury_live.service.SELECTION_LIMIT", 0)
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "qa"}).json()
    gt, me = r["token"], r["guest"]
    for _ in range(3):
        me = _answer(client, code, gt, me["item"], correct=True)
    assert me["stage"] == "invited" and me["invite"]
    assert me["selection"]["rank"] is None
    assert "м месте" not in me["invite"]["offer_description"] and "пересчиталась." in me["invite"]["offer_description"]
    feed = client.get("/api/jury/live/room/feed", headers=H(emp["access_token"])).json()
    assert feed["counters"]["invited"] == 1
    assert all("-м" not in e["text"] and "None" not in e["text"] for e in feed["events"])
