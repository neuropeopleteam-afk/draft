"""К5 «Адресные задания»: причина предложения («почему вам»), рубрика с оценкой работодателя, свежесть профиля,
периодичность/лимит/напоминания ленты, сигнал в подборке без изменения порядка match-v1, демо-песочница, миграция."""
from datetime import timedelta
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from tests.test_assignments import NEED, facts_of, keys_of, make_need, solve, wrong
from tests.test_day2_rules import H, candidate_with_category, employer, my_ref

EMAIL = "e@example.com"
OPEN = {"mode": "open", "direction": "backend", "grade": "middle", "n_tasks": 3, "salary_from": 220000, "salary_to": 280000}


def uid(db, email=EMAIL):
    from app.modules.auth.models import User

    return db.scalar(select(User).where(User.email == email)).id


def open_assignment(client, te, stack, **extra) -> dict:
    r = client.post("/api/employer/assignments", json={**OPEN, "stack": stack, **extra}, headers=H(te))
    assert r.status_code == 201, r.text
    return r.json()


def set_skill(email, tag, *, score=None, days=None):
    """Подправить факт навыка кандидата (слабый результат / давняя дата подтверждения)."""
    from app.modules.profiles.models import CandidateFact

    with SessionLocal() as db:
        u = uid(db, email)
        fs = db.scalars(select(CandidateFact).where(CandidateFact.user_id == u, CandidateFact.kind == "skill",
                                                    CandidateFact.key == tag)).all()
        assert fs, tag
        for f in fs:
            v = dict(f.value)
            if score is not None:
                v["score"], v["correct"] = score, score * (v.get("total") or 1)
            f.value = v
            if days is not None:
                f.created_at = utcnow() - timedelta(days=days)
        db.commit()


def solve_with(client, t, attempt_id, n_correct, approach=None, expect=200):
    body = client.post(f"/api/candidate/assignments/{attempt_id}/start", headers=H(t)).json()
    keys = keys_of(attempt_id)
    ans = {x["token"]: (keys[x["token"]] if i < n_correct else wrong(x, keys[x["token"]])) for i, x in enumerate(body["tasks"])}
    r = client.post(f"/api/candidate/assignments/{attempt_id}/submit", json={"answers": ans, "approach": approach}, headers=H(t))
    assert r.status_code == expect, r.text
    return r.json()


def send_probe(client, te, t, need, with_approach=True, n=4):
    r = client.post("/api/employer/assignments", json={"mode": "probe", "need_id": need["id"], "n_tasks": n, "with_approach": with_approach,
                                                       "candidate_refs": [my_ref(client, t)], "salary_from": 220000,
                                                       "salary_to": 300000}, headers=H(te))
    assert r.status_code == 201, r.text
    atid = next(x["attempt_id"] for x in client.get("/api/candidate/assignments", headers=H(t)).json()["items"]
                if x["assignment_id"] == r.json()["id"])
    return r.json(), atid


APPROACH = ("Сначала разберу требования и ограничения, потом опишу схему данных и обработчик с идемпотентным ключом. "
            "Риск — повторная доставка: закрою уникальным индексом и проверю тестом на дубли.")


# ------------------------------------------------------------------ 2: «почему вам»

def test_why_reasons_weak_stale_declared_and_weights(client):
    from app.modules.assignments import why
    from app.modules.assignments.models import Assignment

    te = employer(client)
    candidate_with_category(client, EMAIL)  # тест подтвердил python/postgresql/sql/http/asyncio; fastapi только заявлен
    set_skill(EMAIL, "python", score=0.2)  # слабо
    set_skill(EMAIL, "postgresql", days=200)  # давно (больше 180 дней)
    set_skill(EMAIL, "sql", days=120)  # стареет
    a = open_assignment(client, te, ["python", "postgresql", "sql", "fastapi", "docker"])
    with SessionLocal() as db:
        asg = db.get(Assignment, uuid.UUID(a["id"]))
        an = why.analyse(db, asg, uid(db))
        kinds = {r["tag"]: r for r in an["rows"]}
        assert kinds["python"]["kind"] == "weak_skill" and kinds["python"]["weight"] == 1.0
        assert kinds["postgresql"]["kind"] == "stale_skill" and kinds["postgresql"]["weight"] == 0.9
        assert kinds["sql"]["kind"] == "stale_skill" and kinds["sql"]["weight"] == 0.6
        assert kinds["fastapi"]["kind"] == "declared_only" and kinds["fastapi"]["weight"] == 0.5
        assert "docker" not in kinds  # нет ни заявленного, ни подтверждённого — причины нет
        from app.modules.auth.models import User

        w = why.build(db, asg, db.get(User, uid(db)), "feed", frequency_days=7)
    assert w["primary"]["kind"] == "weak_skill" and "Python" in w["primary"]["text"]
    cand = why.public(w, "candidate")
    emp = why.public(w, "employer")
    assert cand["visible_to"] == "кандидату и работодателю" and emp["visible_to"] == "вам и кандидату"
    assert emp["headline"][0].isupper() and "требует подтверждения" in emp["headline"]
    assert "слабо" in cand["headline"] and "слабо" not in emp["headline"]  # работодателю — нейтральная формулировка
    decl = next(x for x in cand["reasons"] if x["kind"] == "declared_only")
    assert "в опросе" in decl["text"]
    assert all("в опросе" not in x["text"] for x in emp["reasons"])  # заявленный стек остаётся приватным


