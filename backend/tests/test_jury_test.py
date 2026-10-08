"""07.10, поток «Тест глазами жюри»: экспресс-тест, лимит 30 запусков, «Проверьте сами» на настоящем движке,
повтор на тот же грейд раз в 30 дней, принятие уровня ниже, подсказка грейда, удаление своей песочницы."""
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest

from app.core.db import SessionLocal, utcnow
from app.modules.assessment import bank_engine as be
from app.modules.assessment.rules import (accept_lower_allowed, check_can_start, proved_lower, retake_locks)
from app.modules.jury import scope
from app.modules.assessment.grader import GradeOutcome
from tests.conftest import register_and_verify
from tests.test_bank_engine import oracle
from tests.test_day2_rules import H, ONBOARDING, make_demo, pass_test

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ п. 4: повтор на тот же грейд — раз в 30 дней
def test_retake_rules_pure():
    failed = {"middle": NOW - timedelta(days=3)}
    locks = retake_locks(failed, NOW, 30)
    assert set(locks) == {"middle", "senior"} and locks["middle"].date() == (NOW + timedelta(days=27)).date()
    # тот же грейд и выше — закрыты, ниже — сразу
    assert check_can_start(None, None, "middle", NOW, False, failed).code == "retake_cooldown"
    assert check_can_start(None, None, "senior", NOW, False, failed).code == "retake_cooldown"
    low = check_can_start(None, None, "junior", NOW, False, failed)
    assert low.allowed and low.code is None
    msg = check_can_start(None, None, "middle", NOW, False, failed).message
    assert "30 дней" in msg and "Junior можно пройти сразу" in msg
    # через 30 дней — можно; песочница жюри снимает ограничение
    assert check_can_start(None, None, "middle", NOW + timedelta(days=31), False, failed).allowed
    assert check_can_start(None, None, "middle", NOW, True, failed).allowed
    # правило 90 дней остаётся приоритетным для кандидата с категорией
    assert check_can_start("junior", NOW + timedelta(days=10), "middle", NOW, False, failed).code == "grade_locked"
    assert retake_locks(None, NOW, 30) == {} and retake_locks({"x": NOW}, NOW, 30) == {}


def test_retake_cooldown_api(client):
    t = register_and_verify(client)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    res = pass_test(client, t, "middle", correct=False)
    assert not res["confirmed"] and res["category_id"] is None
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert set(st["retake_locks"]) == {"middle", "senior"} and st["retake_same_grade_days"] == 30
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "retake_cooldown", r.text
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "senior"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "retake_cooldown"
    # тест на грейд ниже — сразу, без зачёта попыток (видео №7, №20)
    res = pass_test(client, t, "junior")
    assert res["confirmed"] and res["category_id"] == "backend.junior"
    # демо-режим жюри снимает ограничение
    make_demo("cand@example.com")
    client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t))
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["retake_locks"] == {}


# ------------------------------------------------------------------ п. 5: принять уровень ниже без нового теста
def test_accept_lower_rules_pure():
    probs = {"none": 0.02, "junior": 0.1, "middle": 0.7, "senior": 0.18}  # Senior не доказан, Middle — P = 0,88
    assert proved_lower(probs, "senior") == "middle"
    assert proved_lower(probs, "middle") == "junior"  # P(θ ≥ junior) = 0,98
    assert proved_lower({"none": 0.5, "junior": 0.3, "middle": 0.2, "senior": 0.0}, "senior") is None
    assert accept_lower_allowed(None, "senior", False, probs) == ("middle", None)
    assert accept_lower_allowed(None, "senior", True, probs) == (None, "confirmed")
    assert accept_lower_allowed("middle", "senior", False, probs) == (None, "not_above_current")
    assert accept_lower_allowed("junior", "senior", False, probs) == ("middle", None)


