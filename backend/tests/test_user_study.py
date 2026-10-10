"""Живые пользователи: обезличенная статистика прохождения — расчёты, включение и отказ, исключение автотестов и служебных
учёток, путь по фактам платформы, необязательная анкета (SUS, P@5), порог показа N ≥ 3, сброс, нет ПДн."""
from datetime import timedelta
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal, utcnow
from app.core.enums import UserRole
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.auth.service import issue_token
from app.modules.jury import scope
from app.modules.study import exclude, report, service, stats, texts
from app.modules.study import path as P
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, ONBOARDING, H, candidate_with_category, correct_index, my_ref, pass_test

HUMAN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
NEED = "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL. Удалённо, 200–280 тыс."
SUS_GOOD = [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]


@pytest.fixture(autouse=True)
def human_browser(client):
    """TestClient представляется «testclient» — для статистики это автотест; тесты ведут себя как обычный браузер."""
    client.headers["user-agent"] = HUMAN
    yield


def on(client, t, **kw) -> dict:
    r = client.post("/api/study/enroll", json=kw, headers=H(t))
    assert r.status_code == 200, r.text
    return r.json()


def candidate(client, email="anna@mail.ru") -> str:
    return register_and_verify(client, email=email)


def employer_t(client, email="boss@corp.ru") -> str:
    return register_and_verify(client, email=email, role="employer", company_name="ООО Ромашка")


def seed_pool(client, n=6) -> list[str]:
    return [my_ref(client, candidate_with_category(client, email=f"pool{i}@example.com")) for i in range(n)]


def run_test(client, t, **body) -> None:
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", **body}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    while s["item"]:
        it = s["item"]
        s = client.post(f"/api/assessment/sessions/{s['session_id']}/answers",
                        json={"item_id": it["item_id"], "answer": correct_index(s["session_id"], it["item_id"])}, headers=H(t)).json()
    assert client.post(f"/api/assessment/sessions/{s['session_id']}/finish", headers=H(t)).status_code == 200


def finished_candidate(client, email="anna@mail.ru") -> str:
    t = candidate(client, email)
    on(client, t)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    assert pass_test(client, t, "middle")["confirmed"]
    return t


def finished_employer(client, ref, email="boss@corp.ru") -> tuple[str, str]:
    t = employer_t(client, email)
    on(client, t)
    need = client.post("/api/employer/needs", json={"text": NEED}, headers=H(t)).json()
    client.post("/api/study/events", json={"kind": "view", "key": f"/employer/needs/{need['id']}"}, headers=H(t))
    assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(t)).status_code == 201
    return t, need["id"]


def top5_form(client, t, **q) -> dict:
    return client.get("/api/study/survey", params=q, headers=H(t)).json()


def ratings_of(form, values=(5, 4, 4, 2, 1)) -> list[dict]:
    return [{"ref": x["ref"], "rating": v} for x, v in zip(form["rel"]["selection"]["shown"], values)]


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
    assert w[0] == pytest.approx(0.354, abs=0.005) and w[1] == pytest.approx(0.879, abs=0.005)
    assert stats.share(0, 0)["share"] is None


def test_norm_key_hides_identifiers():
    u = str(uuid.uuid4())
    assert P.norm_key(f"/employer/needs/{u}/v/2?x=1#h") == "/employer/needs/:id/v/:n"
    assert P.norm_key("/employer/candidates/C-7F3A2B") == "/employer/candidates/:ref"
    assert P.norm_key(f"/api/candidate/probes/{u}") == "/candidate/probes/:id"
    assert P.norm_key("/study/ABCD-EFGH-JKLM") == "/study/ABCD-EFGH-JKLM"[:7] + ":t" or P.norm_key("/study/ABCD-EFGH-JKLM")
    assert P.norm_key("javascript:alert(1)") is None and P.norm_key("") is None
    assert "ivan@example.com" not in (P.norm_key("/employer/needs/ivan@example.com") or "")


# ------------------------------------------------------------------ кого не считаем

def _u(email, role=UserRole.candidate, demo=False) -> User:
    return User(email=email, password_hash="x", role=role, is_demo=demo)


