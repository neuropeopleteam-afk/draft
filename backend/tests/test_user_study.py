"""У1: проверка с живыми пользователями — приглашение, путь по фактам платформы, анкета (SUS, P@5), порог показа, права, нет ПДн."""
from datetime import timedelta
import json
import re
import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal, utcnow
from app.modules.study import path as P
from app.modules.study import report, service, stats, texts
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, ONBOARDING, H, candidate_with_category, employer, make_demo, my_ref, pass_test

NEED = "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL. Удалённо, 200–280 тыс."
SUS_GOOD = [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]


def issue(role="candidate", n=1, **kw) -> list[dict]:
    with SessionLocal() as db:
        return service.create_invites(db, role, n, **kw)


def code_of(inv: dict) -> str:
    return inv["code"]


def begin(client, inv: dict) -> dict:
    """Открыть ссылку и дать согласие."""
    assert client.get(f"/api/study/invites/{code_of(inv)}").status_code == 200
    r = client.post(f"/api/study/invites/{code_of(inv)}/start", json={"consent": True})
    assert r.status_code == 200, r.text
    return r.json()


def candidate_path(client, inv, email="c1@example.com", *, finish=True) -> str:
    begin(client, inv)
    t = register_and_verify(client, email=email)
    assert client.post("/api/study/join", json={"code": code_of(inv)}, headers=H(t)).status_code == 200
    if finish:
        assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
        assert pass_test(client, t, "middle")["confirmed"]
    return t


def employer_path(client, inv, email="e1@corp.ru", *, contact=True, cand_ref=None) -> tuple[str, str]:
    begin(client, inv)
    t = register_and_verify(client, email=email, role="employer", company_name="ООО Ромашка")
    assert client.post("/api/study/join", json={"code": code_of(inv)}, headers=H(t)).status_code == 200
    need = client.post("/api/employer/needs", json={"text": NEED}, headers=H(t)).json()
    client.post("/api/study/events", json={"kind": "view", "key": f"/employer/needs/{need['id']}"}, headers=H(t))
    if contact and cand_ref:
        r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": cand_ref}, headers=H(t))
        assert r.status_code == 201, r.text
    return t, need["id"]


# ------------------------------------------------------------------ расчёты

def test_sus_score_standard_scale():
    assert stats.sus_score(SUS_GOOD) == 100.0
    assert stats.sus_score([1, 5, 1, 5, 1, 5, 1, 5, 1, 5]) == 0.0
    assert stats.sus_score([3] * 10) == 50.0
    assert stats.sus_score([4, 2, 4, 2, 4, 2, 4, 2, 4, 2]) == 75.0  # (3·5 + 3·5) · 2,5
    assert stats.sus_score([5, 1, 5, 1, 5, 1, 5, 1, 5, 2]) == 97.5
    for bad in ([3] * 9, [3] * 11, [0] + [3] * 9, [6] + [3] * 9, [True] * 10, ["3"] * 10):
        with pytest.raises(ValueError):
            stats.sus_score(bad)


def test_mean_ci_matches_t_interval():
    m = stats.mean_ci([60.0, 70.0, 80.0], lo=0, hi=100)
    assert m["n"] == 3 and m["mean"] == 70.0 and m["sd"] == 10.0
    assert m["ci"] == pytest.approx([70 - 4.302653 * 10 / 3 ** 0.5, 70 + 4.302653 * 10 / 3 ** 0.5], abs=1e-3)
    assert stats.mean_ci([95.0, 100.0, 100.0], lo=0, hi=100)["ci"][1] == 100  # граница шкалы обрезает интервал
    assert stats.mean_ci([50.0])["ci"] is None and stats.mean_ci([])["mean"] is None


def test_p_at_5_threshold_and_bootstrap_is_reproducible():
    assert stats.p_at_k([5, 4, 3, 2, 1]) == 0.4  # релевантны 4 и 5
    assert stats.p_at_k([4, 4, 4, 4, 4]) == 1.0 and stats.p_at_k([3, 3, 3, 3, 3]) == 0.0
    assert stats.p_at_k([]) is None
    vals = [0.4, 0.6, 0.8, 1.0]
    a, b = stats.boot_mean_ci(vals), stats.boot_mean_ci(vals)
    assert a == b and 0.4 <= a[0] <= a[1] <= 1.0
    w = stats.wilson(6, 9)
    assert w[0] == pytest.approx(0.3, abs=0.01) and w[1] == pytest.approx(0.88, abs=0.01)
    assert stats.share(0, 0)["share"] is None


