"""Кабинет ФСП: доступ только роли «ФСП»/администратора, только агрегаты (K = 5), демо-данные и демо-кубки."""
import json

from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref


def analyst_token(client) -> str:
    r = client.post("/api/fsp-cabinet/demo-login")
    assert r.status_code == 200, r.text
    assert r.json()["landing"] == "/fsp" and r.json()["user"]["role"] == "fsp_analyst"
    return r.json()["access_token"]


def test_access_by_role(client):
    tc = register_and_verify(client, email="c@example.com")
    te = employer(client)
    for t in (tc, te):
        assert client.get("/api/fsp-cabinet/report", headers=H(t)).status_code == 403
    assert client.get("/api/fsp-cabinet/report").status_code == 401
    ta = analyst_token(client)
    assert client.get("/api/fsp-cabinet/report", headers=H(ta)).status_code == 200
    # «ФСП» не работодатель и не кандидат
    assert client.get("/api/employer/candidates", headers=H(ta)).status_code == 403
    assert client.get("/api/candidate/cups", headers=H(ta)).status_code == 403
    me = client.get("/api/me", headers=H(ta))
    assert me.status_code == 200


def test_small_groups_suppressed_and_no_pii(client):
    te = employer(client)
    refs = []
    for i in range(3):
        t = candidate_with_category(client, f"c{i}@example.com")
        refs.append(my_ref(client, t))
    for ref in refs[:2]:
        assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref},
                           headers=H(te)).status_code == 201
    ta = analyst_token(client)
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    flat = json.dumps(rep, ensure_ascii=False)
    for secret in ("Иван", "Петров", "@example.com", "111-22-33", *refs):
        assert secret not in flat
    ov = rep["overview"]
    assert ov["candidates"] is None and ov["invited_candidates"] is None  # 3 и 2 человека — меньше 5
    row = next(r for r in rep["demand"]["categories"] if r["category_id"] == "backend.middle")
    assert row["invited_candidates"] is None and row["supply"] is None and row["invite_rate"] is None
    assert row["invitations"] == 2  # число приглашений-событий не идентифицирует человека
    sal = next(r for r in rep["salaries"]["categories"] if r["category_id"] == "backend.middle")
    assert sal["suppressed"] and "mid_median" not in sal
    empty = next(r for r in rep["demand"]["categories"] if r["category_id"] == "qa.senior")
    assert empty["supply"] == 0 and empty["invited_candidates"] == 0  # ноль раскрывать можно
    csv = client.get("/api/fsp-cabinet/export/demand.csv", headers=H(ta))
    assert csv.status_code == 200 and "<5" in csv.text and "@example.com" not in csv.text
    assert client.get("/api/fsp-cabinet/export/nope.csv", headers=H(ta)).status_code == 404


def test_k_rules_pure():
    from app.fsp_cabinet.analytics import K, kc, kr

    assert K == 5 and kc(0) == 0 and kc(4) is None and kc(5) == 5
    assert kr(3, 10) is None and kr(5, 10) == 0.5 and kr(0, 7) == 0.0 and kr(5, 4) is None


