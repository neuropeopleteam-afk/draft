"""И7 «Задания работодателя с автопроверкой»: сборка по стеку потребности/вакансии, зонд кандидату, задание к
вакансии при отклике, лента «Задания для вас» раз в N дней с push, факты T1 по навыкам в подборке и «почему»,
ключи не уходят на клиент, вилка обязательна, песочница жюри."""
from datetime import timedelta
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from tests.test_day2_rules import H, candidate_with_category, employer, my_ref

NEED = ("Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
        "Будет плюсом Kafka. Удалённо, 220–300 тыс.")
VACANCY = {"title": "Python-разработчик (платежи)", "category_id": "backend.middle", "stack": ["python", "postgresql", "redis"],
           "description": "Платёжное ядро: FastAPI, PostgreSQL, Redis. Удалённо, гибкий график, команда 6 человек.",
           "salary_from": 230000, "salary_to": 290000, "work_format": "remote", "publish": True}
SECRETS = ("\"key\"", "\"seed\"", "family_id", "\"accept\"")


def keys_of(attempt_id: str) -> dict:
    from app.modules.assignments.models import AssignmentAttempt

    with SessionLocal() as db:
        at = db.get(AssignmentAttempt, uuid.UUID(attempt_id))
        return {it["token"]: it["key"]["value"] for it in at.tasks}


def wrong(task: dict, key):
    if task["kind"] == "option":
        return next(o["id"] for o in task["options"] if o["id"] != key)
    if task["kind"] == "line":
        return int(key) % max(2, task["code_lines"]) + 1
    return "заведомо неверный вывод"


def solve(client, t, attempt_id: str, n_correct: int) -> dict:
    r = client.post(f"/api/candidate/assignments/{attempt_id}/start", headers=H(t))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_progress" and body["deadline_at"]
    tasks = body["tasks"]
    assert len(tasks) == body["assignment"]["n_tasks"]
    assert tasks and not any(s in r.text for s in SECRETS), "ключи и семейства не должны уходить на клиент"
    keys = keys_of(attempt_id)
    ans = {x["token"]: (keys[x["token"]] if i < n_correct else wrong(x, keys[x["token"]])) for i, x in enumerate(tasks)}
    r = client.post(f"/api/candidate/assignments/{attempt_id}/submit", json={"answers": ans}, headers=H(t))
    assert r.status_code == 200, r.text
    return r.json()


def make_need(client, te) -> dict:
    r = client.post("/api/employer/needs", json={"text": NEED}, headers=H(te))
    assert r.status_code == 201, r.text
    return r.json()


def facts_of(email: str, origin: str = "assignment") -> list:
    from app.modules.auth.models import User
    from app.modules.profiles.models import CandidateFact

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        return [(f.kind, f.key, dict(f.value)) for f in db.scalars(select(CandidateFact).where(CandidateFact.user_id == u.id)).all()
                if (f.value or {}).get("origin") == origin]


# ------------------------------------------------------------------ 1–2: задание по требованиям → зонд кандидату