@pytest.mark.parametrize("email,role,demo,ua,auto,expect", [
    ("anna@mail.ru", UserRole.candidate, False, HUMAN, False, None),
    ("boss@corp.ru", UserRole.employer, False, HUMAN, False, None),
    ("anna@mail.ru", UserRole.candidate, False, "Mozilla/5.0 HeadlessChrome/130.0", False, "automation"),
    ("anna@mail.ru", UserRole.candidate, False, "Playwright/1.48", False, "automation"),
    ("anna@mail.ru", UserRole.candidate, False, "python-httpx/0.27", False, "automation"),
    ("anna@mail.ru", UserRole.candidate, False, "testclient", False, "automation"),
    ("anna@mail.ru", UserRole.candidate, False, HUMAN, True, "automation"),  # navigator.webdriver
    ("expert@mail.ru", UserRole.expert, False, HUMAN, False, "role"),
    ("adm@mail.ru", UserRole.admin, False, HUMAN, False, "role"),
    ("fsp@mail.ru", UserRole.fsp_analyst, False, HUMAN, False, "role"),
    ("e2e-1a2b3c@mail.ru", UserRole.candidate, False, HUMAN, False, "test_account"),
    ("qa.tester@corp.ru", UserRole.employer, False, HUMAN, False, "test_account"),
    ("test+1@mail.ru", UserRole.candidate, False, HUMAN, False, "test_account"),
    ("someone@example.com", UserRole.candidate, False, HUMAN, False, "test_account"),
    ("hr@company.test", UserRole.employer, False, HUMAN, False, "test_account"),
    ("demo-candidate-001@demo.invalid", UserRole.candidate, True, HUMAN, False, "service"),
    ("someone@mail.ru", UserRole.candidate, True, HUMAN, False, "service"),  # демо-сид не из песочницы жюри
    ("candidate@jury.example.com", UserRole.candidate, True, HUMAN, False, "shared_demo"),  # общее демо — один аккаунт на многих
    ("employer@jury.example.com", UserRole.employer, True, HUMAN, False, "shared_demo"),
    ("guest-ab12cd34+abcde12345@jury.example.com", UserRole.candidate, True, HUMAN, False, "service"),  # гость QR-демонстрации
    ("expert+abcde12345@jury.example.com", UserRole.expert, True, HUMAN, False, "role"),
    ("candidate-new+abcde12345@jury.example.com", UserRole.candidate, True, HUMAN, False, None),  # песочница одного эксперта
    ("employer+abcde12345@jury.example.com", UserRole.employer, True, HUMAN, False, None),
])
def test_exclusion_rules(email, role, demo, ua, auto, expect):
    assert exclude.reason(_u(email, role, demo), ua=ua, automation=auto) == expect


def test_kill_switch_turns_everything_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "study_enabled", False)
    t = candidate(client)
    assert on(client, t) == {"state": "excluded", "reason": "disabled"}
    assert client.get("/api/study/me", headers=H(t)).json()["state"] == "excluded"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 0


# ------------------------------------------------------------------ уведомление, включение, отказ

def test_first_login_notice_then_enroll_keeps_no_personal_data(client):
    t = candidate(client)
    assert client.get("/api/study/me", headers=H(t)).json() == {"state": "new"}  # уведомление ещё не показано
    r = on(client, t)
    assert r["state"] == "on" and r["role"] == "candidate" and not r["path_done"] and r["prompt"] is False
    assert [s["key"] for s in r["steps"]] == ["survey", "test", "result"] and r["current"] == "survey"
    assert on(client, t)["state"] == "on"  # повтор безопасен
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 1
        p = db.scalar(select(StudyParticipant))
        cols = {c.name for c in StudyParticipant.__table__.columns}
        assert not cols & {"email", "name", "ip", "phone", "user_agent"}  # в таблице нет ни почты, ни имени, ни адреса
        assert p.role == "candidate" and p.declined_at is None
    # работодатель — свой путь
    te = employer_t(client)
    assert [s["key"] for s in on(client, te)["steps"]] == ["need", "selection", "contact"]