def test_why_declared_only_hidden_from_employer_and_need_match(client):
    from app.modules.assignments import why
    from app.modules.assignments.models import Assignment
    from app.modules.auth.models import User

    te = employer(client)
    need = make_need(client, te)
    t = candidate_with_category(client, EMAIL)
    r = client.post("/api/employer/assignments", json={"mode": "probe", "need_id": need["id"], "n_tasks": 4,
                                                       "candidate_refs": [my_ref(client, t)],
                                                       "salary_from": 220000, "salary_to": 300000}, headers=H(te))
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        a = db.get(Assignment, uuid.UUID(r.json()["id"]))
        w = why.build(db, a, db.get(User, uid(db)), "probe")
    kinds = {x["kind"] for x in w["reasons"]}
    assert "need_match" in kinds and w["need"]["required_total"] >= 3
    assert all("в опросе" not in x["employer_text"] for x in w["reasons"])
    assert why.public(w, "employer")["context"] == "Вы отправили задание кандидату лично"


def test_pick_for_prefers_weak_over_fresh(client):
    from app.modules.assignments import feed
    from app.modules.auth.models import User

    te = employer(client)
    candidate_with_category(client, EMAIL)
    fresh = open_assignment(client, te, ["postgresql", "http"], title="Свежие навыки")
    set_skill(EMAIL, "sql", score=0.1)
    weak = open_assignment(client, te, ["sql", "python"], title="Слабый навык")
    with SessionLocal() as db:
        u = db.get(User, uid(db))
        ranked = feed.rank_for(db, u)
        assert [r[1].title for r in ranked][0] == "Слабый навык"
        assert ranked[0][0] > ranked[1][0]
        assert feed.pick_for(db, u).id == uuid.UUID(weak["id"])
    assert fresh["id"] != weak["id"]


# ------------------------------------------------------------------ 3: рубрика

def test_rubric_templates_sum_to_100_and_auto_points():
    from app.modules.assignments import rubric

    for with_approach in (False, True):
        r = rubric.build(with_approach)
        assert sum(c["max"] for c in r) == 100
        assert rubric.has_employer_part(r) is with_approach
    r = rubric.build(True)
    for c in (x for x in r if x["kind"] == "employer"):  # уровни — якоря баллов, максимум достижим
        assert c["levels"][0]["points"] == 0 and c["levels"][-1]["points"] == c["max"]
        assert all(lv["label"] for lv in c["levels"])