def test_preview_by_need_and_probe_full_flow(client):
    from app.integrations.push.service import SENT_LOG

    te = employer(client)
    need = make_need(client, te)
    pv = client.post("/api/employer/assignments/preview", json={"need_id": need["id"], "n_tasks": 5}, headers=H(te))
    assert pv.status_code == 200, pv.text
    pv = pv.json()
    assert pv["direction"] == "backend" and pv["grade"] == "middle" and 3 <= len(pv["families"]) <= 5
    assert {"python", "fastapi", "postgresql", "redis"} <= set(pv["stack"])
    # честно: покрытие и «чего в банке нет» — разбиение стека без потерь (после синхронизации банка 164 семейства
    # kafka уже покрыт — состав missing не фиксируем)
    cov = pv["coverage"]
    assert "python" in cov["covered"] and not (set(cov["covered"]) & set(cov["missing"]))
    assert set(cov["covered"]) | set(cov["missing"]) == set(pv["stack"])
    assert all("family_id" not in f for f in pv["families"]) and all(f["tags"] for f in pv["families"])
    covered_by_tasks = {t for f in pv["families"] for t in f["tags"]}
    assert {"python", "redis"} <= covered_by_tasks

    t = candidate_with_category(client, "a@example.com")
    ref = my_ref(client, t)
    # без вилки — нельзя (зонд — предложение работодателя)
    bad = client.post("/api/employer/assignments", json={"need_id": need["id"], "mode": "probe", "candidate_refs": [ref],
                                                         "salary_from": 0, "salary_to": 0}, headers=H(te))
    assert bad.status_code == 422
    r = client.post("/api/employer/assignments", json={"need_id": need["id"], "mode": "probe", "candidate_refs": [ref],
                                                       "salary_from": 230000, "salary_to": 300000}, headers=H(te))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["sent"] == 1 and a["n_tasks"] == 5 and a["mode"] == "probe" and a["title"].startswith("Задание по требованиям")
    assert not any(s in r.text for s in SECRETS)
    assert SENT_LOG and SENT_LOG[-1]["url"].startswith("/candidate/assignments/")

    mine = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert len(mine["items"]) == 1 and mine["items"][0]["status"] == "offered" and mine["items"][0]["source"] == "probe"
    atid = mine["items"][0]["attempt_id"]
    detail = client.get(f"/api/candidate/assignments/{atid}", headers=H(t)).json()
    assert detail["tasks"] is None and detail["assignment"]["company"]["name"] == "ООО Ромашка"
    # отправить до старта нельзя
    assert client.post(f"/api/candidate/assignments/{atid}/submit", json={"answers": {}}, headers=H(t)).status_code == 409

    res = solve(client, t, atid, 4)
    assert res["status"] == "scored" and res["correct"] == 4 and res["total"] == 5 and res["score_pct"] == 80
    assert [x["correct"] for x in res["tasks"]].count(True) == 4 and not any(s in str(res) for s in SECRETS)
    assert res["skills"] and all(set(s) >= {"tag", "title", "correct", "total", "score"} for s in res["skills"])

    # факты T1: по навыкам и общий (kind=probe) — в карточке и в подборке
    facts = facts_of("a@example.com")
    kinds = {k for k, _, _ in facts}
    assert kinds == {"skill", "probe"} and any(key == "python" for k, key, _ in facts if k == "skill")
    probe_fact = next(v for k, _, v in facts if k == "probe")
    assert probe_fact["score"] == 0.8 and "4 из 5" in probe_fact["verdict"]

    emp = client.get(f"/api/employer/assignments/{a['id']}", headers=H(te)).json()
    assert emp["attempts_total"] == 1 and emp["attempts"][0]["candidate_ref"] == ref
    assert emp["attempts"][0]["score_pct"] == 80 and emp["attempts"][0]["status"] == "scored"
    assert not any(s in str(emp) for s in SECRETS)
    lst = client.get("/api/employer/assignments", headers=H(te)).json()
    assert [x["id"] for x in lst] == [a["id"]] and lst[0]["attempts_by_status"] == {"scored": 1}

    # подборка по потребности: причина «почему» упоминает задание работодателя, зонд виден в карточке
    sel = client.post(f"/api/employer/needs/{need['id']}/selections", json={"parent_version": 1, "filters": {}}, headers=H(te))
    assert sel.status_code in (200, 201), sel.text
    row = next(x for x in sel.json()["results"] if x["ref"] == ref)
    texts = " ".join(r["text"] for r in row["reasons"])
    assert "заданием работодателя" in texts, texts
    assert any(p["title"].startswith("Задание работодателя") for p in row["card"]["probes"])
    # повторно отправить тому же кандидату — нельзя (одна попытка на задание)
    again = client.post(f"/api/employer/assignments/{a['id']}/send", json={"candidate_refs": [ref]}, headers=H(te)).json()
    assert again["sent"] == 0 and again["attempts_total"] == 1


def test_evidence_in_invitation_includes_assignment(client):
    from app.modules.auth.models import User
    from app.modules.invitations.service import build_evidence
    from app.modules.profiles.models import Company

    te = employer(client)
    need = make_need(client, te)
    t = candidate_with_category(client, "b@example.com")
    ref = my_ref(client, t)
    a = client.post("/api/employer/assignments", json={"need_id": need["id"], "mode": "probe", "candidate_refs": [ref],
                                                       "salary_from": 230000, "salary_to": 300000}, headers=H(te)).json()
    atid = client.get("/api/candidate/assignments", headers=H(t)).json()["items"][0]["attempt_id"]
    solve(client, t, atid, 5)
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "b@example.com"))
        c = db.scalar(select(Company).where(Company.name == "ООО Ромашка"))
        ev = build_evidence(db, u.id, c.id, None)
    assert any(e["kind"] == "assignment" and "5 из 5" in e["text"] for e in ev), ev
    assert any(e["kind"] == "skill" and "заданием работодателя" in e["text"] for e in ev), ev
    assert a["status"] == "active"