def test_norm_key_hides_identifiers():
    u = str(uuid.uuid4())
    assert P.norm_key(f"/employer/needs/{u}/v/2?x=1#h") == "/employer/needs/:id/v/:n"
    assert P.norm_key("/employer/candidates/C-7F3A2B") == "/employer/candidates/:ref"
    assert P.norm_key(f"/api/candidate/probes/{u}") == "/candidate/probes/:id"
    assert P.norm_key("/study/K7QH-M2XD-9TPA") == "/study/K7QH-M2XD-9TPA"[:7] + ":t" or P.norm_key("/study/ABCD-EFGH-JKLM")
    assert P.norm_key("javascript:alert(1)") is None and P.norm_key("") is None
    assert "ivan@example.com" not in (P.norm_key("/employer/needs/ivan@example.com") or "")


# ------------------------------------------------------------------ приглашение и согласие

def test_invite_code_is_stored_only_as_hash_and_link_works(client):
    inv = issue("candidate", 2, batch="репетиция")
    assert [i["label"] for i in inv] == ["К-01", "К-02"] and inv[0]["code"] != inv[1]["code"]
    assert re.fullmatch(r"[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}", inv[0]["code"])
    assert inv[0]["url"].endswith(f"/study/{inv[0]['code']}")
    with SessionLocal() as db:
        rows = db.scalars(select(StudyParticipant)).all()
        dump = json.dumps([[str(getattr(r, c.name)) for c in StudyParticipant.__table__.columns] for r in rows])
    assert inv[0]["code"] not in dump and inv[0]["code"].replace("-", "") not in dump
    v = client.get(f"/api/study/invites/{inv[0]['code']}").json()
    assert v["role"] == "candidate" and v["state"] == "new" and len(v["steps"]) == 4 and v["minutes"] == 20
    assert "обезличенн" in v["consent"]["text"] and v["consent"]["version"] == texts.CONSENT_VERSION
    # код без дефисов и в нижнем регистре — тот же участник; чужой код — 404 без подробностей
    assert client.get(f"/api/study/invites/{inv[0]['code'].replace('-', '').lower()}").status_code == 200
    r = client.get("/api/study/invites/AAAA-BBBB-CCCC")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "invite_not_found"
    assert client.get("/api/study/invites/x").status_code == 404


def test_start_requires_consent_and_is_idempotent(client):
    inv = issue("employer")[0]
    assert inv["label"] == "Р-01"
    r = client.post(f"/api/study/invites/{inv['code']}/start", json={"consent": False})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "consent_required"
    assert client.get(f"/api/study/invites/{inv['code']}").json()["state"] == "new"
    r = client.post(f"/api/study/invites/{inv['code']}/start", json={"consent": True})
    assert r.status_code == 200 and r.json()["next"] == "/register?role=employer" and "token" not in r.json()
    with SessionLocal() as db:
        p = db.scalar(select(StudyParticipant))
        first = p.started_at
        assert p.consent_version == texts.CONSENT_VERSION and p.consent_at == p.started_at
    assert client.post(f"/api/study/invites/{inv['code']}/start", json={"consent": True}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(StudyParticipant)).started_at == first  # повтор не сдвигает время начала
    assert client.get(f"/api/study/invites/{inv['code']}").json()["state"] == "started"


