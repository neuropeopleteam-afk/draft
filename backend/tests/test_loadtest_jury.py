"""Я7 (09.10): сценарии нагрузки жюри (tools/loadtest/jury_load.py) идут по настоящему API и без LLM.

Проверяется на тестовом приложении то, что Locust делает на стенде: вход в одну песочницу жюри, экспресс-тест до
итога ответами из flows.answer_for (без заданий с LLM-оценкой), потребность из разбора правилами с готовыми
требованиями (повторного разбора и модели нет), приглашение и его повтор (409 — правило продукта), сводка без токенов.
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

from app.core.config import get_settings
from tests.test_infra_0610 import _login

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "loadtest"
sys.path.insert(0, str(TOOLS))
import flows  # noqa: E402


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_express_path_to_result_without_llm_items(client):
    sid = _login(client, "employer", "new")["scenario"]
    assert sid
    rnd = random.Random(7)
    for persona in flows.CAND_PERSONAS:
        tok = _login(client, persona, sid)["access_token"]
        r = client.post("/api/assessment/sessions", headers=_h(tok),
                        json={"claimed_grade": flows.GRADE_FOR[persona], "mode": "express", "integrity_ack": True})
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["mode"] == "express"
        item, n = s["item"], 0
        while item:
            assert not flows.is_llm_item(item), item["format"]  # экспресс: без open_answer и open_book_3step
            a = client.post(f"/api/assessment/sessions/{s['session_id']}/answers", headers=_h(tok),
                            json=flows.answer_for(item, rnd))
            assert a.status_code == 200, a.text
            item, n = a.json()["item"], n + 1
            assert n <= 30
        f = client.post(f"/api/assessment/sessions/{s['session_id']}/finish", headers=_h(tok))
        assert f.status_code == 200, f.text
        assert 3 <= n <= 12
        assert client.get(f"/api/assessment/sessions/{s['session_id']}/result", headers=_h(tok)).status_code == 200


def test_llm_item_detection():
    assert flows.is_llm_item({"format": "open_answer", "answer_kind": "text"})
    assert flows.is_llm_item({"format": "open_book_3step", "answer_kind": "text", "step": 3})
    assert not flows.is_llm_item({"format": "open_book_3step", "answer_kind": "option", "step": 1})
    assert not flows.is_llm_item({"format": "predict_output", "answer_kind": "text"})  # сверка с ключом
    body = flows.answer_for({"item_id": "x", "answer_kind": "line", "code": "a\nb\nc"}, random.Random(1))
    assert 1 <= body["answer"] <= 3


def test_employer_need_from_rules_and_invitation(client, monkeypatch):
    calls = []
    from app.modules.matching import need_parser

    monkeypatch.setattr(need_parser, "parse_need", lambda *a, **k: calls.append(a) or {})  # POST /needs не разбирает
    sid = _login(client, "employer", "new")["scenario"]
    tok = _login(client, "employer", sid)["access_token"]
    made = []
    for text in flows.NEED_TEXTS:
        p = client.post("/api/employer/needs/parse", headers=_h(tok), json={"text": text, "mode": "fast"})
        assert p.status_code == 200, p.text
        req = flows.need_requirements(p.json())
        assert req.get("direction") and req["stack_required"], (text, req)
        n = client.post("/api/employer/needs", headers=_h(tok), json={"text": text, "requirements": req})
        assert n.status_code == 201, n.text
        made.append(n.json())
    assert calls == []  # требования готовы — повторного разбора (и модели) при сохранении нет
    refs, need = [], made[0]
    for need in made:  # подборка хотя бы по одной потребности не пуста (кандидаты песочницы и демо-базы)
        v = client.get(f"/api/employer/needs/{need['id']}/selections/{need['versions'][-1]['version']}",
                       headers=_h(tok))
        refs = [x["ref"] for x in v.json()["results"]]
        if refs:
            break
    assert refs
    sent = None
    for ref in refs:  # часть кандидатов песочницы уже приглашена её сценарием — первая свободная
        r = client.post("/api/employer/invitations", headers=_h(tok), json=flows.invitation_body(ref, need["id"]))
        assert r.status_code in (201, 409), r.text
        if r.status_code == 201:
            sent = ref
            break
    assert sent
    again = client.post("/api/employer/invitations", headers=_h(tok), json=flows.invitation_body(sent, need["id"]))
    assert again.status_code == 409 and "invitation_cooldown" in again.text  # в нагрузке — успех, не ошибка
    assert client.get(f"/api/employer/needs/{need['id']}/compare", headers=_h(tok)).status_code in (200, 422)
    assert get_settings().jury_max_test_starts_per_day == 30  # docs/LOAD.md: лимит стартов демо-учётки за сутки


def _run_load():
    spec = importlib.util.spec_from_file_location("run_load", TOOLS / "run_load.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_run_load_scrub_and_summary(tmp_path, capsys, monkeypatch):
    m = _run_load()
    s = m._scrub("GET /x/AbCdEf0123456789xyz ok; Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl")
    assert "AbCdEf0123456789" not in s and "eyJ" not in s and "/x/<токен>" in s
    monkeypatch.setattr(m, "OUT", tmp_path)
    head = ("Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,Min Response Time,"
            "Max Response Time,Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,"
            "99.99%,100%\n")
    (tmp_path / "t_stats.csv").write_text(
        head + "POST,тест: ответ,10,0,20,25,5,90,100,1.0,0,20,22,24,25,30,40,60,80,90,90,90\n"
        ",Aggregated,10,0,20,25,5,90,100,1.0,0,20,22,24,25,30,40,60,80,90,90,90\n", encoding="utf-8")
    (tmp_path / "t_server.txt").write_text("## 10:00:00 1.20 1.00 0.90\nspectrek_fsp-api-1;150.5%;600MiB / 1.5GiB\n"
                                           "## memory.peak api\n734003200\noom 0\noom_kill 0\n")
    m.summary(type("A", (), {"tag": "t"})())
    out = capsys.readouterr().out
    assert "| тест: ответ | 10 | 0 | 20 | 40 | 80 | 90 |" in out
    assert "spectrek_fsp-api-1 | 150 / 150 | 600" in out and "oom_kill 0" in out