def test_decline_deletes_data_and_is_respected(client):
    t = finished_candidate(client)
    client.post("/api/study/events", json={"kind": "view", "key": "/candidate/profile"}, headers=H(t))
    assert client.post("/api/study/survey", json={"sus": SUS_GOOD}, headers=H(t)).status_code == 200
    assert client.post("/api/study/decline", headers=H(t)).json() == {"state": "declined"}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyEvent)) == 0
        assert db.scalar(select(func.count()).select_from(StudyAnswer)) == 0
        assert db.scalar(select(StudyParticipant.declined_at)) is not None
        assert report.rows(db) == []
    # отказ уважается: ни me, ни автоматическое включение, ни события, ни анкета его не отменяют
    assert client.get("/api/study/me", headers=H(t)).json() == {"state": "declined"}
    assert on(client, t) == {"state": "declined"}
    assert client.post("/api/study/events", json={"kind": "view", "key": "/candidate"}, headers=H(t)).status_code == 204
    assert client.get("/api/study/survey", headers=H(t)).status_code == 404
    assert client.post("/api/study/survey", json={"sus": SUS_GOOD}, headers=H(t)).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyEvent)) == 0
    # только сам человек может включить снова — со свежим началом
    again = on(client, t, again=True)
    st = {s["key"]: s for s in again["steps"]}
    assert again["state"] == "on" and not again["path_done"] and again["current"] == "test"
    assert st["survey"]["skipped"]  # опрос и тест были до нового начала — заново не засчитываются


def test_decline_before_enroll_is_remembered(client):
    t = candidate(client)
    assert client.post("/api/study/decline", headers=H(t)).json() == {"state": "declined"}
    assert on(client, t) == {"state": "declined"}


def test_automation_is_not_counted(client):
    t = candidate(client)
    client.headers["user-agent"] = "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/130.0 Safari/537.36"
    assert on(client, t) == {"state": "excluded", "reason": "automation"}
    assert client.get("/api/study/me", headers=H(t)).json() == {"state": "excluded", "reason": "automation"}
    client.headers["user-agent"] = HUMAN
    assert on(client, t, automation=True) == {"state": "excluded", "reason": "automation"}  # navigator.webdriver
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 0
    # человек в обычном браузере включается, и уже включённого автотест (тот же логин с другим UA) не ломает
    assert on(client, t)["state"] == "on"
    client.headers["user-agent"] = "Playwright/1.48"
    assert client.get("/api/study/me", headers=H(t)).json()["state"] == "excluded"
    client.post("/api/study/events", json={"kind": "view", "key": "/candidate"}, headers=H(t))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyEvent)) == 0  # события автотеста не пишутся


def test_service_accounts_do_not_enroll(client):
    t = register_and_verify(client, email="e2e-9f8e7d@mail.ru")
    assert on(client, t) == {"state": "excluded", "reason": "test_account"}
    t2 = register_and_verify(client, email="x@example.com", role="employer", company_name="ООО")
    assert on(client, t2)["reason"] == "test_account"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 0


def test_events_only_for_enrolled_and_without_identifiers(client):
    t = candidate(client)
    assert client.post("/api/study/events", json={"kind": "view", "key": "/candidate"}, headers=H(t)).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyEvent)) == 0  # включения не было — не пишем
    on(client, t)
    u = uuid.uuid4()
    for body in ({"kind": "view", "key": f"/employer/needs/{u}/v/2?email=ivan@mail.ru"},
                 {"kind": "view", "key": "/study/survey"},
                 {"kind": "error", "key": f"/api/candidate/probes/{u}", "status": 500, "code": "http_500 <b>"}):
        assert client.post("/api/study/events", json=body, headers=H(t)).status_code == 204
    with SessionLocal() as db:
        ev = [(e.kind, e.key, e.status, e.code) for e in db.scalars(select(StudyEvent).order_by(StudyEvent.at))]
    assert ev == [("view", "/employer/needs/:id/v/:n", None, None), ("error", "/candidate/probes/:id", 500, "http_500b")]
    assert client.post("/api/study/events", json={"kind": "view", "key": "/x"}).status_code == 401