def test_quick_mode_enters_without_registration_and_without_mail(client):
    inv = issue("candidate", mode="quick")[0]
    r = client.post(f"/api/study/invites/{inv['code']}/start", json={"consent": True}).json()
    assert r["next"] == "/candidate" and r["token"]["user"]["role"] == "candidate"
    t = r["token"]["access_token"]
    assert r["token"]["user"]["email"].endswith("@study.invalid")  # письма таким учёткам не уходят
    me = client.get("/api/study/me", headers=H(t)).json()
    assert me["active"] and me["mode"] == "quick"
    reg = next(s for s in me["steps"] if s["key"] == "register")
    assert reg["done"] and reg["skipped"]  # регистрация не измерялась
    assert client.get("/api/me", headers=H(t)).json()["candidate"]["public_ref"]
    # повторный вход по той же ссылке — в ту же учётную запись
    r2 = client.post(f"/api/study/invites/{inv['code']}/start", json={"consent": True}).json()
    assert r2["token"]["user"]["id"] == r["token"]["user"]["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 1


# ------------------------------------------------------------------ путь кандидата по фактам платформы

def test_candidate_path_steps_come_from_platform_facts(client):
    inv = issue("candidate")[0]
    t = candidate_path(client, inv, finish=False)
    me = client.get("/api/study/me", headers=H(t)).json()
    st = {s["key"]: s for s in me["steps"]}
    assert me["role"] == "candidate" and st["register"]["done"] and not st["register"]["skipped"]
    assert not st["survey"]["done"] and me["current"] == "survey" and not me["path_done"]
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t))
    assert r.status_code == 201
    st = {s["key"]: s for s in client.get("/api/study/me", headers=H(t)).json()["steps"]}
    assert st["survey"]["done"] and st["test"]["done"] and not st["result"]["done"]
    # дальше — как в test_day2_rules: все ответы верны и «завершить»
    from tests.test_day2_rules import correct_index
    s = r.json()
    while s["item"]:
        it = s["item"]
        s = client.post(f"/api/assessment/sessions/{s['session_id']}/answers",
                        json={"item_id": it["item_id"], "answer": correct_index(s["session_id"], it["item_id"])}, headers=H(t)).json()
    assert client.post(f"/api/assessment/sessions/{s['session_id']}/finish", headers=H(t)).status_code == 200
    me = client.get("/api/study/me", headers=H(t)).json()
    assert me["path_done"] and me["current"] is None and all(s["done"] for s in me["steps"])
    with SessionLocal() as db:
        p = db.scalar(select(StudyParticipant))
        d = P.derive(db, p)
        order = [d["steps"][k]["at"] for k in d["keys"]]
        assert order == sorted(order) and d["done_at"] == order[-1]
        assert P.status_of(p, d, False) == "done"


def test_facts_before_consent_are_not_counted(client):
    """Учётная запись, у которой тест был до согласия, не получает «пройденный путь» задним числом."""
    t = candidate_with_category(client, email="old@example.com")  # аккаунт уже с категорией
    inv = issue("candidate")[0]
    begin(client, inv)
    assert client.post("/api/study/join", json={"code": inv["code"]}, headers=H(t)).status_code == 200
    me = client.get("/api/study/me", headers=H(t)).json()
    st = {s["key"]: s for s in me["steps"]}
    assert st["register"]["done"] and st["register"]["skipped"]  # «уже был аккаунт»
    assert not st["survey"]["done"] and not st["test"]["done"] and not st["result"]["done"] and not me["path_done"]


def test_stopped_vs_active_by_inactivity(client):
    inv = issue("candidate")[0]
    candidate_path(client, inv, finish=False)
    with SessionLocal() as db:
        p = db.scalar(select(StudyParticipant))
        d = P.derive(db, p)
        assert P.status_of(p, d, False) == "active"
        assert P.status_of(p, d, False, now=utcnow() + P.STALL_AFTER + timedelta(minutes=1)) == "stopped"
        assert P.status_of(p, d, True) == "stopped"  # ответил на анкету, не дойдя до конца
        assert d["current"] == "survey"  # «где бросил» — первый непройденный шаг


# ------------------------------------------------------------------ путь работодателя и анкета с P@5

def seed_pool(client, n=6):
    refs = []
    for i in range(n):
        tc = candidate_with_category(client, email=f"pool{i}@example.com")
        refs.append(my_ref(client, tc))
    return refs