# ------------------------------------------------------------------ 3: задание к вакансии

def test_vacancy_assignment_on_apply(client):
    te = employer(client)
    v = client.post("/api/employer/vacancies", json=VACANCY, headers=H(te))
    assert v.status_code == 201, v.text
    v = v.json()
    r = client.post("/api/employer/assignments", json={"vacancy_id": v["id"], "mode": "vacancy", "n_tasks": 4}, headers=H(te))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["vacancy_id"] == v["id"] and a["salary_from"] == 230000 and a["n_tasks"] == 4
    # второе активное задание к той же вакансии — нельзя
    assert client.post("/api/employer/assignments", json={"vacancy_id": v["id"], "mode": "vacancy"}, headers=H(te)).status_code == 409

    t = candidate_with_category(client, "c@example.com")
    pub = client.get(f"/api/vacancies/{v['id']}", headers=H(t)).json()
    assert pub["assignment"]["title"].startswith("Задание к вакансии") and pub["assignment"]["n_tasks"] == 4
    app = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(t))
    assert app.status_code in (200, 201), app.text
    app = app.json()
    assert app["assignment"]["status"] == "offered" and app["assignment"]["source"] == "vacancy"
    atid = app["assignment"]["attempt_id"]
    mine = client.get("/api/candidate/applications", headers=H(t)).json()
    assert mine[0]["assignment"]["attempt_id"] == atid
    res = solve(client, t, atid, 2)
    assert res["status"] == "scored" and res["correct"] == 2 and res["application_id"] == app["id"]

    apps = client.get(f"/api/employer/vacancies/{v['id']}/applications", headers=H(te)).json()
    assert apps[0]["assignment"]["score_pct"] == 50 and apps[0]["assignment"]["correct"] == 2
    assert apps[0]["assignment"]["skills"]
    emp = client.get(f"/api/employer/assignments/{a['id']}", headers=H(te)).json()
    assert emp["attempts"][0]["source"] == "vacancy" and emp["attempts"][0]["candidate_ref"] == my_ref(client, t)
    # после закрытия задания новые отклики задание не получают
    assert client.post(f"/api/employer/assignments/{a['id']}/close", headers=H(te)).json()["status"] == "closed"
    t2 = candidate_with_category(client, "d@example.com")
    app2 = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(t2)).json()
    assert app2["assignment"] is None


# ------------------------------------------------------------------ 4: лента «Задания для вас»