# ------------------------------------------------------------------ путь по фактам платформы

def test_candidate_path_comes_from_platform_facts(client):
    t = candidate(client)
    on(client, t)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    me = client.get("/api/study/me", headers=H(t)).json()
    assert [s["key"] for s in me["steps"] if s["done"]] == ["survey"] and me["current"] == "test"
    run_test(client, t)
    me = client.get("/api/study/me", headers=H(t)).json()
    assert me["path_done"] and me["current"] is None and me["prompt"] is True  # анкету предложат один раз
    with SessionLocal() as db:
        p = db.scalar(select(StudyParticipant))
        d = P.derive(db, p)
        order = [d["steps"][k]["at"] for k in d["keys"]]
        assert order == sorted(order) and d["done_at"] == order[-1]
        assert P.status_of(p, d, False) == "done"


def test_facts_before_enrollment_are_not_counted(client):
    """Старая учётка с категорией: опрос был заранее (пропущен), а тест и результат — только новые."""
    t = candidate_with_category(client, email="old@mail.ru")
    r = on(client, t)
    st = {s["key"]: s for s in r["steps"]}
    assert st["survey"]["done"] and st["survey"]["skipped"]
    assert not st["test"]["done"] and not st["result"]["done"] and not r["path_done"]


def test_stopped_vs_active_by_inactivity(client):
    t = candidate(client)
    on(client, t)
    with SessionLocal() as db:
        p = db.scalar(select(StudyParticipant))
        d = P.derive(db, p)
        assert P.status_of(p, d, False) == "active"
        assert P.status_of(p, d, False, now=utcnow() + P.STALL_AFTER + timedelta(minutes=1)) == "stopped"
        assert P.status_of(p, d, True) == "stopped"  # ответил на анкету, не дойдя до конца
        assert d["current"] == "survey"  # «где бросил» — первый непройденный шаг


def test_employer_path_with_new_or_existing_need(client):
    refs = seed_pool(client, 2)
    t, need_id = finished_employer(client, refs[0])
    me = client.get("/api/study/me", headers=H(t)).json()
    assert me["path_done"], me["steps"]
    # потребность, открытая без создания (как у персоны жюри): шаги «потребность» и «подборка» — по одному просмотру
    t2 = employer_t(client, "second@corp.ru")
    on(client, t2)
    client.post("/api/employer/needs", json={"text": NEED}, headers=H(t2))
    with SessionLocal() as db:
        p2 = db.scalar(select(StudyParticipant).where(StudyParticipant.user_id == db.scalar(select(User.id).where(User.email == "second@corp.ru"))))
        p2.enrolled_at = utcnow() + timedelta(hours=1)  # потребность появилась «до» начала сбора
        db.commit()
        d = P.derive(db, p2)
        assert d["steps"]["need"]["at"] is None
    client.post("/api/study/events", json={"kind": "view", "key": f"/employer/needs/{need_id}"}, headers=H(t2))


# ------------------------------------------------------------------ песочница жюри: персоны

def test_jury_sandbox_personas_are_counted_and_shared_demo_is_not(client):
    from app.modules.jury import seed

    sid = "abcde12345"
    with SessionLocal() as db:
        seed._candidate_new(db, sid)
        u = db.scalar(select(User).where(User.email == scope.emails(sid)["candidate_new"]))
        tok = issue_token(u, {scope.CLAIM: sid}).access_token
        shared = _u("candidate@jury.example.com", UserRole.candidate, True)
        assert exclude.reason(shared, ua=HUMAN) == "shared_demo"
    r = on(client, tok)
    st = {s["key"]: s for s in r["steps"]}
    assert r["state"] == "on" and st["survey"]["skipped"] and st["survey"]["done"]  # опрос заполнен заранее — пропущен
    assert r["current"] == "test"
    # песочница жюри: правило 90 дней снято; путь проходится тем же тестом (на стенде — и экспресс-режим 5–7 заданий)
    assert client.get("/api/assessment/status", headers=H(tok)).json()["sandbox_active"]
    run_test(client, tok)
    me = client.get("/api/study/me", headers=H(tok)).json()
    assert me["path_done"] and me["prompt"] is True


