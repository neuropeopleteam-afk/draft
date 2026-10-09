"""И26: две попытки теста рядом — сравнение (повторы, Δθ и погрешность, форматы), API кандидата и работодателя,
матрица прав (чужие попытки — 404), демо-повтор жюри, готовая пара у демо-персоны."""
from __future__ import annotations

from datetime import timedelta
import uuid

import pytest
from sqlalchemy import select, update

from app.core.db import SessionLocal, utcnow
from app.core.enums import TestSessionStatus as SessionStatus, UserRole
from app.modules.assessment.attempts import attempt_view, compare, overlap
from app.modules.assessment.models import TestSession as Session_
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, ONBOARDING, candidate_with_category, employer, make_demo, my_ref, pass_test


def _it(fam: str, var: str, canary: bool = False, done: bool = True) -> dict:
    return {"family_id": fam, "variant_id": var, "seed": 1, "canary": canary, "done": done}


def _ts(items, theta=0.85, se=0.40, *, mode="full", prior=None, confirmed=True, provisional=False, grade="middle",
        direction="backend", subpool=0, time_s=900.0, correct=7, answered=10, accepted_lower=None) -> Session_:
    now = utcnow()
    st = {"items": items, "subpool": subpool, "mode": mode}
    if prior is not None:
        st["prior"] = prior
    return Session_(
        id=uuid.uuid4(), user_id=uuid.uuid4(), direction_id=direction, claimed_grade_id=grade,
        status=SessionStatus.finished, form_seed=1, is_sandbox=False, theta=theta, theta_se=se,
        started_at=now - timedelta(minutes=20), finished_at=now,
        result={"mode": mode, "state": st,
                "engine_result": {"theta": theta, "se": se, "confirmed": confirmed, "provisional": provisional,
                                  "answered": answered, "correct": correct,
                                  "details": {"time_used_s": time_s, "subpool": subpool}},
                "outcome": {"grade": grade if confirmed else None, "accepted_lower": accepted_lower}})


# ------------------------------------------------------------------ чистое сравнение

def test_overlap_counts_new_scored_non_canary_items():
    a = attempt_view(_ts([_it("f1", "v1"), _it("f2", "v2"), _it("f3", "v3"), _it("canary-fam-x", "canary-var-x", canary=True),
                          _it("f9", "v9", done=False)]))
    b = attempt_view(_ts([_it("f1", "v1b"), _it("f4", "v4"), _it("f5", "v5"), _it("canary-fam-x", "canary-var-x", canary=True)],
                         subpool=1))
    assert a["n_items"] == 3 and b["n_items"] == 3  # канарейка и неоценённое задание не считаются
    ov = overlap(a, b)
    assert ov["repeated_families"] == 1 and ov["n_families_second"] == 3 and ov["share_families"] == pytest.approx(1 / 3, abs=1e-3)
    assert ov["repeated_variants"] == 0 and ov["share_variants"] == 0 and not ov["same_subpool"]
    # наружу множества семейств и вариантов (в том числе контрольных) не уходят
    c = compare(a, b)
    assert "families" not in c["first"] and "variants" not in c["second"]
    assert "canary-fam-x" not in str(c) and "canary-var-x" not in str(c)


