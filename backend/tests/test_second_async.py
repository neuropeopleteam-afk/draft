"""И27: вторая оценка спорных развёрнутых ответов — в фоне. Итог теста её не ждёт; результат дописывается в оценку
с пометкой «пересмотрено второй моделью»; после итога грейд задним числом не меняется — спорный ответ уходит эксперту.

Оценщик: настоящий grade_open на подменённой сети (test_llm_chain: Net) или заглушка в сквозном сценарии через API.
"""
from __future__ import annotations

import json
import time
import uuid

import httpx

from app.core.db import SessionLocal
from app.modules.assessment import bank_engine as be, grader, second_opinion
from app.modules.assessment.grader import GradeOutcome, second_opinion as second_call
from tests.conftest import register_and_verify
from tests.test_bank_engine import _state, oracle
from tests.test_day2_rules import ONBOARDING, H
from tests.test_llm_chain import ANSWER, FABLE, RUBRIC, SONNET, _go, _grade, configure, net  # noqa: F401 — net

FIRST = {"score": 0.5, "criteria": {"cause": 1.0, "fix": 0.0}}


# ------------------------------------------------------------------ оценщик
def test_async_first_score_does_not_wait_for_second(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 0}))  # 0,5 — у порога, нужна вторая оценка
    net.on("or.test", FABLE, lambda req, body: (time.sleep(3), _grade({"cause": 1, "fix": 0.5})(req, body))[1])
    from app.modules.resume.pii import redact

    redact("Ответ Ивана Петрова", use_ner=True)  # прогрев NER (загрузка модели — не часть ожидания)
    t0 = time.monotonic()
    g = _go(second_async=True)
    assert time.monotonic() - t0 < 2.0  # вторая модель отвечает через 3 с — её не ждём
    assert g.status == "scored" and g.method == "llm" and g.score == 0.5 and "near_threshold" in g.checks
    assert g.second == {"status": "pending", "checks": g.checks}
    assert [c["model"] for c in net.calls] == [SONNET]  # вторая модель в ответе кандидата не вызывалась
    # явная модель (сравнение оценщиков) и вызов по умолчанию — как раньше, синхронно
    net.on("or.test", FABLE, _grade({"cause": 1, "fix": 0.5}))
    assert _go().method == "llm2"


def test_second_opinion_verdicts(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    kw = dict(stem="Найдите ошибку бронирования", code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER, first=FIRST)
    net.on("or.test", FABLE, _grade({"cause": 1, "fix": 0.5}))  # 0,75 — рядом с 0,5
    r = second_call(**kw)
    assert r["verdict"] == "agree" and r["combined"]["score"] == 0.625 and r["label"] == "пересмотрено второй моделью"
    assert r["model_label"] == "вторая модель" and r["status"] == "done" and r["revised_at"]
    assert net.calls[-1]["body"]["messages"][0]["content"].startswith("Ты — второй, независимый проверяющий")
    net.on("or.test", FABLE, _grade({"cause": 0, "fix": 0}, "weak"))
    assert second_call(**{**kw, "first": {"score": 1.0, "criteria": {"cause": 1.0, "fix": 1.0}}})["verdict"] == "disagree"
    net.on("or.test", FABLE, lambda req, body: httpx.Response(500))
    r = second_call(**kw)
    assert r["verdict"] == "failed" and r["error"] == "http_500"


# ------------------------------------------------------------------ сквозной сценарий через API (движок bank)
def _start(client, monkeypatch, email):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(get_settings(), "llm_grading_second_async", True)
    calls: list[str] = []

    def fake_grade(**kw):
        calls.append(kw["answer"])
        return GradeOutcome(status="scored", score=0.5, method="llm", criteria={"c": 0.5}, checks=["near_threshold"],
                            second={"status": "pending"} if kw.get("second_async") else None)

    monkeypatch.setattr(be, "grade_open", fake_grade)
    queued: list[tuple] = []
    monkeypatch.setattr(second_opinion, "_spawn", lambda fn, *a: queued.append(a))  # фон — вручную, по шагам
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t))
    assert r.status_code == 201, r.text
    return t, r.json(), queued, calls


def _answer_all(client, t, s, on_answer=None):
    sid, n = s["session_id"], 0
    while s["item"]:
        p = s["item"]
        it = next(i for i in _state(sid)["items"] if i["token"] == p["item_id"])
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json={
            "item_id": p["item_id"], "answer": oracle(it, p["step"] or 1, True), "step": p["step"], "time_spent_ms": 4000})
        assert r.status_code == 200, r.text
        s = r.json()
        if on_answer:
            on_answer()
        n += 1
        assert n < 80
    return sid


def _verdict(monkeypatch, verdicts: list[str]):
    seen = []

    def fake(**kw):
        v = verdicts[min(len(seen), len(verdicts) - 1)]
        seen.append(v)
        return {"status": "done", "label": grader.SECOND_LABEL, "revised_at": time.time(), "verdict": v,
                "score": 0.9 if v == "agree" else 0.0, "model_label": "Claude Fable 5.1",
                **({"combined": {"score": 0.7, "criteria": {"c": 0.7}}} if v == "agree" else {})}

    monkeypatch.setattr(grader, "second_opinion", fake)
    return seen