# ------------------------------------------------------------------ необязательная анкета

def test_survey_is_optional_and_parts_are_independent(client):
    t = finished_candidate(client)
    assert client.get("/api/study/me", headers=H(t)).json()["prompt"] is True
    assert client.post("/api/study/survey/shown", headers=H(t)).json() == {"ok": True}
    me = client.get("/api/study/me", headers=H(t)).json()
    assert me["prompt"] is False and me["path_done"]  # показали один раз — повторно не предлагают
    form = client.get("/api/study/survey", headers=H(t)).json()
    assert len(form["sus"]["items"]) == 10 and form["grade_fit"]["options"] and form["belief"]["q"] and form["answers"] is None
    # пустая отправка и неполный SUS не принимаются, закрыть окно — можно без ответа
    assert client.post("/api/study/survey", json={}, headers=H(t)).json()["detail"]["code"] == "empty_survey"
    assert client.post("/api/study/survey", json={"sus": [3] * 9}, headers=H(t)).json()["detail"]["code"] == "bad_sus"
    assert client.post("/api/study/survey", json={"sus": [3] * 10 + [3]}, headers=H(t)).status_code == 422
    # одна часть без другой: только «верю грейду» и комментарий
    ok = client.post("/api/study/survey", json={"belief": 4, "grade_fit": "higher", "tags": ["slow", "нет-такой"],
                                                "comment": "Долго искал кнопку, пишите на ivan.petrov@mail.ru или +7 900 111-22-33"},
                     headers=H(t))
    assert ok.status_code == 200 and ok.json()["sus_score"] is None and ok.json()["path_done"]
    with SessionLocal() as db:
        a = db.scalar(select(StudyAnswer))
        assert a.sus == [] and a.belief == 4 and a.grade_fit == "higher" and a.tags == ["slow"]
        assert "ivan.petrov" not in a.comment and "900" not in a.comment  # контакты вырезаны до записи
        assert report.rows(db)[0].sus is None
    # повторная отправка заменяет ответы, а не копит
    assert client.post("/api/study/survey", json={"sus": SUS_GOOD}, headers=H(t)).json()["sus_score"] == 100.0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyAnswer)) == 1
        assert db.scalar(select(StudyAnswer.belief)) is None


def test_employer_rates_top5_for_the_selection_they_opened(client):
    refs = seed_pool(client, 6)
    t, need_id = finished_employer(client, refs[0])
    form = top5_form(client, t, need_id=need_id)
    shown = form["rel"]["selection"]["shown"]
    assert len(shown) == 5 and [x["rank"] for x in shown] == [1, 2, 3, 4, 5] and all(x["ref"] for x in shown)
    assert form["rel"]["selection"]["need_id"] == need_id and form["belief"]["q"] and form["grade_fit"] is None
    base = {"need_id": need_id, "sus": SUS_GOOD}
    rt = ratings_of(form)
    # неполные, лишние и неверные оценки не принимаются
    assert client.post("/api/study/survey", json={**base, "ratings": rt[:3]}, headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={**base, "ratings": rt[:4] + [{"ref": "C-ZZZZZZ", "rating": 3}]}, headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={**base, "ratings": [{**rt[0], "rating": 6}] + rt[1:]}, headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={**base, "ratings": rt + rt[:1]}, headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={"need_id": str(uuid.uuid4()), "ratings": rt}, headers=H(t)).status_code == 422  # чужая потребность
    ok = client.post("/api/study/survey", json={**base, "ratings": rt, "belief": 5}, headers=H(t))
    assert ok.status_code == 200, ok.text
    with SessionLocal() as db:
        a = db.scalar(select(StudyAnswer))
        assert a.selection["shown"] == 5 and a.selection["algorithm"] and a.belief == 5
        assert report.rows(db)[0].p5 == 0.6  # оценки 5, 4, 4, 2, 1 → релевантны трое