def test_open_assignment_feed_by_stack_and_interval(client, monkeypatch):
    from app.core.config import get_settings
    from app.integrations.push.service import SENT_LOG
    from app.modules.assignments import feed
    from app.modules.assignments.models import AssignmentAttempt

    te = employer(client)
    r = client.post("/api/employer/assignments", json={"mode": "open", "direction": "backend", "grade": "middle",
                                                       "stack": ["python", "postgresql"], "n_tasks": 3,
                                                       "title": "Открытое задание: Python и SQL",
                                                       "salary_from": 220000, "salary_to": 280000}, headers=H(te))
    assert r.status_code == 201, r.text
    a1 = r.json()
    # кандидату без категории лента пуста (сначала первичный тест)
    from tests.conftest import register_and_verify

    t0 = register_and_verify(client, email="nocat@example.com")
    f0 = client.get("/api/candidate/assignments", headers=H(t0)).json()
    assert f0["items"] == [] and f0["new_offer"] is None and f0["has_category"] is False

    SENT_LOG.clear()
    t = candidate_with_category(client, "e@example.com")  # backend.middle, стек python/postgresql/fastapi
    f1 = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert f1["new_offer"] and len(f1["items"]) == 1 and f1["items"][0]["source"] == "feed"
    assert f1["items"][0]["assignment"]["id"] == a1["id"] and f1["feed_days"] == 3
    assert any(p["title"].startswith("Задание для вас") for p in SENT_LOG), SENT_LOG
    # второе открытое задание есть, но повторное предложение — не раньше чем через N дней
    a2 = client.post("/api/employer/assignments", json={"mode": "open", "direction": "backend", "grade": "middle",
                                                        "stack": ["python"], "n_tasks": 3, "salary_from": 220000,
                                                        "salary_to": 280000}, headers=H(te)).json()
    f2 = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert f2["new_offer"] is None and len(f2["items"]) == 1
    atid = f1["items"][0]["attempt_id"]
    assert client.post(f"/api/candidate/assignments/{atid}/decline", headers=H(t)).json()["status"] == "declined"
    assert client.get("/api/candidate/assignments", headers=H(t)).json()["new_offer"] is None
    with SessionLocal() as db:
        at = db.get(AssignmentAttempt, uuid.UUID(atid))
        at.offered_at = utcnow() - timedelta(days=4)
        db.commit()
    # открытое задание другого направления (QA) кандидату backend не предлагается
    client.post("/api/employer/assignments", json={"mode": "open", "direction": "qa", "grade": "middle",
                                                   "stack": ["pytest", "python"], "n_tasks": 3, "salary_from": 200000,
                                                   "salary_to": 250000}, headers=H(te))
    f3 = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert f3["new_offer"] and {x["assignment"]["id"] for x in f3["items"]} == {a1["id"], a2["id"]}
    # отказ не создаёт фактов; решённое — создаёт
    assert facts_of("e@example.com") == []
    res = solve(client, t, f3["new_offer"], 3)
    assert res["status"] == "scored" and facts_of("e@example.com")
    with SessionLocal() as db:
        from app.modules.auth.models import User

        u = db.scalar(select(User).where(User.email == "e@example.com"))
        monkeypatch.setattr(get_settings(), "assignments_feed_days", 3)
        assert feed.due(db, u.id) is False  # только что предложено
        # фоновый обход: кандидат заходил недавно, но предложение ещё не «созрело» — 0 новых
        assert feed.run_once(db) == 0


def test_feed_run_once_offers_recent_logins(client):
    from app.modules.assignments import feed
    from app.modules.auth.models import User

    te = employer(client)
    client.post("/api/employer/assignments", json={"mode": "open", "direction": "backend", "grade": "middle",
                                                   "stack": ["python"], "n_tasks": 3, "salary_from": 220000,
                                                   "salary_to": 280000}, headers=H(te))
    candidate_with_category(client, "g@example.com")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "g@example.com"))
        u.last_login_at = utcnow()
        db.commit()
        assert feed.run_once(db) == 1
        assert feed.run_once(db) == 0
        u.last_login_at = utcnow() - timedelta(days=60)
        db.commit()


# ------------------------------------------------------------------ правила и слияние фактов

def test_salary_and_category_rules(client):
    te = employer(client)
    # открытое задание: вилка «до» не шире 1,5 «от»
    r = client.post("/api/employer/assignments", json={"mode": "open", "direction": "backend", "grade": "middle",
                                                       "stack": ["python"], "salary_from": 100000, "salary_to": 200000}, headers=H(te))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "salary_range_too_wide"
    # без категории — нельзя собрать
    r = client.post("/api/employer/assignments/preview", json={"stack": ["python"]}, headers=H(te))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "category_required"
    # зонд без кандидатов
    r = client.post("/api/employer/assignments", json={"mode": "probe", "direction": "backend", "grade": "middle",
                                                       "stack": ["python"], "salary_from": 200000, "salary_to": 250000}, headers=H(te))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "candidates_required"
    # чужая потребность
    r = client.post("/api/employer/assignments/preview", json={"need_id": str(uuid.uuid4())}, headers=H(te))
    assert r.status_code == 404


def test_expired_attempt_gives_no_facts(client):
    from app.modules.assignments.models import AssignmentAttempt

    te = employer(client)
    t = candidate_with_category(client, "h@example.com")
    ref = my_ref(client, t)
    client.post("/api/employer/assignments", json={"mode": "probe", "direction": "backend", "grade": "middle",
                                                   "stack": ["python"], "candidate_refs": [ref], "salary_from": 200000,
                                                   "salary_to": 250000}, headers=H(te))
    atid = client.get("/api/candidate/assignments", headers=H(t)).json()["items"][0]["attempt_id"]
    assert client.post(f"/api/candidate/assignments/{atid}/start", headers=H(t)).status_code == 200
    with SessionLocal() as db:
        at = db.get(AssignmentAttempt, uuid.UUID(atid))
        at.deadline_at = utcnow() - timedelta(minutes=10)
        db.commit()
    r = client.post(f"/api/candidate/assignments/{atid}/submit", json={"answers": {}}, headers=H(t)).json()
    assert r["status"] == "expired" and r["score"] is None and facts_of("h@example.com") == []