def test_rubric_preview_and_approach_review_flow(client):
    from app.integrations.push.service import SENT_LOG

    te = employer(client)
    need = make_need(client, te)
    pv = client.post("/api/employer/assignments/preview", json={"need_id": need["id"]}, headers=H(te)).json()
    assert sum(c["max"] for c in pv["rubric"]) == 100 and sum(c["max"] for c in pv["rubric_auto"]) == 100
    assert {c["kind"] for c in pv["rubric"]} == {"auto", "employer"} and "подойдёте" in pv["approach_prompt"]
    t = candidate_with_category(client, EMAIL)
    a, atid = send_probe(client, te, t, need)
    assert a["approach_prompt"] and len(a["rubric"]["criteria"]) == 4
    offer = client.get(f"/api/candidate/assignments/{atid}", headers=H(t)).json()
    assert offer["why"]["source"] == "probe" and offer["assignment"]["approach_prompt"]
    assert sum(c["max"] for c in offer["assignment"]["rubric"]["criteria"]) == 100  # рубрика видна кандидату до старта
    # без описания подхода отправить нельзя; запись не портится
    client.post(f"/api/candidate/assignments/{atid}/start", headers=H(t))
    assert client.post(f"/api/candidate/assignments/{atid}/submit", json={"answers": {}, "approach": "коротко"},
                       headers=H(t)).status_code == 422
    res = solve_with(client, t, atid, 3, approach=APPROACH + " Пишите мне на ivan.petrov@example.com или +7 900 123-45-67.")
    assert res["review_status"] == "pending" and res["final_points"] is None
    assert "ivan.petrov@example.com" not in (res["approach_text"] or "") and "123-45-67" not in (res["approach_text"] or "")
    rb = res["rubric"]
    assert rb["auto_max"] == 70 and rb["employer_max"] == 30 and rb["total"] is None
    assert 0 <= rb["auto_points"] <= 70 and rb["auto_points"] == sum(c["points"] for c in rb["criteria"] if c["kind"] == "auto")
    # до оценки: зонд = результат автопроверки, строка в подборке честно говорит «оценка ожидается»
    pf = [f for f in facts_of(EMAIL) if f[0] == "probe"][0][2]
    assert pf["score"] == pytest.approx(res["score"], abs=1e-3) and pf["reviewed"] is False
    # работодатель: в списке видно «ждут оценки», в попытке — подход и причина
    lst = client.get("/api/employer/assignments", headers=H(te)).json()
    assert lst[0]["to_review"] == 1
    det = client.get(f"/api/employer/assignments/{a['id']}", headers=H(te)).json()
    at0 = det["attempts"][0]
    assert at0["approach_text"] == res["approach_text"] and at0["review_status"] == "pending" and at0["why"]["source"] == "probe"
    # валидация оценки: только уровни из рубрики и все критерии
    rv = f"/api/employer/assignments/{a['id']}/attempts/{atid}/review"
    assert client.post(rv, json={"scores": {"approach": 12, "risks": 5}}, headers=H(te)).status_code == 422
    assert client.post(rv, json={"scores": {"approach": 15}}, headers=H(te)).status_code == 422
    assert client.post(rv, json={"scores": {"answers": 50, "approach": 20, "risks": 10}}, headers=H(te)).status_code == 422
    # чужой работодатель оценить не может
    other = employer(client, "other@corp.ru", "ООО Другая")
    assert client.post(rv, json={"scores": {"approach": 15, "risks": 10}}, headers=H(other)).status_code == 404
    SENT_LOG.clear()
    ok = client.post(rv, json={"scores": {"approach": 15, "risks": 5}, "comment": "Риски названы частично"}, headers=H(te))
    assert ok.status_code == 200, ok.text
    done = client.get(f"/api/candidate/assignments/{atid}", headers=H(t)).json()
    rb = done["rubric"]
    assert done["review_status"] == "reviewed" and done["final_points"] == rb["total"] == rb["auto_points"] + 20
    assert rb["employer_points"] == 20 and rb["comment"] == "Риски названы частично"
    assert any("оценил" in p["title"] for p in SENT_LOG)
    pf = [f for f in facts_of(EMAIL) if f[0] == "probe"][0][2]
    assert pf["reviewed"] is True and pf["score"] == pytest.approx(rb["total"] / 100, abs=1e-3)
    assert f"{rb['total']} из 100 по рубрике" in pf["verdict"] and "оценка работодателя 20 из 30" in pf["verdict"]
    # повторная оценка допустима (исправление) и не двигает дату подтверждения навыков
    from app.modules.profiles.models import CandidateFact

    def dates():
        with SessionLocal() as db:
            return sorted((f.key, f.created_at) for f in db.scalars(select(CandidateFact).where(
                CandidateFact.user_id == uid(db), CandidateFact.source_ref.like("assignment:%"))).all())

    d0 = dates()
    assert client.post(rv, json={"scores": {"approach": 20, "risks": 10}}, headers=H(te)).status_code == 200
    assert dates() == d0
    assert client.get("/api/employer/assignments", headers=H(te)).json()[0]["to_review"] == 0