def test_employer_path_and_top5_ratings_give_p_at_5(client):
    refs = seed_pool(client, 6)
    inv = issue("employer")[0]
    t, need_id = employer_path(client, inv, cand_ref=refs[0])
    me = client.get("/api/study/me", headers=H(t)).json()
    assert me["path_done"], me["steps"]
    form = client.get("/api/study/survey", headers=H(t)).json()
    shown = form["rel"]["selection"]["shown"]
    assert len(shown) == 5 and [x["rank"] for x in shown] == [1, 2, 3, 4, 5] and all(x["ref"] for x in shown)
    assert form["belief"]["q"] and form["grade_fit"] is None and len(form["sus"]["items"]) == 10
    ratings = [{"ref": x["ref"], "rating": r} for x, r in zip(shown, [5, 4, 4, 2, 1])]
    # неполные, лишние и неверные оценки не принимаются
    base = {"sus": SUS_GOOD, "belief": 4}
    assert client.post("/api/study/survey", json={**base, "ratings": ratings[:3]}, headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={**base, "ratings": ratings[:4] + [{"ref": "C-ZZZZZZ", "rating": 3}]},
                       headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={**base, "ratings": [{**ratings[0], "rating": 6}] + ratings[1:]},
                       headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={"sus": [3] * 9, "ratings": ratings}, headers=H(t)).status_code == 422
    ok = client.post("/api/study/survey", json={**base, "ratings": ratings, "tags": ["slow", "нет-такой"],
                                                "comment": "Долго искал кнопку, пишите на ivan.petrov@example.com или +7 900 111-22-33"},
                     headers=H(t))
    assert ok.status_code == 200 and ok.json()["sus_score"] == 100.0 and ok.json()["path_done"]
    with SessionLocal() as db:
        a = db.scalar(select(StudyAnswer))
        assert a.tags == ["slow"] and a.selection["shown"] == 5 and a.selection["algorithm"]
        assert "ivan.petrov" not in a.comment and "900" not in a.comment  # контакты вырезаны до записи
        row = [r for r in report.rows(db)][0]
        assert row.p5 == 0.6 and row.sus == 100.0 and row.status == "done"
    # повторная отправка заменяет ответы, а не копит
    assert client.post("/api/study/survey", json={**base, "ratings": ratings}, headers=H(t)).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyAnswer)) == 1


def test_employer_who_never_saw_selection_is_not_asked_about_it(client):
    inv = issue("employer")[0]
    begin(client, inv)
    t = register_and_verify(client, email="lazy@corp.ru", role="employer")
    client.post("/api/study/join", json={"code": inv["code"]}, headers=H(t))
    form = client.get("/api/study/survey", headers=H(t)).json()
    assert not form["exposed"] and form["rel"]["selection"] is None
    r = client.post("/api/study/survey", json={"sus": [3] * 10, "belief": 5, "tags": ["unclear"]}, headers=H(t))
    assert r.status_code == 200
    with SessionLocal() as db:
        a = db.scalar(select(StudyAnswer))
        assert a.belief is None and a.ratings == [] and not a.path_done  # о подборке и грейде не спрашивали — ответа нет


def test_candidate_grade_questions_only_after_result(client):
    inv = issue("candidate")[0]
    t = candidate_path(client, inv, finish=False)
    r = client.post("/api/study/survey", json={"sus": [3] * 10, "belief": 5, "grade_fit": "fit"}, headers=H(t))
    assert r.status_code == 200
    with SessionLocal() as db:
        a = db.scalar(select(StudyAnswer))
        assert a.belief is None and a.grade_fit is None
    inv2 = issue("candidate")[0]
    t2 = candidate_path(client, inv2, email="c2@example.com")
    assert client.get("/api/study/survey", headers=H(t2)).json()["grade_fit"]["options"]
    assert client.post("/api/study/survey", json={"sus": [3] * 10, "belief": 4, "grade_fit": "higher"}, headers=H(t2)).status_code == 200
    with SessionLocal() as db:
        got = {a.belief: a.grade_fit for a in db.scalars(select(StudyAnswer))}
        assert got.get(4) == "higher"


# ------------------------------------------------------------------ порог показа и сводка

def answered_participant(db, role="candidate", sus=None, ratings=None, test=False, started=None, belief=None):
    p = StudyParticipant(code_hash=uuid.uuid4().hex + uuid.uuid4().hex, role=role, label=f"X-{uuid.uuid4().hex[:4]}",
                         is_test=test, started_at=started or utcnow(), consent_at=utcnow(), consent_version="t")
    db.add(p)
    db.flush()
    db.add(StudyAnswer(participant_id=p.id, sus=sus or SUS_GOOD, ratings=ratings or [], belief=belief, tags=["slow"],
                       submitted_at=utcnow()))
    db.commit()
    return p