def test_demo_report_and_cups(client):
    from app.cup.models import Cup, CupEntry
    from app.fsp_cabinet import demo
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        db.commit()
    ta = analyst_token(client)  # демо-вход сам готовит историю приглашений и демо-кубки
    with SessionLocal() as db:
        assert demo.has_demo_invitations(db)
        cups = db.scalars(select(Cup)).all()
        assert len(cups) == 6 and {c.status for c in cups} == {"finished", "active"}
        placed = db.scalars(select(CupEntry).where(CupEntry.place.is_not(None))).all()
        assert placed and all(e.passport_status in ("written", "pending_link") for e in placed)
        assert any(e.passport_status == "written" for e in placed)
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    flat = json.dumps(rep, ensure_ascii=False)
    assert "@demo.invalid" not in flat and "CND-" not in flat
    ov = rep["overview"]
    assert ov["candidates"] >= 150 and ov["invitations"] >= 100 and ov["cups"] == 6
    shown = [r for r in rep["salaries"]["categories"] if not r["suppressed"]]
    hidden = [r for r in rep["salaries"]["categories"] if r["suppressed"]]
    assert shown and hidden  # в части категорий офферов мало — вилки скрыты
    for r in shown:
        assert r["offers"] >= 5 and r["companies"] >= 2 and r["from_p25"] <= r["mid_median"] <= r["to_p75"]
    fe = rep["fsp_effect"]
    assert fe["groups"][0]["key"] == "no_fsp" and fe["groups"][0]["candidates"] >= 5
    for part in ("ranks", "results", "levels"):  # вторичное подавление: не бывает ровно одной скрытой группы
        assert sum(1 for g in fe[part] if g["candidates"] is None) != 1
    f = rep["funnel"]
    assert [s["key"] for s in f["cups"]] == ["joined", "placed", "invited", "accepted"]
    assert f["all"][0]["count"] >= 150 and f["all"][1]["conversion"] is not None
    assert len(rep["cups"]) == 6 and all("participants" in c for c in rep["cups"])
    assert all(s["count"] is not None for s in f["cups"])  # воронка кубков раскрыта целиком (каждый этап ≥ 5)
    # демо-кубки видны демо-кандидатам своей категории; удаление демо — чистое
    with SessionLocal() as db:
        from app.cup import demo as cup_demo

        assert cup_demo.delete_cups(db) == 6 and demo.delete_invitations(db) >= 100
        assert db.scalars(select(Cup)).all() == []


def test_jury_employer_gets_review_cup(client):
    from app.modules.demo.seed import seed
    from app.modules.jury.seed import EMAILS

    with SessionLocal() as db:
        seed(db)
        db.commit()
    r = client.post("/api/jury/login", json={"persona": "employer"})
    assert r.status_code == 200, r.text
    te = r.json()["access_token"]
    assert EMAILS["employer"] == "employer@jury.example.com"
    cups = client.get("/api/employer/cups", headers=H(te)).json()
    assert len(cups) == 1 and cups[0]["phase"] == "judging" and cups[0]["to_review"] == 2
    cup = client.get(f"/api/employer/cups/{cups[0]['id']}", headers=H(te)).json()
    todo = [s for s in cup["solutions"] if s["status"] == "submitted"]
    assert len(todo) == 2
    for s in todo:
        r = client.post(f"/api/employer/cups/{cup['id']}/entries/{s['entry_id']}/score",
                        json={"criteria": {"correctness": 1, "tradeoffs": 0.5, "clarity": 1}}, headers=H(te))
        assert r.status_code == 200, r.text
    res = r.json()  # последняя оценка — итоги подведены автоматически (срок кубка вышел)
    assert res["phase"] == "finished" and res["summary"]["invited"] >= 1
    assert len(client.get("/api/employer/cups", headers=H(te)).json()) == 1  # повторно не создаётся


# ---------------------------------------------------------------- режим жюри: персона «ФСП», сброс, свежесть демо
def _ideas_state(db):
    from app.cup.models import Cup, CupEntry
    from app.cup.service import phase
    from app.modules.auth.models import User
    from app.modules.fsp.models import FspAchievement
    from app.modules.invitations.models import Invitation
    from app.modules.jury.seed import EMAILS
    from app.modules.profiles.models import CandidateFact

    cups = db.scalars(select(Cup)).all()
    ids = {f"cup:{c.id}" for c in cups}
    facts = db.scalars(select(CandidateFact.source_ref).where(CandidateFact.source_ref.like("cup:%"))).all()
    ach = db.scalars(select(FspAchievement.source_ref).where(FspAchievement.source_ref.like("cup:%"))).all()
    maria = db.scalar(select(User).where(User.email == EMAILS["candidate"]))
    me = db.scalars(select(CupEntry).where(CupEntry.candidate_user_id == maria.id)).all() if maria else []
    inv = [db.get(Invitation, e.invitation_id) for e in me if e.invitation_id]
    return {"phases": sorted(phase(c) for c in cups), "facts": len(facts), "orphans": set(facts + ach) - ids,
            "maria": [(e.place, e.passport_status) for e in me], "maria_inv": [i.status.value for i in inv if i]}