def test_auto_only_assignment_has_no_employer_review(client):
    te = employer(client)
    t = candidate_with_category(client, EMAIL)
    a = open_assignment(client, te, ["python", "postgresql"])
    assert a["approach_prompt"] is None and [c["kind"] for c in a["rubric"]["criteria"]] == ["auto", "auto"]
    offer = client.get("/api/candidate/assignments", headers=H(t)).json()["new_offer"]
    res = solve(client, t, offer, 3)
    assert res["review_status"] == "none" and res["final_points"] == res["rubric"]["total"] == res["rubric"]["auto_points"]
    assert res["rubric"]["max"] == 100
    r = client.post(f"/api/employer/assignments/{a['id']}/attempts/{offer}/review", json={"scores": {"approach": 5}}, headers=H(te))
    assert r.status_code == 409


def test_old_assignment_without_rubric_shows_auto_rubric(client):
    from app.modules.assignments import rubric
    from app.modules.assignments.models import Assignment

    a = type("A", (), {"rubric": None})()
    assert [c["id"] for c in rubric.of(a)] == ["answers", "stack"]


# ------------------------------------------------------------------ 1,3: свежесть профиля и сигнал в подборке

def test_assignment_refreshes_skill_dates_and_freshness(client):
    from app.modules.profiles import freshness
    from app.modules.profiles.facts import load_bundles

    te = employer(client)
    t = candidate_with_category(client, EMAIL)
    for tag in ("python", "postgresql", "sql"):
        set_skill(EMAIL, tag, days=200)

    def summary():
        with SessionLocal() as db:
            b = load_bundles(db, [uid(db)], direction="backend")[uid(db)]
            return freshness.summary(b.skills_t1)

    before = summary()
    assert before["stale"] == 3 and before["fresh"] == 3 and before["level"] == "aging"  # остальные навыки теста — свежие
    a = open_assignment(client, te, ["python", "postgresql", "sql"])
    offer = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert offer["freshness"]["stale"] >= 3 and offer["schedule"]["pending"] is True
    solve(client, t, offer["new_offer"], 3)
    after = summary()
    assert after["fresh"] >= 6 and after["stale"] == 0 and after["aging"] == 0 and after["level"] == "fresh"
    assert client.get("/api/candidate/assignments", headers=H(t)).json()["freshness"]["fresh"] >= 3
    assert a["id"]


def test_freshness_levels_and_thresholds():
    from app.modules.profiles import freshness as fr

    assert (fr.state_of(90), fr.state_of(91), fr.state_of(180), fr.state_of(181)) == ("fresh", "aging", "aging", "stale")
    assert fr.summary({})["level"] == "none"
    assert fr.age_text(12) == "12 дн." and fr.age_text(130) == "около 4 мес."


def test_ranking_signal_present_and_order_unchanged(client, monkeypatch):
    from app.modules.assignments import signal
    from app.modules.matching import ranking

    te = employer(client)
    need = make_need(client, te)
    t = candidate_with_category(client, EMAIL)
    r, atid = send_probe(client, te, t, need)
    solve_with(client, t, atid, 4, approach=APPROACH)
    with SessionLocal() as db:
        from app.modules.matching.models import EmployerNeed

        req = db.get(EmployerNeed, uuid.UUID(need["id"])).requirements
        with_sig = ranking.build_selection(db, req, {})
        monkeypatch.setattr(signal, "reason_for", lambda probes: None)
        without = ranking.build_selection(db, req, {})
    mine = next(x for x in with_sig["results"] if x["reasons"] and any(y["requirement"] == "Адресное задание" for y in x["reasons"]))
    line = next(y for y in mine["reasons"] if y["requirement"] == "Адресное задание")
    assert line["level"] == "T1" and "оценка подхода работодателем ожидается" in line["text"]
    # порядок и скор match-v1 не зависят от строки-сигнала
    assert [(x["ref"], x["score"], x["rank"]) for x in with_sig["results"]] == [(x["ref"], x["score"], x["rank"]) for x in without["results"]]
    # карточка работодателя несёт свежесть (только подтверждённые навыки)
    assert mine["card"]["freshness"] is None or mine["card"]["freshness"]["n"] >= 1


# ------------------------------------------------------------------ 4: периодичность, лимит, напоминания