def test_compare_within_error_and_formats():
    a = attempt_view(_ts([_it("f1", "v1")], theta=0.85, se=0.40, time_s=1110))
    b = attempt_view(_ts([_it("f2", "v2")], theta=1.27, se=0.49, time_s=840, subpool=1, correct=8))
    c = compare(a, b)
    assert c["second"]["theta_text"] == "+1,27 ± 0,49" and c["first"]["theta_text"] == "+0,85 ± 0,40"
    d = c["delta"]
    assert d["theta"] == pytest.approx(0.42) and d["se_diff"] == pytest.approx((0.4 ** 2 + 0.49 ** 2) ** 0.5, abs=1e-4)
    assert d["within_error"] is True and d["accuracy"] == pytest.approx(0.1) and d["time_s"] == pytest.approx(-270)
    txt = {x["id"]: x["text"] for x in c["changes"]}
    assert "+0,85 ± 0,40 → +1,27 ± 0,49, разница +0,42" in txt["theta"] and "в пределах погрешности" in txt["theta"]
    assert "±1,24 при 95 %" in txt["theta"]
    assert "70 % → 80 %" in txt["accuracy"] and "сравнивают θ" in txt["accuracy"]
    assert txt["time"] == "19 мин → 14 мин." and "Повторов нет" in txt["overlap"]
    assert "Без изменений" in txt["status"] and "." not in d.get("theta_text", "")  # десятичная запятая


def test_compare_outside_error_status_change_and_minus_sign():
    a = attempt_view(_ts([_it("f1", "v1")], theta=-0.5, se=0.2, confirmed=False, grade="middle"))
    b = attempt_view(_ts([_it("f2", "v2")], theta=1.0, se=0.2, confirmed=True, grade="middle", subpool=1))
    c = compare(a, b)
    assert c["delta"]["within_error"] is False and c["delta"]["status_changed"] and c["delta"]["grade_changed"]
    txt = {x["id"]: x["text"] for x in c["changes"]}
    assert "−0,50 ± 0,20" in txt["theta"] and "больше погрешности" in txt["theta"] and "уровень выше" in txt["theta"]
    assert "не подтверждён" in txt["status"] and "подтверждён (Middle)" in txt["status"]


def test_compare_confirm_mode_prior_answers_are_not_repeats():
    first = [_it("f1", "v1"), _it("f2", "v2")]
    a = attempt_view(_ts(first, theta=-0.2, se=0.45, confirmed=False, provisional=True, grade="junior"))
    b = attempt_view(_ts([_it("f7", "v7"), _it("f8", "v8")], prior=first, mode="confirm", theta=-0.1, se=0.33,
                         grade="junior"))
    assert b["prior_items"] == 2 and b["n_items"] == 2 and b["mode_title"] == "дотестирование"
    c = compare(a, b)
    assert c["overlap"]["repeated_families"] == 0
    assert "2 ответов прошлой попытки перенесены" in next(x["text"] for x in c["changes"] if x["id"] == "overlap")
    assert a["status"] == "provisional" and a["grade_after"] == "junior"


def test_accepted_lower_status_and_express_note():
    a = attempt_view(_ts([_it("f1", "v1")], confirmed=False, accepted_lower="junior", mode="express"))
    b = attempt_view(_ts([_it("f2", "v2")], subpool=1))
    assert a["status"] == "accepted_lower" and a["grade_after"] == "junior"
    ids = [x["id"] for x in compare(a, b)["changes"]]
    assert "mode" in ids


def test_different_directions_rejected():
    from fastapi import HTTPException

    a = attempt_view(_ts([_it("f1", "v1")], direction="backend"))
    b = attempt_view(_ts([_it("f1", "v1")], direction="frontend"))
    with pytest.raises(HTTPException) as e:
        compare(a, b)
    assert e.value.status_code == 422


# ------------------------------------------------------------------ API кандидата: демо-повтор и права

def _demo_second_attempt(client, t, email="cand@example.com"):
    make_demo(email)
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    return pass_test(client, t, "middle")