def _parts(sid):
    return [(it, p, g) for it in _state(sid)["items"] for p, g in enumerate(it["grading"])
            if isinstance(g, dict) and g.get("second")]


def test_in_progress_agree_and_disagree(client, monkeypatch):
    t, s, queued, calls = _start(client, monkeypatch, "so1@example.com")
    _verdict(monkeypatch, ["agree", "disagree"])

    def drain():  # фон отрабатывает сразу после ответа (тест ещё идёт)
        while queued:
            second_opinion.run(*queued.pop(0))

    sid = _answer_all(client, t, s, drain)
    parts = _parts(sid)
    assert parts, "в сессии не оказалось развёрнутых ответов"
    (it1, p1, g1), rest = parts[0], parts[1:]
    assert g1["second"]["label"] == "пересмотрено второй моделью" and g1["second"]["verdict"] == "agree"
    assert it1["x"][p1] == 0.7 and g1["method"] == "llm2" and g1["second"]["queued_at"]
    for it, p, g in rest:  # разошлись — балл снят, ответ ждёт эксперта
        assert g["second"]["verdict"] == "disagree" and it["x"][p] is None and g["error"] == "graders_disagree"
    n_calls = len(calls)
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    assert len(calls) == n_calls  # спорный ответ при завершении модель повторно не оценивает
    assert res["details"]["pending_review"] == len(rest)
    so = res["second_opinions"]
    assert so["pending"] == 0 and so["revised"] == len(parts) and so["disputed"] == len(rest)
    # запись для калибровки (test_answers) обновлена событием review
    from sqlalchemy import select

    from app.modules.assessment.models import TestAnswer

    with SessionLocal() as db:
        rows = db.scalars(select(TestAnswer)).all()
        graded = [r.grading for r in rows if any(isinstance(g, dict) and g.get("second") for g in r.grading["parts"])]
    assert any(g["parts"][p1].get("method") == "llm2" for g in graded if len(g["parts"]) > p1)


def test_finished_result_does_not_wait_and_dispute_goes_to_expert(client, monkeypatch):
    from app.modules.assessment import review

    t, s, queued, _ = _start(client, monkeypatch, "so2@example.com")
    sid = _answer_all(client, t, s)
    n = len(queued)
    assert n >= 1
    t0 = time.monotonic()
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    assert time.monotonic() - t0 < 5 and res["second_opinions"]["pending"] == n  # итог не ждёт вторую оценку
    before = {(it["token"], p): it["x"][p] for it, p, _ in _parts(sid)}
    category = res["category_id"]
    _verdict(monkeypatch, ["disagree"])
    while queued:
        second_opinion.run(*queued.pop(0))
    after = _parts(sid)
    for it, p, g in after:  # балл и грейд задним числом не меняются: только пометка и очередь эксперта
        assert it["x"][p] == before[(it["token"], p)] and g["disputed"] and g["second"]["after_finish"]
    r = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t)).json()
    assert r["category_id"] == category and r["second_opinions"]["disputed"] == n and r["second_opinions"]["pending"] == 0
    with SessionLocal() as db:
        q = review.queue(db, "pending")
        mine = [i for i in q["items"] if i["session_id"] == sid]
        assert len(mine) == n and mine[0]["llm"]["second"]["verdict"] == "disagree"
        it, p, _ = after[0]
        crit = {c["id"]: 1.0 for c in it["rubric"]["criteria"]}
        out = review.submit(db, uuid.UUID(sid), it["token"], p, crit, "проверено", "expert-test")
        assert out["review"]["applied"] and out["recomputed"] and out["review"]["llm_score"] == before[(it["token"], p)]
    st = _state(sid)
    x = next(i for i in st["items"] if i["token"] == it["token"])["x"][p]
    assert x == 1.0


def test_second_job_skips_if_already_decided(client, monkeypatch):
    t, s, queued, _ = _start(client, monkeypatch, "so3@example.com")
    sid = _answer_all(client, t, s)
    _verdict(monkeypatch, ["agree"])
    job = queued[0]
    second_opinion.run(*job)
    snap = json.dumps(_state(sid), sort_keys=True, default=str)
    second_opinion.run(*job)  # повторный запуск той же задачи ничего не меняет
    assert json.dumps(_state(sid), sort_keys=True, default=str) == snap
    second_opinion.run(uuid.uuid4(), "нет", 0)  # нет сессии — тихо


def test_sync_mode_keeps_old_behaviour(client, monkeypatch):
    from app.core.config import get_settings

    t, s, queued, calls = _start(client, monkeypatch, "so4@example.com")
    monkeypatch.setattr(get_settings(), "llm_grading_second_async", False)
    _answer_all(client, t, s)
    assert queued == [] and calls  # без фона: оценщик сам решает вторую оценку синхронно
