"""«Junior (предварительно)» у нижнего порога: правило, 90 дней, без принудительного понижения, подтверждение
(повторный тест, дотестирование банка, зонд/кубок), ранжирование ниже подтверждённого, карточка работодателя."""
from datetime import timedelta
import random
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal, as_aware, utcnow
from app.modules.assessment import engine as em
from tests.conftest import register_and_verify
from tests.test_day2_rules import ONBOARDING, H, employer, pass_test


# ---------------------------------------------------------------- правило (банк и заглушка)

def test_decide_provisional_rule():
    from assessment_bank.psychometrics import decide

    d = decide(-1.2, 0.4, "junior")  # P(θ ≥ −1) = Φ(−0,5) ≈ 0,31: не подтверждён, но и не доказанно ниже
    assert not d.confirmed and d.assigned == "none" and d.provisional and d.provisional_reason == "uncertain"
    assert 0.30 < d.p_claimed < 0.32
    d = decide(-0.9, 0.5, "junior")  # θ̂ выше порога, точности не хватило (P ≈ 0,58 < 0,8)
    assert not d.confirmed and d.provisional and d.provisional_reason == "precision"
    d = decide(-1.7, 0.3, "junior")  # P ≈ 0,01: уровень ниже доказан
    assert not d.confirmed and not d.provisional
    d = decide(-0.4, 0.3, "junior")  # подтверждён — не предварительный
    assert d.confirmed and not d.provisional
    # заявившему Middle Junior не присваивается даже предварительно (нет принудительного понижения)
    d = decide(-0.6, 0.4, "middle")
    assert not d.confirmed and not d.provisional and d.retake_lower == "junior"
    # прежнее правило — для сравнения до/после
    assert not decide(-1.2, 0.4, "junior", provisional_level=None).provisional
    # граница: θ̂ + 1,28·SE ≈ порог
    assert decide(-1.0 - 1.30 * 0.4, 0.4, "junior").provisional is False
    assert decide(-1.0 - 1.26 * 0.4, 0.4, "junior").provisional is True


def test_stub_grade_decision_provisional():
    dec = em.grade_decision(-1.2, 0.4, "junior")
    assert dec["provisional"] and dec["provisional_reason"] == "uncertain" and not dec["confirmed"]
    assert not em.grade_decision(-1.2, 0.4, "middle")["provisional"]
    assert not em.grade_decision(-1.8, 0.3, "junior")["provisional"]


def test_apply_result_provisional_cases():
    from app.modules.assessment.rules import apply_result

    now = utcnow()
    o = apply_result(None, "junior", False, now, False, provisional=True)
    assert o.changed and o.reason == "provisional" and o.provisional and o.locked_until is None
    # подтверждение того же грейда — не смена грейда: 90 дней от даты попадания в категорию
    since = now - timedelta(days=10)
    o = apply_result("junior", "junior", True, now, False, current_provisional=True, provisional_since=since)
    assert not o.changed and o.status_changed and o.reason == "confirmed"
    assert abs((o.locked_until - (since + timedelta(days=90))).total_seconds()) < 1
    # прошло больше 90 дней — подтверждение без нового периода
    o = apply_result("junior", "junior", True, now, False, current_provisional=True,
                     provisional_since=now - timedelta(days=120))
    assert o.status_changed and o.locked_until is None
    # неудача статус не снимает
    o = apply_result("junior", "junior", False, now, False, provisional=False, current_provisional=True)
    assert not o.changed and not o.status_changed and o.provisional
    # предварительный Junior → подтверждённый Middle: первое подтверждённое присвоение (с 90 днями)
    o = apply_result("junior", "middle", True, now, False, current_provisional=True)
    assert o.changed and o.reason == "initial" and o.locked_until is not None
    # подтверждённую категорию другого направления предварительный результат не заменяет
    o = apply_result(None, "junior", False, now, False, provisional=True, confirmed_elsewhere="frontend.middle")
    assert not o.changed and o.new_grade is None