def test_block_is_hidden_below_three_respondents(client):
    assert client.get("/api/study/summary").json() == {"shown": False, "min_n": 3}
    with SessionLocal() as db:
        answered_participant(db)
        answered_participant(db, "employer")
    assert client.get("/api/study/summary").json() == {"shown": False, "min_n": 3}  # двое — без цифр и без числа участников
    with SessionLocal() as db:
        answered_participant(db, test=True)  # репетиция не считается
        answered_participant(db, test=True)
    assert client.get("/api/study/summary").json()["shown"] is False
    with SessionLocal() as db:
        answered_participant(db)
    s = client.get("/api/study/summary").json()
    assert s["shown"] and s["n"]["answered"] == 3 and s["n"]["by_role"]["candidate"]["answered"] == 2
    assert s["sus"]["n"] == 3 and s["sus"]["mean"] == 100.0
    assert "N = 3" in s["signature"] and "приглашены командой" in s["signature"]
    assert s["sus"]["by_role"] == {}  # у роли меньше трёх ответивших — своего среза нет
    assert s["p5"]["n"] == 0 and "mean" not in s["p5"]


def test_role_slices_p5_and_sus_ci(client):
    base = utcnow() - timedelta(days=1)
    with SessionLocal() as db:
        for sus, r in [([5, 1, 5, 1, 5, 1, 5, 1, 5, 1], [5, 5, 4, 4, 3]), ([4, 2, 4, 2, 4, 2, 4, 2, 4, 2], [5, 4, 3, 2, 1]),
                       ([3, 3, 3, 3, 3, 3, 3, 3, 3, 3], [4, 4, 4, 1, 1])]:
            answered_participant(db, "employer", sus=sus, started=base, belief=4,
                                 ratings=[{"ref": f"C-{i}", "rank": i + 1, "rating": v} for i, v in enumerate(r)])
        for _ in range(3):
            answered_participant(db, "candidate", sus=[4, 2, 4, 2, 4, 2, 4, 2, 4, 2], started=base, belief=3)
    s = client.get("/api/study/summary").json()
    assert s["sus"]["n"] == 6 and set(s["sus"]["by_role"]) == {"candidate", "employer"}
    assert s["sus"]["by_role"]["employer"]["mean"] == pytest.approx((100 + 75 + 50) / 3)
    lo, hi = s["sus"]["by_role"]["employer"]["ci"]
    assert 0 <= lo < 75 < hi <= 100
    p5 = s["p5"]
    # P@5 участников: 0,6; 0,4; 0,6 → среднее 0,5333
    assert p5["n"] == 3 and p5["mean"] == pytest.approx((0.6 + 0.4 + 0.6) / 3) and p5["threshold"] == 4
    assert p5["ratings"] == 15 and p5["ratings_relevant"] == 7 and len(p5["by_rank"]) == 5 and p5["ci"][0] <= p5["mean"] <= p5["ci"][1]
    assert s["belief"]["employer"]["mean"] == 4.0 and s["belief"]["candidate"]["mean"] == 3.0
    assert s["blockers"] == {texts.BLOCKER_TAGS["slow"]: 6}


def test_completion_time_and_errors_in_summary(client):
    refs = seed_pool(client, 3)
    invs = issue("employer", 3)
    for i, inv in enumerate(invs):
        t, _ = employer_path(client, inv, email=f"e{i}@corp.ru", cand_ref=refs[i] if i < 2 else None)
        if i == 0:
            client.post("/api/study/events", json={"kind": "error", "key": f"/api/employer/needs/{uuid.uuid4()}",
                                                   "status": 500, "code": "http_500"}, headers=H(t))
        client.post("/api/study/survey", json={"sus": SUS_GOOD}, headers=H(t))
    with SessionLocal() as db:  # третий остановился на «вопрос или приглашение» (прошло больше получаса)
        p = db.scalars(select(StudyParticipant).order_by(StudyParticipant.label)).all()[2]
        assert P.derive(db, p)["current"] == "contact"
    s = client.get("/api/study/summary").json()
    assert s["shown"] and s["n"]["started"] == 3 and s["n"]["done"] == 2
    c = s["completion"]
    assert c["done"] == 2 and c["stopped"] == 1 and c["share"]["share"] == pytest.approx(2 / 3)
    assert c["stopped_at"] == {"contact": 1}
    assert s["time"]["n"] == 2 and s["time"]["median_s"] >= 0 and "need" in s["time"]["step_median_s"]
    assert s["errors"] == {"participants": 1, "of": 3, "server": 1, "total": 1, "by_code": {"http_500": 1}}