def test_jury_fsp_persona_and_reset_recreates_cups(client, monkeypatch):
    from app.cup.models import Cup
    from app.modules.demo.seed import seed
    from app.modules.jury import router as jr

    with SessionLocal() as db:
        seed(db)
        db.commit()
    st = client.get("/api/jury/status").json()
    assert any(p["id"] == "fsp" and p["role"] == "fsp_analyst" for p in st["personas"])
    r = client.post("/api/jury/login", json={"persona": "fsp"})
    assert r.status_code == 200, r.text
    assert r.json()["landing"] == "/fsp" and r.json()["user"]["role"] == "fsp_analyst"
    ta = r.json()["access_token"]
    with SessionLocal() as db:
        s1 = _ideas_state(db)
    # 3 завершены, 2 идут, 1 скоро; Мария — с местом в завершённом кубке, запись в паспорте, приглашение ждёт ответа
    assert s1["phases"] == ["active", "active", "finished", "finished", "finished", "upcoming"]
    assert s1["maria"] and s1["maria"][0][0] is not None and s1["maria"][0][1] == "written"
    assert s1["maria_inv"] == ["sent"] and not s1["orphans"]
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    assert rep["overview"]["invitations"] >= 100 and rep["overview"]["cups"] == 6
    # работодатель жюри получает свой кубок «на оценке»; после сброса он и его факты T1 исчезают, демо — как было
    te = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]
    cups = client.get("/api/employer/cups", headers=H(te)).json()
    assert len(cups) == 1 and cups[0]["to_review"] == 2
    cup = client.get(f"/api/employer/cups/{cups[0]['id']}", headers=H(te)).json()
    for s in [x for x in cup["solutions"] if x["status"] == "submitted"]:
        client.post(f"/api/employer/cups/{cup['id']}/entries/{s['entry_id']}/score",
                    json={"criteria": {"correctness": 1, "tradeoffs": 1, "clarity": 1}}, headers=H(te))
    with SessionLocal() as db:
        assert _ideas_state(db)["facts"] > s1["facts"]  # итоги кубка жюри — факты T1 у демо-кандидатов
    for _ in range(2):
        monkeypatch.setitem(jr._state, "last_reset", 0.0)
        r = client.post("/api/jury/reset")
        assert r.status_code == 200 and r.json()["deleted_users"] == 5, r.text
        assert len(r.json()["ideas"]["cups"]) == 6
        with SessionLocal() as db:
            s2 = _ideas_state(db)
            assert s2["phases"] == s1["phases"] and s2["facts"] == s1["facts"] and not s2["orphans"]
            assert s2["maria_inv"] == ["sent"] and len(db.scalars(select(Cup)).all()) == 6
    ta = client.post("/api/jury/login", json={"persona": "fsp"}).json()["access_token"]
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    assert rep["overview"]["invitations"] >= 100 and rep["overview"]["cups"] == 6
    assert all(s["count"] is not None for s in rep["funnel"]["cups"])
    te = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]
    assert client.get("/api/employer/cups", headers=H(te)).json()[0]["to_review"] == 2  # кубок жюри — заново


def test_stale_demo_cups_reseeded_on_jury_login(client):
    from datetime import timedelta

    from app.cup import demo as cup_demo
    from app.cup.models import Cup
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        db.commit()
    assert client.post("/api/jury/login", json={"persona": "candidate"}).status_code == 200
    with SessionLocal() as db:
        assert not cup_demo.is_stale(db)
        cup = db.scalar(select(Cup).where(Cup.title == "Маршрутизация заказов"))
        old = cup.id
        cup.ends_at = utcnow() + timedelta(hours=2)  # идущий кубок вот-вот закончится
        db.commit()
        assert cup_demo.is_stale(db)
    tc = client.post("/api/jury/login", json={"persona": "candidate"}).json()["access_token"]
    with SessionLocal() as db:
        assert not cup_demo.is_stale(db)
        cup = db.scalar(select(Cup).where(Cup.title == "Маршрутизация заказов"))
        assert cup.id != old and len(db.scalars(select(Cup)).all()) == 6
    items = client.get("/api/candidate/cups", headers=H(tc)).json()["items"]
    titles = {c["title"]: c for c in items}
    assert titles["Маршрутизация заказов"]["phase"] == "active" and titles["Маршрутизация заказов"]["my_status"] is None
    assert titles["Надёжные платежи"]["my_place"] is not None
    pas = client.get("/api/candidate/cups/passport", headers=H(tc)).json()
    assert pas and pas[0]["passport_status"] == "written" and pas[0]["invited"]