def _force_result(session_id: str, probs: dict, theta: float, se: float) -> None:
    """Подменяет вероятности в сохранённом результате заглушки — проверяем правило, а не заглушку."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.modules.assessment.models import TestSession

    with SessionLocal() as db:
        ts = db.get(TestSession, uuid.UUID(session_id))
        er = dict(ts.result["engine_result"])
        er.update({"probabilities": probs, "theta": theta, "se": se, "confirmed": False, "retake_lower": "middle"})
        ts.result = {**ts.result, "engine_result": er}
        flag_modified(ts, "result")
        db.commit()


def test_accept_lower_api(client):
    t = register_and_verify(client)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    res = pass_test(client, t, "senior", correct=False)
    sid = res["session_id"]
    # всё неверно — Senior не подтверждён; на шкале со Стажёром (И13) заглушка при θ ≈ −0,9 ещё может доказать
    # уровень Стажёра (P(θ ≥ −1,75) ≥ 0,8) — ничего выше intern доказано быть не может
    assert not res["confirmed"] and res["accept_lower_grade"] in (None, "intern")
    _force_result(sid, {"none": 0.6, "intern": 0.25, "junior": 0.1, "middle": 0.05, "senior": 0.0}, -2.0, 0.6)
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert r.status_code == 200 and not r.json()["accept_lower_available"]  # ничего не доказано
    r = client.post(f"/api/assessment/sessions/{sid}/accept-lower", headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "accept_lower_unavailable"
    _force_result(sid, {"none": 0.01, "junior": 0.09, "middle": 0.75, "senior": 0.15}, 0.6, 0.4)
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t))
    assert r.status_code == 200 and r.json()["accept_lower_available"] and r.json()["accept_lower_grade"] == "middle"
    r = client.post(f"/api/assessment/sessions/{sid}/accept-lower", headers=H(t))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["accepted_lower"] == "middle" and out["category_id"] == "backend.middle" and out["grade_changed"]
    assert "90 %" in out["message"] and not out["accept_lower_available"]
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["current"]["category_id"] == "backend.middle" and st["grade_history"][0]["reason"] == "initial"
    assert st["lock_active"] and st["sessions"][0]["accepted_lower"] == "middle"
    card = client.get("/api/me/card", headers=H(t)).json()
    assert card["test"]["grade"] == "middle" and card["test"]["accepted_lower"] and card["test"]["mode"] == "full"
    # повторно — нельзя; принудительного понижения нет: подтверждённый грейд сохранён
    r = client.post(f"/api/assessment/sessions/{sid}/accept-lower", headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_accepted"
    # по неподтверждённой попытке на Senior повтор на Senior закрыт на 30 дней, но категория уже есть
    assert "senior" in st["retake_locks"]


# ------------------------------------------------------------------ п. 1–2: экспресс-тест и лимит 30
@pytest.fixture
def bank(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm"))
    return be.BankEngine()


def test_express_engine_short_no_canaries_no_extension(bank):
    st = bank.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=99, mode="express")
    assert st["mode"] == "express" and st["cfg"]["canary_positions"] == [] and st["cfg"]["ext_items"] == 0
    while (item := bank.next_item(st)) is not None:
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        assert item.total == 7 and not it["canary"]
        assert it["format"] not in ("open_book_3step", "open_answer") and it["time_limit_s"] <= 240
        assert bank.answer(st, item.item_id, oracle(it, item.step or 1, True), 1500, step=item.step).accepted
    res = bank.finish(st)
    d = res.details
    assert d["mode"] == "express" and 5 <= d["n_scored"] <= 7 and d["n_canaries"] == 0 and d["extension"] is None
    assert "Экспресс-тест" in res.explanation and "интервал θ шире" in res.explanation
    # полный режим не изменился
    full = bank.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=99)
    assert full["mode"] == "full" and "canary_positions" not in full["cfg"] or full["cfg"].get("canary_positions") != []
    assert bank._total_est(full) == full["cfg"]["max_items"] + 3


def test_express_api_only_in_sandbox_and_marked(client, bank):
    t = register_and_verify(client, email="exp@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["express_available"] is False and (st["express"]["min_items"], st["express"]["max_items"]) == (5, 7)
    # консилиум 07.10, решение 5: параметры экспресса по грейду — за Senior длиннее
    assert st["express"]["by_grade"]["middle"] == {"min_items": 5, "max_items": 7, "item_time_s": 240, "max_minutes": 20}
    assert st["express"]["by_grade"]["senior"] == {"min_items": 8, "max_items": 12, "item_time_s": 360, "max_minutes": 45}
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", "mode": "express"}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "express_sandbox_only"
    make_demo("exp@example.com")
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["express_available"] is True and st["sandbox_starts"]["limit"] == 30  # п. 2: лимит 5 → 30
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", "mode": "express"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["mode"] == "express" and s["item"]["total"] == 7
    sid = s["session_id"]
    from app.modules.assessment.models import TestSession

    n = 0
    while s["item"]:
        with SessionLocal() as db:
            ts = db.get(TestSession, uuid.UUID(sid))
            assert (ts.deadline_at - ts.started_at) <= timedelta(minutes=20)
            it = next(i for i in ts.result["state"]["items"] if i["token"] == s["item"]["item_id"])
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json={
            "item_id": s["item"]["item_id"], "answer": oracle(it, s["item"]["step"] or 1, True),
            "step": s["item"]["step"], "time_spent_ms": 3000})
        assert r.status_code == 200, r.text
        s = r.json()
        n += 1
        assert n <= 7
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    assert res["mode"] == "express" and res["details"]["mode"] == "express" and res["details"]["n_canaries"] == 0
    assert res["confirmed"] and res["category_id"] == "backend.middle", res
    status = client.get("/api/assessment/status", headers=H(t)).json()
    assert status["sessions"][0]["mode"] == "express" and status["sandbox_starts"]["used"] == 1
    card = client.get("/api/me/card", headers=H(t)).json()
    assert card["test"]["mode"] == "express"


# ------------------------------------------------------------------ консилиум 07.10, решение 5: экспресс за Senior — 8–12 заданий, лимит 360 с
def test_express_senior_longer_same_rule(bank):
    """За Senior экспресс длиннее (8–12, лимит задания ≤ 360 с), без канареек и дотестирования; правило P ≥ 0,8 то же —
    и «всё верно» теперь подтверждает Senior (за 7 заданий с лимитом 240 с потолок θ̂ ≈ 1,4 не давал этого). Junior/Middle — как раньше."""
    st = bank.start(direction="backend", claimed_grade="senior", stack_tags=[], seed=99, mode="express")
    c = st["cfg"]
    assert (c["min_items"], c["max_items"], c["max_item_time_s"], c["max_time_s"]) == (8, 12, 360.0, 45 * 60.0)
    assert c["canary_positions"] == [] and c["ext_items"] == 0
    n = 0
    while (item := bank.next_item(st)) is not None:
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        assert item.total == 12 and item.max_items == 12 and not it["canary"]
        assert it["format"] not in ("open_book_3step", "open_answer") and it["time_limit_s"] <= 360
        assert bank.answer(st, item.item_id, oracle(it, item.step or 1, True), 1500, step=item.step).accepted
        n += 1
    assert 8 <= n <= 12
    res = bank.finish(st)
    d = res.details
    assert d["mode"] == "express" and d["n_canaries"] == 0 and d["extension"] is None and d["length"]["max_items"] == 12
    assert res.confirmed and res.point_grade == "senior" and res.probabilities["senior"] >= 0.8, (res.theta, res.se)
    assert "За Senior экспресс длиннее (до 12 заданий)" in res.explanation
    # Junior — как раньше: 5–7, лимит 240 с, 20 минут
    jr = bank.start(direction="qa", claimed_grade="junior", stack_tags=[], seed=5, mode="express")
    assert (jr["cfg"]["min_items"], jr["cfg"]["max_items"], jr["cfg"]["max_item_time_s"], jr["cfg"]["max_time_s"]) == (5, 7, 240.0, 1200.0)
    assert be.express_params(bank._settings(), "middle") == be.express_params(bank._settings(), "junior")


def test_express_senior_api_deadline_and_synthetic(client, bank, monkeypatch):
    """API: сессия экспресса за Senior с дедлайном 45 минут и total 12; «Проверьте сами»: «всё верно» на SyntheticEngine подтверждает
    Senior (seed фиксирован), длина 8–12."""
    from app.modules.assessment.models import TestSession
    from app.modules.validation import selfcheck as sc

    t = register_and_verify(client, email="exp-sr@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    make_demo("exp-sr@example.com")
    assert client.put("/api/me/jury-mode", json={"enabled": True}, headers=H(t)).status_code == 200
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "senior", "mode": "express"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["mode"] == "express" and s["item"]["total"] == 12 and s["item"]["time_limit_s"] <= 360
    with SessionLocal() as db:
        ts = db.get(TestSession, uuid.UUID(s["session_id"]))
        assert (ts.deadline_at - ts.started_at) == timedelta(minutes=45)
        assert ts.result["state"]["cfg"]["max_items"] == 12
    monkeypatch.setattr(be, "grade_open", lambda **kw: (_ for _ in ()).throw(AssertionError("LLM не должен вызываться")))
    out = sc.run(strategy="all_correct", theta=None, direction="backend", claimed="senior", n=3, repeat=False,
                 mode="express", seed=7)
    assert out["confirm_rate"] == 1.0 and out["assigned"] == {"senior": 3} and out["verdict"]["ok"]
    assert 8 <= out["n_items"]["min"] and out["n_items"]["max"] <= 12 and out["theta_hat_max"] >= 1.5


# ------------------------------------------------------------------ консилиум 07.10, 7.5: честная подпись вердикта и потолок θ̂ в ожидании
def test_self_check_verdict_label_and_ceiling():
    from app.modules.validation import selfcheck as sc

    base = {"runs_total": 20, "mode": "express", "n_items": {"mean": 7.0, "min": 7, "max": 7}, "time_min": {"mean": 13.6},
            "correct_share": 0.6}
    # 10 % против 39 %: больше 2 σ (≈ 22 п. п.), но в допуске (≈ 32 п. п.) — разрыв назван, а не спрятан за «как ожидалось»
    v = sc._verdict({**base, "confirm_rate": 0.10}, {"confirm_rate": 0.39})
    assert v["ok"] and v["kind"] == "tolerance" and v["label"] == "В допуске выборки, разрыв 29 п. п." and v["gap_pp"] == 29
    assert "разрыв 29 п. п." in v["text"] and "не доказывает смещения" in v["text"]
    v = sc._verdict({**base, "confirm_rate": 0.35}, {"confirm_rate": 0.39})
    assert v["ok"] and v["kind"] == "exact" and v["label"] == "Как и ожидалось"
    v = sc._verdict({**base, "confirm_rate": 0.90}, {"confirm_rate": 0.39})
    assert not v["ok"] and v["kind"] == "mismatch" and v["label"] == "Расхождение с ожиданием, разрыв 51 п. п."
    v = sc._verdict({**base, "confirm_rate": 1.0}, {"confirmed": True})
    assert v["ok"] and v["label"] == "Как и ожидалось" and v["gap_pp"] is None
    # потолок θ̂: за 7 коротких заданий Senior не подтвердить даже при всех верных — ожидание 0 %, а не 22 % по формуле без потолка
    e0 = sc.expected_for("theta", 1.5, "senior", se=0.67)
    e1 = sc.expected_for("theta", 1.5, "senior", se=0.67, theta_hat_max=1.39)
    e2 = sc.expected_for("theta", 1.5, "senior", se=0.67, theta_hat_max=1.9)
    assert e0["confirm_rate"] > 0.15 and e1["confirm_rate"] == 0.0 and e2["confirm_rate"] == e0["confirm_rate"]
    assert "Потолок оценки" in e1["text"] and e1["theta_hat_needed"] == 1.56 and "потолок θ̂" in e2["text"]
    pool7 = [{"a": [1.0], "b": [0.0], "sigma": [0.0]}] * 7
    c7, c12 = sc.theta_hat_ceiling(pool7), sc.theta_hat_ceiling(pool7 + [{"a": [1.0], "b": [1.0], "sigma": [0.0]}] * 5)
    assert 1.2 < c7 < 1.6 < c12 and sc.theta_hat_ceiling([]) is None


# ------------------------------------------------------------------ п. 3: «Проверьте сами» на настоящем движке
def test_self_check_module_and_api(client, monkeypatch):
    from app.modules.validation import selfcheck as sc

    monkeypatch.setattr(be, "grade_open", lambda **kw: (_ for _ in ()).throw(AssertionError("LLM не должен вызываться")))
    out = sc.run(strategy="all_correct", theta=None, direction="backend", claimed="middle", n=2, repeat=True,
                 mode="express", seed=5)
    assert out["runs_total"] == 4 and out["confirm_rate"] == 1.0 and out["assigned"] == {"middle": 4}
    assert out["n_items"]["max"] <= 7 and out["retest"]["decision_agreement"] == 1.0 and out["verdict"]["ok"]
    out = sc.run(strategy="all_wrong", theta=None, direction="qa", claimed="junior", n=2, repeat=False, mode="full", seed=5)
    assert out["confirm_rate"] == 0.0 and out["point_grade"] == {"none": 2} and out["verdict"]["ok"]
    # развёрнутые ответы оценены стратегией, а не LLM; воспроизводимость по seed
    a = sc.run(strategy="level_middle", theta=None, direction="backend", claimed="middle", n=2, repeat=False, mode="full", seed=11)
    b = sc.run(strategy="level_middle", theta=None, direction="backend", claimed="middle", n=2, repeat=False, mode="full", seed=11)
    assert a["runs"] == b["runs"] and a["theta"] == 0.5
    assert sc.expected_for("theta", 0.95, "senior")["confirmed"] is False and "у самого порога" in sc.expected_for("theta", 0.95, "senior")["text"]
    # API: вход обязателен, лимиты, занятость
    r = client.post("/api/validation/self-check", json={"n": 1})
    assert r.status_code == 401
    t = register_and_verify(client, email="v@example.com")
    r = client.post("/api/validation/self-check", json={"strategy": "nope"}, headers=H(t))
    assert r.status_code == 404
    r = client.post("/api/validation/self-check", json={"n": 99}, headers=H(t))
    assert r.status_code == 422
    r = client.post("/api/validation/self-check", headers=H(t),
                    json={"strategy": "random", "direction": "frontend", "claimed_grade": "junior", "n": 2, "repeat": False,
                          "mode": "express", "seed": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runs_total"] == 2 and body["expected"]["confirmed"] is False and "verdict" in body
    assert "state" not in json.dumps(body) and "key" not in body["runs"][0]
    assert sc._busy.acquire(blocking=False)
    try:
        r = client.post("/api/validation/self-check", json={"n": 1}, headers=H(t))
        assert r.status_code == 429 and r.json()["detail"]["code"] == "self_check_busy"
    finally:
        sc._busy.release()
    rep = client.get("/api/validation/report").json()
    assert rep["self_check"]["max_n"] == 20 and len(rep["self_check"]["strategies"]) == 8
    # в БД ничего не записано
    from sqlalchemy import func, select

    from app.modules.assessment.models import TestSession

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TestSession)) == 0


# ------------------------------------------------------------------ п. 6: подсказка грейда по правилам
def test_grade_hint_rules_pure():
    from app.modules.assessment.grade_hint import build_hint, grade_by_years

    assert [grade_by_years(y) for y in (0.5, 1.5, 4.4, 4.5, None)] == ["junior", "middle", "middle", "senior", None]
    h = build_hint(survey_years=3.0, resume={"experience_years": 3.2, "roles": [{"id": "developer"}], "stack": [{"tag": "python"}]},
                   achievements=[])
    assert h["suggested"] == "middle" and h["confidence"] == "high" and "Выбор за вами" in h["summary"]
    assert {s["source"] for s in h["signals"]} == {"survey", "resume", "fsp"}
    # расхождение опроса и резюме — объяснено, уверенность ниже
    h = build_hint(survey_years=1.0, resume={"experience_years": 6.0, "roles": [{"id": "team_lead"}]}, achievements=[])
    assert h["suggested"] == "senior" and h["confidence"] != "high" and any("Расходится" in s["text"] for s in h["signals"])
    # ФСП: призовое место на межрегиональном уровне и выше — мягкий сигнал Middle для Junior по стажу, не выше
    h = build_hint(survey_years=1.0, resume=None,
                   achievements=[{"level": "national", "place": 2, "result_title": "призёр", "verified": True}])
    assert h["suggested"] in ("junior", "middle") and any(s["source"] == "fsp" and s["grade"] == "middle" for s in h["signals"])
    h = build_hint(survey_years=1.0, resume=None,
                   achievements=[{"level": "regional", "place": 12, "result_title": "участник", "verified": True}])
    assert h["suggested"] == "junior" and any("На грейд не влияют" in s["text"] for s in h["signals"])
    h = build_hint(survey_years=None, resume=None, achievements=[])
    assert h["suggested"] is None and h["confidence"] == "none"


def test_grade_hint_api_for_jury_persona(client):
    r = client.post("/api/jury/login", json={"persona": "candidate_new"})
    assert r.status_code == 200, r.text
    assert r.json()["landing"] == "/candidate/express"
    t = r.json()["access_token"]
    h = client.get("/api/assessment/grade-hint", headers=H(t)).json()
    assert h["suggested"] == "middle" and h["method"] == "rules" and h["has_resume"]
    assert len(h["signals"]) >= 4 and {s["source"] for s in h["signals"]} == {"survey", "resume", "fsp"}
    st = client.get("/api/assessment/status", headers=H(t)).json()
    assert st["current"]["category_id"] is None and st["sandbox_active"] and st["sessions"] == []
    # у персоны нет резюме с ПДн: текст без ФИО и контактов
    me = client.get("/api/me/resume", headers=H(t)).json()
    assert "Антон" not in json.dumps(me, ensure_ascii=False)
    # экспресс доступен в демо-режиме, но только на движке банка (в тестах по умолчанию — заглушка)
    assert st["express_available"] == st["engine"].startswith("bank")


# ------------------------------------------------------------------ п. 7: удаление своей песочницы
def test_delete_own_sandbox(client):
    from sqlalchemy import select

    from app.modules.auth.models import User
    from app.modules.jury import seed

    r = client.post("/api/jury/login", json={"persona": "candidate_new", "scenario": "new"})
    assert r.status_code == 200, r.text
    sid, t = r.json()["scenario"], r.json()["access_token"]
    assert sid and len(sid) == 10
    with SessionLocal() as db:
        assert seed._complete(db, sid)
    r = client.delete("/api/jury/sandbox", headers=H(t))
    assert r.status_code == 200, r.text
    assert r.json()["deleted_users"] == 7 and r.json()["scenario"] == sid  # 7 персон: + candidate_junior (И1) и candidate_new (И2)
    with SessionLocal() as db:
        assert not seed._complete(db, sid)
        assert db.scalar(select(User).where(User.email == scope.emails(sid)["candidate_new"])) is None
    # общее демо не удаляется
    r = client.post("/api/jury/login", json={"persona": "employer"})
    r = client.delete("/api/jury/sandbox", headers=H(r.json()["access_token"]))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "jury_shared"
    # живой кандидат — не жюри
    t2 = register_and_verify(client, email="live@example.com")
    assert client.delete("/api/jury/sandbox", headers=H(t2)).status_code == 403
    assert client.delete("/api/jury/sandbox").status_code == 401