# ---------------------------------------------------------------- сценарий через API (заглушка с заданной θ)

@pytest.fixture
def theta(monkeypatch):
    box = {"v": (-1.2, 0.4)}
    monkeypatch.setattr(em, "eap_theta", lambda responses: box["v"])
    return box


def _junior(client, theta, email="jun@example.com"):
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json={**ONBOARDING, "experience_years": 1}, headers=H(t)).status_code == 200
    theta["v"] = (-1.2, 0.4)
    res = pass_test(client, t, "junior")
    return t, res


def _age_sessions(email: str, days: int = 31) -> None:
    """Сдвигает завершённые сессии кандидата в прошлое: правило 30 дней после неподтверждённой попытки (И2) истекло."""
    from app.modules.assessment.models import TestSession
    from app.modules.auth.models import User

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == email))
        for ts in db.scalars(select(TestSession).where(TestSession.user_id == uid, TestSession.finished_at.is_not(None))):
            ts.finished_at = ts.finished_at - timedelta(days=days)
            ts.started_at = ts.started_at - timedelta(days=days)
        db.commit()


def _profile(email):
    from app.modules.auth.models import User
    from app.modules.profiles.models import CandidateProfile

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        return db.get(CandidateProfile, u.id), u.id


def test_api_provisional_assigned_visible_and_confirmed(client, theta):
    t, res = _junior(client, theta)
    assert not res["confirmed"] and res["provisional"] and res["category_provisional"]
    assert res["category_id"] == "backend.junior" and res["locked_until"] is None
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["current"]["provisional"] and st["current"]["category_title"].endswith("(предварительно)")
    assert not st["lock_active"] and st["grade_history"][0]["reason"] == "provisional"
    pv = st["provisional"]
    assert pv["p_pct"] == 31 and pv["attempts_left"] == 2 and pv["hint"]
    assert not pv["can_confirm_test"]  # заглушка — дотестирование только на банке; есть подсказка
    assert pv["confirm_unavailable_reason"]

    # работодатель видит карточку с пометкой и уровнем доказанности, подсчёт «предварительно» в категории
    e = employer(client)
    r = client.get("/api/employer/candidates", params={"category": "backend.junior"}, headers=H(e)).json()
    assert r["total"] == 1 and r["provisional"] == 1
    card = r["items"][0]
    assert card["category"]["provisional"] and card["grade_title"] == "Junior (предварительно)"
    assert card["provisional"]["p_pct"] == 31
    assert client.get("/api/employer/candidates", params={"category": "backend.junior", "confirmed": True},
                      headers=H(e)).json()["total"] == 0
    cats = {c["id"]: c for c in client.get("/api/employer/categories", headers=H(e)).json()}
    assert cats["backend.junior"]["provisional"] == 1

    # повторный тест не подтвердил и доказал «ниже» — статус не снимается (принудительного понижения нет),
    # но работодатель видит актуальную оценку
    theta["v"] = (-1.8, 0.3)
    res = pass_test(client, t, "junior")
    assert not res["confirmed"] and res["category_provisional"] and res["category_id"] == "backend.junior"
    card = client.get("/api/employer/candidates", params={"category": "backend.junior"}, headers=H(e)).json()["items"][0]
    assert card["provisional"]["p_pct"] == 0 and card["provisional"]["reason"] == "below"

    # неподтверждённая полная попытка на Junior закрывает полный повтор на 30 дней (И2; консилиум 07.10, 7.3б) —
    # сам исход «предварительно» повтор не закрывает (7.3а)
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "junior"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "retake_cooldown"
    _age_sessions("jun@example.com")
    # подтверждение — не смена грейда: причина confirmed, грейд тот же, 90 дней — от даты попадания в категорию
    theta["v"] = (-0.5, 0.3)
    res = pass_test(client, t, "junior")
    assert res["confirmed"] and not res["category_provisional"] and res["status_changed"] and not res["grade_changed"]
    st = client.get("/api/assessment/status", headers=H(t)).json()
    h = st["grade_history"][0]
    assert h["reason"] == "confirmed" and h["from"] == h["to"] == "junior"
    assert st["provisional"] is None and not st["current"]["provisional"]
    p, _ = _profile("jun@example.com")
    first = st["grade_history"][-1]
    assert first["reason"] == "provisional"
    lock = as_aware(p.grade_locked_until)
    assert lock and abs((lock - (as_aware(__import__("datetime").datetime.fromisoformat(first["at"]))
                                 + timedelta(days=90))).total_seconds()) < 5
    card = client.get("/api/employer/candidates", params={"category": "backend.junior"}, headers=H(e)).json()["items"][0]
    assert not card["category"]["provisional"] and card["provisional"] is None