def test_schedule_prefs_limit_backoff(client, monkeypatch):
    from app.core.config import get_settings
    from app.modules.assignments import feed
    from app.modules.assignments.models import AssignmentAttempt
    from app.modules.auth.models import User

    te = employer(client)
    t = candidate_with_category(client, EMAIL)
    a = open_assignment(client, te, ["python", "postgresql"])
    assert feed.feed_days() == 7 and get_settings().assignments_feed_monthly_limit == 4
    r = client.put("/api/candidate/assignments/prefs", json={"frequency_days": 3}, headers=H(t))
    assert r.status_code == 422
    assert client.put("/api/candidate/assignments/prefs", json={"frequency_days": 0}, headers=H(t)).json()["paused"] is True
    f = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert f["new_offer"] is None and f["schedule"]["blocked"] == "paused"  # «не предлагать» соблюдается
    sch = client.put("/api/candidate/assignments/prefs", json={"frequency_days": 14}, headers=H(t)).json()
    assert sch["frequency_days"] == 14 and sch["due"] is True
    f = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert f["new_offer"] and f["schedule"]["next_at"] and f["schedule"]["used"] == 1 and f["schedule"]["blocked"] == "pending"
    extra = [open_assignment(client, te, ["python", "sql"], title=f"Ещё задание {i}") for i in range(3)]
    with SessionLocal() as db:
        u = db.get(User, uid(db))
        # два отказа/истечения подряд — интервал удваивается; лимит за 30 дней
        db.add_all([AssignmentAttempt(assignment_id=uuid.UUID(x["id"]), candidate_user_id=u.id, source="feed", status=s,
                                      offered_at=utcnow() - timedelta(days=d))
                    for x, (s, d) in zip(extra, (("declined", 20), ("expired", 10)))])
        for at in db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.candidate_user_id == u.id,
                                                             AssignmentAttempt.status == "offered")).all():
            at.status, at.offered_at = "declined", utcnow() - timedelta(days=15)
        db.commit()
        s = feed.schedule(db, u)
        assert s["backoff"] is True and s["effective_days"] == 28 and s["blocked"] == "wait"
        monkeypatch.setattr(get_settings(), "assignments_feed_monthly_limit", 1)
        db.add(AssignmentAttempt(assignment_id=uuid.UUID(extra[2]["id"]), candidate_user_id=u.id, source="feed", status="declined",
                                 offered_at=utcnow() - timedelta(days=2)))
        db.commit()
        s = feed.schedule(db, u)
        assert s["used"] >= 1 and s["limit"] == 1 and s["blocked"] in ("limit", "wait") and s["due"] is False


def test_offer_ttl_and_reminders(client):
    from app.integrations.push.service import SENT_LOG
    from app.modules.assignments import feed
    from app.modules.assignments.models import AssignmentAttempt

    te = employer(client)
    t = candidate_with_category(client, EMAIL)
    open_assignment(client, te, ["python", "postgresql"])
    atid = client.get("/api/candidate/assignments", headers=H(t)).json()["new_offer"]

    def shift(**kw):
        with SessionLocal() as db:
            at = db.get(AssignmentAttempt, uuid.UUID(atid))
            for k, days in kw.items():
                setattr(at, k, utcnow() - timedelta(days=days))
            db.commit()

    def run():
        with SessionLocal() as db:
            r = feed.maintenance(db)
            db.commit()
            at = db.get(AssignmentAttempt, uuid.UUID(atid))
            return r, at.remind_count, at.status

    SENT_LOG.clear()
    assert run()[0] == {"expired": 0, "reminded": 0, "review_reminded": 0}  # только что предложено
    shift(offered_at=3)
    r, n, st = run()
    assert r["reminded"] == 1 and n == 1 and st == "offered"
    assert any(p["title"].startswith("Напоминание") for p in SENT_LOG)
    assert run()[0]["reminded"] == 0  # повторный обход в тот же день не дублирует
    shift(offered_at=6, remind_at=3)
    assert run()[1] == 2
    shift(offered_at=9, remind_at=5)
    assert run()[1] == 2  # не больше двух напоминаний
    shift(offered_at=15)
    r, n, st = run()
    assert r["expired"] == 1 and st == "expired"
    lst = client.get("/api/candidate/assignments", headers=H(t)).json()
    assert lst["items"][0]["status_title"] == "Предложение истекло"


def test_review_reminder_to_employer(client):
    from app.integrations.push.service import SENT_LOG
    from app.modules.assignments import feed
    from app.modules.assignments.models import AssignmentAttempt

    te = employer(client)
    t = candidate_with_category(client, EMAIL)
    a = open_assignment(client, te, ["python", "postgresql"], with_approach=True)
    atid = client.get("/api/candidate/assignments", headers=H(t)).json()["new_offer"]
    solve_with(client, t, atid, 2, approach=APPROACH)
    SENT_LOG.clear()
    with SessionLocal() as db:
        assert feed.maintenance(db)["review_reminded"] == 0
        at = db.get(AssignmentAttempt, uuid.UUID(atid))
        at.submitted_at = utcnow() - timedelta(days=4)
        db.commit()
        assert feed.maintenance(db)["review_reminded"] == 1
        assert feed.maintenance(db)["review_reminded"] == 0
        db.commit()
    assert any("Оцените подход" in p["title"] for p in SENT_LOG)
    assert a["id"]


