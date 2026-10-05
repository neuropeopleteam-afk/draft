"""Кабинет ФСП: доступ только роли «ФСП»/администратора, только агрегаты (K = 5), демо-данные и демо-кубки."""
import json

from sqlalchemy import select

from app.core.db import SessionLocal
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
        assert len(cups) == 5 and {c.status for c in cups} == {"finished", "active"}
        placed = db.scalars(select(CupEntry).where(CupEntry.place.is_not(None))).all()
        assert placed and all(e.passport_status in ("written", "pending_link") for e in placed)
        assert any(e.passport_status == "written" for e in placed)
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    flat = json.dumps(rep, ensure_ascii=False)
    assert "@demo.invalid" not in flat and "CND-" not in flat
    ov = rep["overview"]
    assert ov["candidates"] >= 150 and ov["invitations"] >= 100 and ov["cups"] == 5
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
    assert len(rep["cups"]) == 5 and all("participants" in c for c in rep["cups"])
    # демо-кубки видны демо-кандидатам своей категории; удаление демо — чистое
    with SessionLocal() as db:
        from app.cup import demo as cup_demo

        assert cup_demo.delete_cups(db) == 5 and demo.delete_invitations(db) >= 100
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