def test_candidate_attempts_rules_and_demo_retake(client):
    t = candidate_with_category(client)
    r = client.get("/api/assessment/attempts", headers=H(t))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["direction"] == "backend" and len(d["attempts"]) == 1 and d["comparison"] is None
    # обычный кандидат: правило 90 дней как есть — повтор сейчас недоступен, с причиной
    assert d["can_retake_now"] is False and "90 дней" in d["retake_reason"] and not d["sandbox"]
    # демо-режим жюри: повтор сразу, с пометкой
    make_demo("cand@example.com")
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    d = client.get("/api/assessment/attempts", headers=H(t)).json()
    assert d["sandbox"] and d["can_retake_now"] and d["retake_grade"] == "middle" and "демо-режиме" in d["note"]
    assert pass_test(client, t, "middle")["confirmed"]
    d = client.get("/api/assessment/attempts", headers=H(t)).json()
    assert len(d["attempts"]) == 2
    c = d["comparison"]
    assert c["first"]["id"] == d["attempts"][0]["id"] and c["second"]["id"] == d["attempts"][1]["id"]
    assert c["second"]["is_sandbox"] and c["overlap"]["engine"] == "stub"
    # заглушка выдаёт один и тот же набор — честно 100 %
    assert c["overlap"]["share_families"] == 1.0
    assert any(x["id"] == "sandbox" for x in c["changes"])
    assert c["second"]["theta_text"].startswith(("+", "−")) and "," in c["second"]["theta_text"]
    # явная пара a/b — в любом порядке, итог по времени
    a, b = d["attempts"][0]["id"], d["attempts"][1]["id"]
    r = client.get(f"/api/assessment/attempts?a={b}&b={a}", headers=H(t))
    assert r.status_code == 200 and r.json()["comparison"]["first"]["id"] == a
    assert client.get(f"/api/assessment/attempts?a={a}&b={a}", headers=H(t)).status_code == 422
    assert client.get(f"/api/assessment/attempts?a={a}", headers=H(t)).status_code == 422


def test_candidate_attempts_access_matrix(client):
    t1 = candidate_with_category(client)
    _demo_second_attempt(client, t1)
    mine = client.get("/api/assessment/attempts", headers=H(t1)).json()["attempts"]
    t2 = register_and_verify(client, email="other@example.com")
    client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t2))
    # чужие попытки — 404, как у остальных сессий теста
    r = client.get(f"/api/assessment/attempts?a={mine[0]['id']}&b={mine[1]['id']}", headers=H(t2))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "session_not_found"
    r = client.get(f"/api/assessment/attempts?a={uuid.uuid4()}&b={mine[1]['id']}", headers=H(t1))
    assert r.status_code == 404
    assert client.get("/api/assessment/attempts", headers=H(t2)).json()["attempts"] == []
    assert client.get("/api/assessment/attempts").status_code == 401
    te = employer(client)
    assert client.get("/api/assessment/attempts", headers=H(te)).status_code == 403


def test_unfinished_attempt_is_409(client):
    t = candidate_with_category(client)
    make_demo("cand@example.com")
    client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t))
    done = client.get("/api/assessment/attempts", headers=H(t)).json()["attempts"][0]["id"]
    s = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t)).json()
    r = client.get(f"/api/assessment/attempts?a={done}&b={s['session_id']}", headers=H(t))
    assert r.status_code == 409


# ------------------------------------------------------------------ работодатель: согласие и видимость