def test_api_middle_claim_never_provisional(client, theta):
    t = register_and_verify(client, email="mid@example.com")
    client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t))
    theta["v"] = (-1.2, 0.4)
    res = pass_test(client, t, "middle")
    assert not res["confirmed"] and not res["provisional"] and res["category_id"] is None


def test_provisional_then_middle_is_initial_assignment(client, theta):
    t, _ = _junior(client, theta, "jm@example.com")
    theta["v"] = (0.6, 0.3)
    res = pass_test(client, t, "middle")
    assert res["confirmed"] and res["category_id"] == "backend.middle" and not res["category_provisional"]
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["grade_history"][0]["reason"] == "initial" and st["lock_active"]


def test_confirm_by_work_probe_and_cup(client, theta):
    from app.modules.assessment import provisional
    from app.modules.profiles.facts import load_bundles

    _junior(client, theta, "work@example.com")
    _, uid = _profile("work@example.com")
    with SessionLocal() as db:
        assert not provisional.confirm_by_work(db, uid, source="probe", ref="probe:x", ref_title="Задача", score=0.3)
        assert not provisional.confirm_by_work(db, uid, source="cup", ref="cup:x", ref_title="Кубок", score=0.9,
                                               direction="frontend")  # другое направление
        assert provisional.confirm_by_work(db, uid, source="probe", ref="probe:1", ref_title="Мини-API", score=0.7)
        db.commit()
        b = load_bundles(db, [uid])[uid]
        assert not b.provisional and b.test.value["confirmed_by"] == "probe"
        from app.modules.assessment.models import GradeHistory
        h = db.scalars(select(GradeHistory).where(GradeHistory.user_id == uid)
                       .order_by(GradeHistory.created_at.desc())).first()
        assert h.reason.value == "confirmed" and h.from_grade_id == h.to_grade_id == "junior"
        assert provisional.confirmed_by(b.test.value)["title"] == "зондом работодателя"


def test_ranking_provisional_below_confirmed_all_else_equal():
    from types import SimpleNamespace

    from app.modules.matching import ranking
    from app.modules.profiles.facts import Bundle

    def bundle(prov):
        p = SimpleNamespace(current_direction_id="backend", current_grade_id="junior",
                            current_category_id="backend.junior", grade_provisional=prov, work_format=None,
                            privacy={}, rating_score=None)
        test = SimpleNamespace(value={"theta": -0.9, "se": 0.4, "correct": 10, "answered": 18},
                               created_at=utcnow())
        return Bundle(profile=p, test=test)

    req = {"direction": "backend", "grade": "junior"}
    s1, c1, r1 = ranking.score_candidate(bundle(False), req)
    s2, c2, r2 = ranking.score_candidate(bundle(True), req)
    assert abs((s1 - s2) - 0.05) < 1e-9 and c2["provisional"] == 0.05 and c1["provisional"] == 0.0
    assert r2[0]["provisional"] and "предварительно" in r2[0]["text"]
    assert abs(bundle(False).strength() - bundle(True).strength() - 0.05) < 1e-9