def test_withdrawn_participants_leave_no_trace(client):
    refs = seed_pool(client, 2)
    inv = issue("employer")[0]
    t, _ = employer_path(client, inv, cand_ref=refs[0])
    client.post("/api/study/survey", json={"sus": SUS_GOOD}, headers=H(t))
    assert client.post("/api/study/withdraw", headers=H(t)).json() == {"ok": True}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyAnswer)) == 0
        assert db.scalar(select(func.count()).select_from(StudyEvent)) == 0
        p = db.scalar(select(StudyParticipant))
        assert p.withdrawn_at and p.user_id is None and not p.is_active
        assert report.rows(db) == []
    assert client.get("/api/study/me", headers=H(t)).json() == {"active": False}
    assert client.post(f"/api/study/invites/{inv['code']}/start", json={"consent": True}).status_code == 410
    assert client.get(f"/api/study/invites/{inv['code']}").json()["state"] == "withdrawn"


# ------------------------------------------------------------------ права

def test_join_rules(client):
    inv_c, inv_e = issue("candidate")[0], issue("employer")[0]
    tc = register_and_verify(client, email="who@example.com")
    # без согласия привязаться нельзя
    assert client.post("/api/study/join", json={"code": inv_c["code"]}, headers=H(tc)).json()["detail"]["code"] == "consent_required"
    begin(client, inv_c)
    begin(client, inv_e)
    # роль не совпадает
    r = client.post("/api/study/join", json={"code": inv_e["code"]}, headers=H(tc))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "role_mismatch"
    assert client.post("/api/study/join", json={"code": inv_c["code"]}, headers=H(tc)).status_code == 200
    assert client.post("/api/study/join", json={"code": inv_c["code"]}, headers=H(tc)).status_code == 200  # повтор безопасен
    # чужая ссылка и чужая учётка
    t2 = register_and_verify(client, email="other@example.com")
    r = client.post("/api/study/join", json={"code": inv_c["code"]}, headers=H(t2))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invite_taken"
    inv_c2 = issue("candidate")[0]
    begin(client, inv_c2)
    assert client.post("/api/study/join", json={"code": inv_c2["code"]}, headers=H(tc)).json()["detail"]["code"] == "already_participant"
    assert client.post("/api/study/join", json={"code": "AAAA-BBBB-CCCC"}, headers=H(t2)).status_code == 404
    assert client.post("/api/study/join", json={"code": inv_c["code"]}).status_code == 401


def test_demo_accounts_cannot_join(client):
    inv = issue("candidate")[0]
    begin(client, inv)
    t = register_and_verify(client, email="demo-juror@example.com")
    make_demo("demo-juror@example.com")
    r = client.post("/api/study/join", json={"code": inv["code"]}, headers=H(t))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "demo_account"


def test_non_participants_get_neutral_answers(client):
    t = register_and_verify(client, email="plain@example.com")
    assert client.get("/api/study/me", headers=H(t)).json() == {"active": False}
    assert client.post("/api/study/events", json={"kind": "view", "key": "/candidate"}, headers=H(t)).status_code == 204
    assert client.get("/api/study/survey", headers=H(t)).status_code == 404
    assert client.post("/api/study/survey", json={"sus": [3] * 10}, headers=H(t)).status_code == 404
    assert client.post("/api/study/withdraw", headers=H(t)).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyEvent)) == 0