def _staff_token(email: str, role) -> str:
    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.auth.service import issue_token

    with SessionLocal() as db:
        u = User(email=email, password_hash=hash_password("Attempts-pass-123"), role=role, is_email_verified=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        return issue_token(u).access_token


def test_employer_attempts_consent_and_access(client):
    tc = candidate_with_category(client)
    te = employer(client)
    ref = my_ref(client, tc)
    d = client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(te)).json()
    assert d["available"] is False and d["reason"] == "single_attempt" and d["n_attempts"] == 1
    _demo_second_attempt(client, tc)
    r = client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(te))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["available"] and d["n_attempts"] == 2 and d["comparison"]["delta"]["theta"] is not None
    # работодателю — без идентификаторов сессий кандидата и без внутренних множеств заданий
    assert "id" not in d["comparison"]["first"] and all("id" not in x for x in d["attempts"])
    assert "'families'" not in str(d) and "'variants'" not in str(d)
    # согласие: кандидат скрыл сравнение — работодатель видит только «скрыто»
    opts = client.get("/api/me/onboarding", headers=H(tc)).json()["options"]["privacy_fields"]
    assert {"id": "show_attempts", "title": "Сравнение попыток теста"} in opts
    assert client.put("/api/me/privacy", json={"privacy": {"show_attempts": False}}, headers=H(tc)).status_code == 200
    d = client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(te)).json()
    assert d == {"available": False, "reason": "hidden_by_candidate", "text": "Кандидат скрыл сравнение попыток теста"}
    # профиль скрыт — 404, как у карточки
    assert client.delete("/api/me/consents/publication", headers=H(tc)).status_code == 200
    assert client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(te)).status_code == 404
    assert client.get(f"/api/employer/candidates/nope/attempts", headers=H(te)).status_code == 404
    # роли: аноним 401, кандидат и эксперт — 403
    assert client.get(f"/api/employer/candidates/{ref}/attempts").status_code == 401
    assert client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(tc)).status_code == 403
    expert = _staff_token("attempts-expert@example.org", UserRole.expert)
    assert client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(expert)).status_code == 403


# ------------------------------------------------------------------ банк заданий: параллельная форма

@pytest.fixture
def bank(monkeypatch):
    from app.core.config import get_settings
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.grader import GradeOutcome

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm"))


def test_bank_retake_has_no_repeated_families(client, bank):
    from app.modules.jury.seed import run_demo_test
    from app.modules.assessment.attempts import finished_attempts
    from app.modules.auth.models import User

    t = register_and_verify(client, email="bank-attempts@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    make_demo("bank-attempts@example.com")
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "bank-attempts@example.com"))
        for k in range(3):
            run_demo_test(db, uid, "middle", 1.05, 7701 + k)
        rows = finished_attempts(db, uid, "backend")
        v = [attempt_view(x) for x in rows]
    assert len(v) == 3 and all(x["engine"] == "bank" and x["n_items"] >= 5 for x in v)
    c12 = compare(v[0], v[1])
    # повтор — другой субпул: семейства почти не повторяются (дотестирование первой попытки может взять семейство
    # второго субпула — в синтетике так в ~7 % пар, одно семейство), варианты — новые всегда
    assert c12["overlap"]["share_families"] <= 0.15 and c12["overlap"]["repeated_variants"] == 0
    assert v[0]["subpool"] != v[1]["subpool"]
    # третья попытка — снова субпул первой (субпулов два), но семейства всех прошлых попыток исключены (И26, 09.10);
    # повтор возможен только запасным путём LRU, когда новых семейств нет, и всегда с новым вариантом
    c23, c13 = compare(v[1], v[2]), compare(v[0], v[2])
    assert c23["overlap"]["repeated_variants"] == 0 and c13["overlap"]["repeated_variants"] == 0
    assert c13["overlap"]["repeated_families"] <= v[2]["lru_repeats"]
    assert v[2]["subpool"] == v[0]["subpool"]
    d = client.get("/api/assessment/attempts", headers=H(t)).json()
    assert len(d["attempts"]) == 3 and d["comparison"]["second"]["id"] == d["attempts"][2]["id"]
    ov = next(x["text"] for x in d["comparison"]["changes"] if x["id"] == "overlap")
    assert ("Повторов нет" in ov) == (d["comparison"]["overlap"]["repeated_families"] == 0)


# ------------------------------------------------------------------ демо-персона жюри: готовая пара