# ---------------------------------------------------------------- короткое дотестирование (движок банка)

def test_bank_confirm_extension_reuses_prior_answers(monkeypatch):
    import math

    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.bank_engine import BankEngine
    from app.modules.assessment.grader import GradeOutcome
    from tests.test_bank_engine import oracle

    monkeypatch.setattr(be, "grade_open", lambda **k: GradeOutcome(
        status="scored", score=0.9 if len(k["answer"]) > 40 else 0.0, method="llm", model="test"))
    eng = BankEngine()

    def run(st, rnd, target):
        while True:
            item = eng.next_item(st)
            if item is None:
                break
            it = next(i for i in st["items"] if i["token"] == item.item_id)
            good = rnd.random() < (0.85 if it["theta_before"] < target else 0.3)
            assert eng.answer(st, item.item_id, oracle(it, item.step or 1, good), 1000, step=item.step).accepted
        return eng.finish(st)

    for seed in range(2, 12):
        rnd = random.Random(seed)
        st = eng.start(direction="backend", claimed_grade="junior", stack_tags=[], seed=seed)
        res = run(st, rnd, -1.0)
        if res.provisional:
            break
    else:
        pytest.skip("не нашли предварительный итог на 10 сидах")
    assert res.details["category"] == "backend.junior" and res.details["provisional"]["p"] >= 0.10
    prev = dict(st, final_theta=res.theta, final_se=res.se)
    st2 = eng.start(direction="backend", claimed_grade="junior", stack_tags=[], seed=seed + 100, confirm_from=prev,
                    previous_families=[])
    assert st2["mode"] == "confirm" and st2["prior"] and st2["cfg"]["cuts_only"] == "junior"
    assert all("key" not in i and "public" not in i for i in st2["prior"])
    res2 = run(st2, rnd, -0.8)
    new = [i for i in st2["items"] if i["done"] and not i["canary"]]
    assert 1 <= len(new) <= st2["cfg"]["ext_items"]
    assert not ({i["family_id"] for i in new} & {i["family_id"] for i in st2["prior"]})
    assert all(i["time_limit_s"] <= 300 for i in new)  # только короткие задания
    assert res2.details["mode"] == "confirm"
    assert res2.details["n_scored"] == len(new) + sum(1 for i in st2["prior"] if not i.get("canary"))
    assert res2.details["confirm"]["new_items"] == len(new)
    assert res2.confirmed or res2.provisional or res2.p_claimed < 0.10
    assert math.isfinite(res2.theta) and res2.se <= res.se + 0.05