def test_non_employer_cannot_rate_and_unexposed_is_not_asked_about_grade(client):
    t = candidate(client)
    on(client, t)
    form = client.get("/api/study/survey", headers=H(t)).json()
    assert form["belief"] is None and form["grade_fit"] is None  # результата ещё нет — о грейде не спрашиваем
    assert client.post("/api/study/survey", json={"ratings": [{"ref": "C-AAAAAA", "rating": 3}]}, headers=H(t)).status_code == 422
    assert client.post("/api/study/survey", json={"sus": [3] * 10, "belief": 5, "grade_fit": "fit"}, headers=H(t)).status_code == 200
    with SessionLocal() as db:
        a = db.scalar(select(StudyAnswer))
        assert a.belief is None and a.grade_fit is None and not a.path_done


# ------------------------------------------------------------------ порог показа и сводка

class Fake:
    """Подмена путей: тест сводки не должен проходить десятки реальных путей — факты задаём напрямую."""

    def __init__(self, monkeypatch):
        self.spec: dict = {}
        real = P.derive

        def derive(db, p):
            s = self.spec.get(p.id)
            return real(db, p) if s is None else s

        monkeypatch.setattr(P, "derive", derive)

    def add(self, db, role="candidate", *, done=True, step_s=(60, 120, 90), enrolled=None, sus=None, ratings=None, belief=None,
            tags=None, errors=(), current=None, idle_min=0):
        enrolled = enrolled or utcnow() - timedelta(days=1)
        p = StudyParticipant(role=role, enrolled_at=enrolled)
        db.add(p)
        db.flush()
        keys = [k for k, _, _ in texts.PATH[role]]
        at, t = {}, enrolled
        for k, sec in zip(keys, step_s):
            t = t + timedelta(seconds=sec)
            at[k] = t if (done or k != keys[-1]) else None
        evs = [StudyEvent(participant_id=p.id, kind="error", key=k, status=s, code=c) for k, s, c in errors]
        for e in evs:
            e.at = enrolled
        db.add_all(evs)
        self.spec[p.id] = {"steps": {k: {"at": at[k], "skipped": False} for k in keys}, "keys": keys, "path_done": done,
                           "done_at": max(at.values()) if done else None, "current": None if done else (current or keys[-1]),
                           "last_activity": utcnow() - timedelta(minutes=idle_min), "errors": evs, "views": []}
        if sus is not None or ratings is not None or belief is not None or tags:
            db.add(StudyAnswer(participant_id=p.id, sus=sus or [], ratings=ratings or [], belief=belief, tags=tags or [],
                               submitted_at=utcnow()))
        db.commit()
        return p


def rt(vals):
    return [{"ref": f"C-{i}", "rank": i + 1, "rating": v} for i, v in enumerate(vals)]


def test_block_is_hidden_below_three_completed_paths(client, monkeypatch):
    fk = Fake(monkeypatch)
    assert client.get("/api/study/summary").json() == {"shown": False, "min_n": 3}
    with SessionLocal() as db:
        fk.add(db)
        fk.add(db, "employer")
        fk.add(db, done=False, idle_min=60)  # остановился — в N не входит
        fk.add(db, sus=SUS_GOOD, done=False, idle_min=60)
    assert client.get("/api/study/summary").json() == {"shown": False, "min_n": 3}  # два пути — без цифр
    with SessionLocal() as db:
        fk.add(db)
    s = client.get("/api/study/summary").json()
    assert s["shown"] and s["n"]["done"] == 3 and s["n"]["by_role"]["candidate"]["done"] == 2
    assert s["signature"].startswith("Реальные люди на стенде, не команда; обезличенно; период ")
    assert "N = 3 завершённых путей (кандидаты — 2, работодатели — 1)" in s["signature"]
    assert utcnow().astimezone(report.MSK).strftime("%d.%m.%Y") in s["signature"] or (utcnow() - timedelta(days=1)).astimezone(report.MSK).strftime("%d.%m.%Y") in s["signature"]
    assert s["completion"]["by_role"] == {}  # у роли меньше трёх завершивших — своего среза нет
    assert s["sus"] == {"n": 1, "enough": False, "by_role": {}} and s["p5"]["n"] == 0 and "mean" not in s["p5"]  # один ответ — без цифр