def test_jury_persona_has_ready_pair_for_candidate_and_employer(client):
    j = client.post("/api/jury/login", json={"persona": "candidate", "scenario": "new"})
    assert j.status_code == 200, j.text
    t, sid = j.json()["access_token"], j.json()["scenario"]
    d = client.get("/api/assessment/attempts?direction=backend", headers=H(t)).json()
    assert len(d["attempts"]) >= 2 and d["comparison"] is not None
    assert d["sandbox"] and d["can_retake_now"] and d["retake_grade"] == "middle"
    c = d["comparison"]
    assert c["overlap"]["engine"] == "bank" and c["overlap"]["share_families"] <= 0.15
    assert c["overlap"]["repeated_variants"] == 0
    assert c["second"]["status"] == "confirmed" and c["second"]["is_sandbox"]
    # грейд Марии после пары — по-прежнему Backend · Middle
    st = client.get("/api/assessment/status?direction=backend", headers=H(t)).json()
    assert st["current"]["category_id"] == "backend.middle"
    e = client.post("/api/jury/login", json={"persona": "employer", "scenario": sid}).json()["access_token"]
    ref = my_ref(client, t)
    r = client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(e))
    assert r.status_code == 200 and r.json()["available"], r.text
    # кандидат песочницы не существует для работодателя другой песочницы
    other = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"}).json()["access_token"]
    assert client.get(f"/api/employer/candidates/{ref}/attempts", headers=H(other)).status_code == 404


# ------------------------------------------------------------------ /validation: доля повторов

def test_validation_attempts_repeat_live_and_synthetic(client, bank):
    from app.modules.auth.models import User
    from app.modules.jury.seed import run_demo_test
    from app.modules.validation.attempts_repeat import pair_stats

    assert pair_stats([({"a", "b"}, {"b", "c"}), ({"x"}, {"y", "z"})]) == {
        "n_pairs": 2, "share_families": 0.25, "share_pairs_with_repeat": 0.5, "mean_repeated": 0.5, "max_share": 0.5}
    r = client.get("/api/validation/attempts-repeat")
    assert r.status_code == 200
    d = r.json()
    syn = d["synthetic"]
    # сохранённая синтетика: подпись мира и условия, четыре попытки «после» и три «до» на одном мире, варианты — новые
    assert syn["signature"]["seed"] == 20261006 and syn["signature"]["config_hash"] and syn["signature"]["world"]
    p, b = syn["pairs"], syn["before"]
    assert set(p) == {"second_vs_first", "third_vs_second", "third_vs_first", "fourth_vs_first",
                      "fourth_vs_any_previous"}
    assert set(b) == {"second_vs_first", "third_vs_second", "third_vs_first"}
    assert p["second_vs_first"]["share_families"] <= b["second_vs_first"]["share_families"] < 0.05  # параллельная форма
    # третья против первой: исключаются все прошлые попытки — повторов заметно меньше (остаток — малый банк, LRU)
    assert p["third_vs_first"]["share_families"] < b["third_vs_first"]["share_families"] - 0.2
    assert syn["directions"]["backend"]["after"]["third_vs_first"]["share_families"] < 0.15
    # test–retest первых двух попыток парно «до» и «после» — те же цифры (/validation не сдвигается)
    rt = syn["retest_check"]
    assert abs(rt["after"]["grade_kappa_quadratic"] - rt["before"]["grade_kappa_quadratic"]) < 0.02
    assert abs(rt["after"]["icc_theta"] - rt["before"]["icc_theta"]) < 0.02 and rt["same_share"] > 0.8
    assert syn["variants"]["share"] == 0.0 and syn["config"]["subpools"] == 2
    assert d["live"]["n_pairs"] == 0 and "по базе" in d["live"]["conditions"]
    # живая строка: две попытки банка одного человека
    t = register_and_verify(client, email="live-repeat@example.com")
    client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t))
    make_demo("live-repeat@example.com")
    client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t))
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "live-repeat@example.com"))
        run_demo_test(db, uid, "middle", 0.8, 8801)
        run_demo_test(db, uid, "middle", 0.8, 8802)
    live = client.get("/api/validation/attempts-repeat").json()["live"]
    assert live["n_pairs"] == 1 and live["n_people"] == 1 and live["families"]["share_families"] <= 0.15
    assert live["variants"]["share_families"] == 0.0