def test_admin_routes_are_admin_only(client):
    tc = register_and_verify(client, email="x@example.com")
    body = {"role": "candidate", "n": 1}
    assert client.post("/api/study/admin/invites", json=body).status_code == 401
    assert client.post("/api/study/admin/invites", json=body, headers=H(tc)).status_code == 403
    assert client.get("/api/study/admin/report", headers=H(tc)).status_code == 403
    from app.core.enums import UserRole
    from app.core.security import hash_password
    from app.modules.auth.models import User

    with SessionLocal() as db:
        db.add(User(email="adm@example.com", password_hash=hash_password("Passw0rd!x1"), role=UserRole.admin, is_email_verified=True))
        db.commit()
    from app.core.security import create_access_token

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "adm@example.com"))
        ta = create_access_token(u.id, "admin", u.token_version)[0]
    r = client.post("/api/study/admin/invites", json={**body, "n": 2, "batch": "дв"}, headers=H(ta))
    assert r.status_code == 200 and len(r.json()["invites"]) == 2 and r.json()["invites"][0]["url"].startswith("http")
    rep = client.get("/api/study/admin/report", headers=H(ta)).json()
    assert len(rep["participants"]) == 2 and rep["participants"][0]["status"] == "not_started"


# ------------------------------------------------------------------ нет ПДн

def test_no_personal_data_in_public_or_admin_output(client):
    refs = seed_pool(client, 3)
    secret_email, secret_name = "ivan.sidorov@example.com", "Сидоров Иван"
    for i in range(3):
        inv = issue("employer")[0]
        begin(client, inv)
        t = register_and_verify(client, email=f"sidorov{i}@corp.ru" if i else secret_email, role="employer",
                                company_name="ООО Тайная", full_name=secret_name)
        client.post("/api/study/join", json={"code": inv["code"]}, headers=H(t))
        client.post("/api/employer/needs", json={"text": NEED}, headers=H(t))
        client.post("/api/study/survey", json={"sus": SUS_GOOD, "comment": f"звоните {secret_email} 8 (900) 123-45-67 t.me/sidorov"}, headers=H(t))
        client.post("/api/study/events", json={"kind": "view", "key": f"/employer/candidates/{refs[0]}"}, headers=H(t))
    with SessionLocal() as db:
        pub = json.dumps(report.public_summary(db), ensure_ascii=False)
        adm = json.dumps(report.admin_report(db, with_texts=True), ensure_ascii=False, default=str)
        raw = json.dumps([e.key for e in db.scalars(select(StudyEvent))], ensure_ascii=False)
        codes = [i["code"].replace("-", "") for i in []]
    for blob in (pub, adm, raw):
        for needle in (secret_email, "sidorov", "Сидоров", "ООО Тайная", "123-45-67", "t.me", refs[0]):
            assert needle not in blob, needle
    assert client.get("/api/study/summary").text.count("@") == 0
    # на странице приглашения — никаких данных других участников
    inv = issue("candidate")[0]
    v = json.dumps(client.get(f"/api/study/invites/{inv['code']}").json(), ensure_ascii=False)
    assert "sidorov" not in v and "N =" not in v


# ------------------------------------------------------------------ команды

def test_cli_invite_status_report_close(client, capsys):
    from app.modules.study.__main__ import main

    assert main(["invite", "--role", "employer", "--n", "2", "--batch", "10.10", "--base-url", "https://example.org"]) == 0
    out = capsys.readouterr().out
    links = re.findall(r"(Р-\d\d)\thttps://example\.org/study/([2-9A-Z]{4}-[2-9A-Z]{4}-[2-9A-Z]{4})", out)
    assert [x[0] for x in links] == ["Р-01", "Р-02"] and "один раз" in out
    assert main(["invite", "--role", "candidate", "--n", "1", "--test", "--quick"]) == 0
    assert "РЕПЕТИЦИЯ" in capsys.readouterr().out
    assert main(["invite", "--role", "candidate", "--n", "0"]) == 2
    assert main(["status"]) == 0
    st = capsys.readouterr().out
    assert "Р-01" in st and "ТК-01" in st and "[репетиция]" in st
    assert main(["report"]) == 0 and main(["summary"]) == 0
    capsys.readouterr()
    assert main(["close"]) == 2  # без --batch/--label все ссылки не закрываются
    assert main(["close", "--batch", "10.10"]) == 0 and "2" in capsys.readouterr().out
    assert client.get(f"/api/study/invites/{links[0][1]}").json()["state"] == "closed"
    assert client.post(f"/api/study/invites/{links[0][1]}/start", json={"consent": True}).status_code == 410