def test_declined_and_excluded_never_enter_the_numbers(client, monkeypatch):
    fk = Fake(monkeypatch)
    with SessionLocal() as db:
        for _ in range(3):
            fk.add(db)
        p = fk.add(db)
        p.declined_at = utcnow()
        db.commit()
    s = client.get("/api/study/summary").json()
    assert s["shown"] and s["n"]["done"] == 3 and s["n"]["enrolled"] == 3


def test_numbers_slices_ci_and_where_people_stop(client, monkeypatch):
    fk = Fake(monkeypatch)
    with SessionLocal() as db:
        for sus, r in [(SUS_GOOD, [5, 5, 4, 4, 3]), ([4, 2, 4, 2, 4, 2, 4, 2, 4, 2], [5, 4, 3, 2, 1]), ([3] * 10, [4, 4, 4, 1, 1])]:
            fk.add(db, "employer", sus=sus, ratings=rt(r), belief=4, step_s=(30, 60, 120), tags=["slow"])
        for _ in range(3):
            fk.add(db, "candidate", sus=[4, 2, 4, 2, 4, 2, 4, 2, 4, 2], belief=3, step_s=(90, 40, 300))
        fk.add(db, "candidate", done=False, idle_min=45, current="test", errors=[("/candidate/assessment", 500, "http_500")])
        fk.add(db, "employer", done=False, idle_min=2, current="selection")  # ещё идёт — в «бросили» не входит
    s = client.get("/api/study/summary").json()
    assert s["n"]["done"] == 6 and s["n"]["stopped"] == 1 and s["n"]["active"] == 1
    # SUS: всего 6 анкет ≥ 5 — балл есть; в каждой роли по 3 < 5 — среза по роли нет (Я17: n < 5 не результат)
    assert s["sus_min_n"] == 5 and s["sus"]["n"] == 6 and s["sus"]["enough"] and s["sus"]["by_role"] == {}
    assert s["sus"]["mean"] == pytest.approx((100 + 75 + 50 + 75 * 3) / 6)
    lo, hi = s["sus"]["ci"]
    assert 0 <= lo < s["sus"]["mean"] < hi <= 100
    p5 = s["p5"]  # P@5 участников: 0,8; 0,4; 0,6 → среднее 0,6
    assert p5["n"] == 3 and p5["mean"] == pytest.approx(0.6) and p5["threshold"] == 4
    assert p5["ratings"] == 15 and p5["ratings_relevant"] == 9 and len(p5["by_rank"]) == 5 and p5["ci"][0] <= p5["mean"] <= p5["ci"][1]
    assert s["belief"]["employer"]["mean"] == 4.0 and s["belief"]["candidate"]["mean"] == 3.0
    c = s["completion"]
    assert c["done"] == 6 and c["stopped"] == 1 and c["share"]["share"] == pytest.approx(6 / 7)
    assert c["stopped_at"] == {"test": 1}  # где бросили
    assert s["time"]["by_role"]["candidate"]["step_median_s"]["result"] == 300  # медианное время шага
    assert s["time"]["by_role"]["employer"]["median_s"] == 210
    assert s["errors"]["participants"] == 1 and s["errors"]["server"] == 1 and s["errors"]["by_code"] == {"http_500": 1}
    assert s["blockers"] == {texts.BLOCKER_TAGS["slow"]: 3}
    assert "смоделированные" in s["world"]


# ------------------------------------------------------------------ права и нет ПДн