# ------------------------------------------------------------------ 1: песочница жюри, шаг «Смоделировать неделю»

def test_jury_sandbox_targeted_demo(client):
    r = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
    sid = r.json()["scenario"]
    te = r.json()["access_token"]
    lst = client.get("/api/employer/assignments", headers=H(te)).json()
    assert len(lst) == 4 and {x["mode"] for x in lst} == {"probe", "vacancy", "open"}
    probe = next(x for x in lst if x["mode"] == "probe")
    assert probe["to_review"] == 1 and probe["approach_prompt"]
    det = client.get(f"/api/employer/assignments/{probe['id']}", headers=H(te)).json()
    by = {x["review_status"]: x for x in det["attempts"]}
    assert set(by) == {"reviewed", "pending"}
    done = by["reviewed"]["rubric"]  # «до» — автопроверка, «после» — итог
    assert done["max"] == 100 and done["total"] == done["auto_points"] + done["employer_points"] and done["comment"]
    assert by["pending"]["approach_text"] and by["pending"]["why"]["headline"]
    tm = client.post("/api/jury/login", json={"persona": "candidate", "scenario": sid}).json()["access_token"]
    f = client.get("/api/candidate/assignments", headers=H(tm)).json()
    # «стареет» — навыки посеянного теста Марии (состарены на 130 дней), которых не коснулись задания. Сколько их, зависит
    # от случайной формы теста (seed сессии и вариантов — криптостойкий ГСЧ): обычно 5, на полном прогоне встречалось 2,
    # поэтому проверяем смысл демо — видны и «стареет», и «свежо», — а не точное число (раньше было ≥ 3: нестабильно)
    fr = f["freshness"]
    assert f["demo"] is True and fr["aging"] >= 1 and fr["fresh"] >= 3, {k: fr[k] for k in ("n", "fresh", "aging", "stale")}
    feed_item = next(x for x in f["items"] if x["source"] == "feed")
    assert feed_item["status"] == "offered" and feed_item["why"]["kind"] == "stale_skill" and feed_item["remind_count"] == 1
    assert f["schedule"]["blocked"] == "pending"
    # «Смоделировать неделю»: напоминание, затем истечение и новое предложение с другой причиной
    n1 = client.post("/api/candidate/assignments/demo/next-week", headers=H(tm))
    assert n1.status_code == 200 and n1.json()["reminded"] == 1 and n1.json()["offered"] is None
    n2 = client.post("/api/candidate/assignments/demo/next-week", headers=H(tm)).json()
    assert n2["expired"] == 1 and n2["offered"]
    items = client.get("/api/candidate/assignments", headers=H(tm)).json()["items"]
    assert any(x["status_title"] == "Предложение истекло" for x in items)
    ta = client.post("/api/jury/login", json={"persona": "candidate_junior", "scenario": sid}).json()["access_token"]
    j = client.get("/api/candidate/assignments", headers=H(ta)).json()["items"][0]
    assert j["why"]["kind"] == "weak_skill"
    # вне песочницы кнопки нет
    t = candidate_with_category(client, EMAIL)
    assert client.post("/api/candidate/assignments/demo/next-week", headers=H(t)).status_code == 403


# ------------------------------------------------------------------ миграция

def test_migration_tk02_up_down(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from tests.conftest import alembic_config

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "tk02")
    eng = create_engine(url)
    ins = inspect(eng)
    assert {"why", "approach_text", "rubric_result", "review_status", "final_points", "remind_count"} <= {c["name"] for c in ins.get_columns("assignment_attempts")}
    assert {"rubric", "approach_prompt"} <= {c["name"] for c in ins.get_columns("assignments")}
    assert "assignment_prefs" in ins.get_table_names()
    eng.dispose()
    command.downgrade(cfg, "tk01")
    eng = create_engine(url)
    ins = inspect(eng)
    assert "assignment_prefs" not in ins.get_table_names()
    assert "why" not in {c["name"] for c in ins.get_columns("assignment_attempts")}
    assert "rubric" not in {c["name"] for c in ins.get_columns("assignments")}
    eng.dispose()
    command.upgrade(cfg, "head")