def test_merge_skill_facts_unit():
    from app.core.enums import EvidenceLevel, FactSource
    from app.modules.profiles.facts import merge_skill, skill_confirmed, skill_evidence_text
    from app.modules.profiles.models import CandidateFact

    uid = uuid.uuid4()
    test = CandidateFact(user_id=uid, kind="skill", key="python", title="Python", value={"score": 0.3333, "correct": 1, "total": 3},
                         evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref="test_session:x")
    asg = CandidateFact(user_id=uid, kind="skill", key="python", title="Python",
                        value={"score": 1.0, "correct": 3, "total": 3, "origin": "assignment"},
                        evidence_level=EvidenceLevel.T1, source=FactSource.probe, source_ref="assignment:y")
    assert skill_evidence_text(test) == "Подтверждено заданиями теста: 1 из 3"
    assert skill_evidence_text(asg) == "Подтверждено заданием работодателя: 3 из 3"
    m = merge_skill(test, asg)
    assert m.value["correct"] == 4 and m.value["total"] == 6 and m.value["score"] == pytest.approx(0.6667)
    assert not skill_confirmed(test) and skill_confirmed(m)
    assert skill_evidence_text(m) == "Подтверждено заданиями теста (1 из 3) и заданием работодателя (3 из 3)"
    m2 = merge_skill(m, asg)  # ещё одно задание — суммируется в ту же часть
    assert m2.value["parts"]["assignment"] == {"correct": 6.0, "total": 6.0} and m2.value["total"] == 9


# ------------------------------------------------------------------ песочница жюри

def test_jury_sandbox_has_assignments(client):
    from app.modules.assignments.models import Assignment, AssignmentAttempt
    from app.modules.jury import scope

    r = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
    assert r.status_code == 200, r.text
    te = r.json()["access_token"]
    lst = client.get("/api/employer/assignments", headers=H(te)).json()
    assert {x["mode"] for x in lst} == {"probe", "vacancy", "open"}
    probe = next(x for x in lst if x["mode"] == "probe")
    assert probe["attempts_by_status"] == {"scored": 1}
    det = client.get(f"/api/employer/assignments/{probe['id']}", headers=H(te)).json()
    assert det["attempts"][0]["correct"] == 4 and det["attempts"][0]["total"] == 5
    vac = next(x for x in lst if x["mode"] == "vacancy")
    apps = client.get(f"/api/employer/vacancies/{vac['vacancy_id']}/applications", headers=H(te)).json()
    assert apps and apps[0]["assignment"]["status"] == "offered"
    # у Марии той же песочницы: зонд решён и открытое задание в ленте; задания видны только своей песочнице
    sid = scope.parse(client.get("/api/me", headers=H(te)).json()["email"])[1]
    rm = client.post("/api/jury/login", json={"persona": "candidate", "scenario": sid})
    assert rm.status_code == 200, rm.text
    tm = rm.json()["access_token"]
    mine = client.get("/api/candidate/assignments", headers=H(tm)).json()
    assert {x["source"]: x["status"] for x in mine["items"]} == {"probe": "scored", "feed": "offered"}
    with SessionLocal() as db:
        assert all(a.jury_scope == sid for a in db.scalars(select(Assignment)).all())
        assert db.scalar(select(AssignmentAttempt).where(AssignmentAttempt.source == "vacancy")) is not None
    # подборка v1 по потребности, из которой собрано задание, уже показывает факт T1 Марии (пересчитана в сиде)
    sel = client.get(f"/api/employer/needs/{probe['need_id']}/selections/1", headers=H(te)).json()
    maria = client.get("/api/me", headers=H(tm)).json()["candidate"]["public_ref"]
    row = next(x for x in sel["results"] if x["ref"] == maria)
    assert any(p["title"].startswith("Задание работодателя") for p in row["card"]["probes"])
    assert any("заданием работодателя" in r["text"] for r in row["reasons"]), [r["text"] for r in row["reasons"]]