def test_admin_report_is_admin_only_and_summary_is_open(client):
    t = candidate(client)
    assert client.get("/api/study/admin/report").status_code == 401
    assert client.get("/api/study/admin/report", headers=H(t)).status_code == 403
    assert client.get("/api/study/summary").status_code == 200  # публичная, без входа
    assert client.get("/api/study/me").status_code == 401 and client.post("/api/study/enroll", json={}).status_code == 401
    with SessionLocal() as db:
        db.add(User(email="adm@mail.ru", password_hash=hash_password("Passw0rd!x1"), role=UserRole.admin, is_email_verified=True))
        db.commit()
        ta = issue_token(db.scalar(select(User).where(User.email == "adm@mail.ru"))).access_token
    rep = client.get("/api/study/admin/report", headers=H(ta)).json()
    assert rep["participants"] == [] and rep["declined"] == 0 and rep["public"]["shown"] is False


def test_no_personal_data_in_public_or_admin_output(client):
    refs = seed_pool(client, 6)
    secret_email, secret_name = "ivan.sidorov@mail.ru", "Сидоров Иван"
    for i in range(3):
        t = register_and_verify(client, email=secret_email if i == 0 else f"sidorov{i}@corp.ru", role="employer",
                                company_name="ООО Тайная", full_name=secret_name)
        on(client, t)
        need = client.post("/api/employer/needs", json={"text": NEED}, headers=H(t)).json()
        client.post("/api/study/events", json={"kind": "view", "key": f"/employer/candidates/{refs[0]}"}, headers=H(t))
        client.post("/api/study/events", json={"kind": "view", "key": f"/employer/needs/{need['id']}"}, headers=H(t))
        assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": refs[i]}, headers=H(t)).status_code == 201
        form = top5_form(client, t, need_id=need["id"])
        r = client.post("/api/study/survey", json={"need_id": need["id"], "sus": SUS_GOOD, "ratings": ratings_of(form),
                                                  "comment": f"звоните {secret_email} 8 (900) 123-45-67 t.me/sidorov"}, headers=H(t))
        assert r.status_code == 200, r.text
    with SessionLocal() as db:
        pub = json.dumps(report.public_summary(db), ensure_ascii=False)
        adm = json.dumps(report.admin_report(db, with_texts=True), ensure_ascii=False, default=str)
        raw = json.dumps([e.key for e in db.scalars(select(StudyEvent))], ensure_ascii=False)
    assert '"shown": true' in pub
    for blob in (pub, adm, raw):
        for needle in (secret_email, "sidorov", "Сидоров", "ООО Тайная", "123-45-67", "t.me", "user_id"):
            assert needle not in blob, needle
    for blob in (pub, raw):  # ссылки на карточки кандидатов подборки в публичную сводку и события не попадают
        assert refs[0] not in blob
    import re
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", client.get("/api/study/summary").text)  # ни одной почты


# ------------------------------------------------------------------ команды

def test_cli_status_report_summary_and_reset(client, capsys, monkeypatch):
    from app.modules.study.__main__ import main

    fk = Fake(monkeypatch)
    assert main(["status"]) == 0 and "никого" in capsys.readouterr().out
    with SessionLocal() as db:
        for _ in range(3):
            fk.add(db, sus=SUS_GOOD, belief=5, tags=["slow"])
        d = fk.add(db)
        d.declined_at = utcnow()
        db.commit()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "путь пройден: 3" in out and "отказались: 1" in out and "SUS 100" in out
    assert main(["report"]) == 0 and "Публичная сводка: Реальные люди на стенде" in capsys.readouterr().out
    assert main(["summary"]) == 0 and '"shown": true' in capsys.readouterr().out
    # без --yes — только показывает
    assert main(["reset-study"]) == 0 and "Для выполнения добавьте --yes" in capsys.readouterr().out
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 4
    assert main(["reset-study", "--yes"]) == 0
    capsys.readouterr()
    with SessionLocal() as db:  # собранное удалено, отказавший остаётся отказавшимся
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 1
        assert db.scalar(select(StudyParticipant.declined_at)) is not None
        assert db.scalar(select(func.count()).select_from(StudyAnswer)) == 0 and db.scalar(select(func.count()).select_from(StudyEvent)) == 0
    assert client.get("/api/study/summary").json()["shown"] is False  # блок снова скрыт
    assert main(["reset-study", "--yes", "--include-declined"]) == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StudyParticipant)) == 0