def test_api_confirm_mode_with_bank(client, monkeypatch):
    """Дотестирование через API: только для предварительного статуса, не больше 2 попыток, не смена грейда."""
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment import service
    from app.modules.assessment.grader import GradeOutcome
    from app.modules.assessment.models import TestSession
    from tests.test_bank_engine import oracle

    monkeypatch.setattr(be, "grade_open", lambda **k: GradeOutcome(
        status="scored", score=0.9 if len(k["answer"]) > 40 else 0.0, method="llm", model="test"))
    # «Junior (предварительно)» и дотестирование — механика прежнего правила (posterior): по правилу SPRT
    # (поправка №2) её роль играет второй этап у спорного порога, и статуса «предварительно» не бывает — поэтому
    # тест закреплён за прежним правилом, как три теста дотестирования в test_two_stage (6dd4fb70d)
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "assessment_verdict_rule", "posterior")
    t = register_and_verify(client, email="bankjun@example.com")
    client.put("/api/me/onboarding", json={**ONBOARDING, "experience_years": 1}, headers=H(t))
    # первый тест — без дотестирования: сразу ли «предварительно», зависит от ответов; подбираем сид
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "junior", "mode": "confirm"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_provisional"
    _, uid = _profile("bankjun@example.com")
    for seed in range(2, 14):
        rnd = random.Random(seed)
        with SessionLocal() as db:
            ts = service.start_session(db, uid, "junior", "bank")
            while True:
                item = service.next_item(db, ts)
                if item is None:
                    break
                it = next(i for i in ts.result["state"]["items"] if i["token"] == item.item_id)
                good = rnd.random() < (0.85 if it["theta_before"] < -1.0 else 0.3)
                service.submit_answer(db, ts, item.item_id, oracle(it, item.step or 1, good), 1000, step=item.step)
            out = service.finish_session(db, ts)
        if out["category_provisional"]:
            break
        # итог зависит от состояния экспозиции банка (порядок тестов): подтверждённый грейд сбрасываем,
        # чтобы правило 90 дней не мешало следующей попытке подбора сида
        with SessionLocal() as db:
            from app.modules.profiles.models import CandidateProfile

            from app.modules.profiles.models import CandidateSpecialization

            p = db.get(CandidateProfile, uid)
            p.current_category_id = p.current_grade_id = p.current_direction_id = None
            p.grade_locked_until, p.grade_provisional = None, False
            for r in db.scalars(select(CandidateSpecialization).where(CandidateSpecialization.user_id == uid)):
                r.grade_id = r.category_id = r.locked_until = r.confirmed_at = None
                r.status = "declared"
            db.commit()
    else:
        pytest.skip("не нашли предварительный итог")
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["provisional"]["can_confirm_test"] and st["provisional"]["attempts_left"] == 2
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "junior", "mode": "confirm"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["mode"] == "confirm" and s["total"] <= 6 and s["answered"] == 0 and s["item"]["extension"]
    with SessionLocal() as db:
        ts = db.get(TestSession, uuid.UUID(s["session_id"]))
        assert ts.result["state"]["prior"] and (as_aware(ts.deadline_at) - utcnow()) <= timedelta(minutes=31)
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["provisional"]["attempts_left"] == 1 and st["active_mode"] == "confirm"


# ---------------------------------------------------------------- консилиум 07.10, п. 7.3 (слияние И1 × И2 × И13)

def test_provisional_accept_lower_intern_and_no_retake_lock(client, theta):
    """(в) у «Junior (предварительно)» доказанный Стажёр принимается без нового теста — предварительный грейд
    сравнивается как отсутствие категории; (а) исход «предварительно» не закрывает повтор на 30 дней."""
    theta["v"] = (-1.3, 0.3)  # P(θ ≥ −1,0) ≈ 16 % → предварительно; P(θ ≥ −1,75) ≈ 93 % → Стажёр доказан
    t, res = _junior(client, theta)
    assert res["provisional"] and res["category_provisional"] and res["category_id"] == "backend.junior"
    assert res["accept_lower_available"] and res["accept_lower_grade"] == "intern" and res["accept_lower_p"] >= 0.8
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["retake_locks"] == {}  # (а): «предварительно» — не неудача, повтор на Junior открыт
    sid = res["session_id"]
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert r.status_code == 200 and r.json()["accept_lower_grade"] == "intern"
    r = client.post(f"/api/assessment/sessions/{sid}/accept-lower", headers=H(t))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["accepted_lower"] == "intern" and out["category_id"] == "backend.intern" and out["grade_changed"]
    assert out["category_status"] == "confirmed" and not out["accept_lower_available"]
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["current"]["category_id"] == "backend.intern" and not st["current"]["provisional"]
    assert st["provisional"] is None and st["grade_history"][0]["to"] == "intern"
    # работодатель: категория Стажёра подтверждена, «предварительно» в Junior больше нет
    e = employer(client)
    assert client.get("/api/employer/candidates", params={"category": "backend.junior"}, headers=H(e)).json()["total"] == 0
    r = client.get("/api/employer/candidates", params={"category": "backend.intern"}, headers=H(e)).json()
    assert r["total"] == 1 and not r["items"][0]["category"]["provisional"]
