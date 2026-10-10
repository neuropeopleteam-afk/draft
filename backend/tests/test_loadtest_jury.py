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


def test_heavy_actions_resume_docx_and_red_button(client):
    """Тяжёлые действия (всплески памяти api, LLM): DOCX резюме модельного кандидата принимается разбором, «Красная кнопка» —
    по телу flows.attack_body; новый текст потребности не совпадает с базовым (кэш разбора не срабатывает)."""
    sid = _login(client, "employer", "new")["scenario"]
    tok = _login(client, "candidate_nofsp", sid)["access_token"]
    r = client.post("/api/me/resume", headers=_h(tok), files={"file": ("resume.docx", flows.resume_docx(1),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "docx" and not any(r.json()["pii_found"].values())  # ПДн в модельном резюме нет
    for aid in ("rename", "leak_bank"):
        a = client.post(f"/api/validation/attacks/{aid}", headers=_h(tok), json=flows.attack_body(aid))
        assert a.status_code == 200, a.text
    assert flows.need_text_variant(0) != flows.NEED_TEXTS[0] and flows.need_text_variant(0).startswith(flows.NEED_TEXTS[0])


def test_run_load_nginx_counts_only_tagged_lines(tmp_path, monkeypatch):
    """Сверка с журналом nginx: считаются только строки с User-Agent прогона (всплеск — отдельно), токен личной
    ссылки и адреса в вывод не попадают, разница «отправлено Locust − дошло до nginx» — по запросам без событий LLM."""
    import subprocess

    m = _run_load()
    logs, out = tmp_path / "nginx", tmp_path / "out"
    logs.mkdir()
    out.mkdir()
    ln = '203.0.113.7 - - [10/Oct/2026:22:00:0{i} +0300] "{req} HTTP/1.1" {code} 12 "-" "{ua}"\n'
    rows = [("GET /api/assessment/status", 200, "spectrek-load/t"), ("POST /api/jury/login", 200, "spectrek-load/t"),
            ("GET /x/SeCrEtToKeN0123456789 ", 302, "spectrek-load/t"), ("GET /criteria?x=1", 429, "spectrek-load/t"),
            ("GET /api/employer/needs/7/compare", 502, "spectrek-load/t"),
            ("POST /api/jury/login", 200, "spectrek-load/t-burst"), ("GET /", 200, "Mozilla/5.0"),
            ("GET /api/meta", 200, "spectrek-load/t2")]
    (logs / "access.log").write_text("".join(ln.format(i=i, req=r, code=c, ua=u) for i, (r, c, u) in enumerate(rows)))
    monkeypatch.setattr(m, "OUT", out)
    monkeypatch.setattr(m, "NGINX_LOG_DIR", str(logs))
    monkeypatch.setattr(m, "_remote", lambda s, timeout=120: subprocess.run(["bash", "-c", s], capture_output=True,
                                                                            text=True).stdout)
    head = "Type,Name,Request Count,Failure Count\n"
    (out / "t_stats.csv").write_text(head + "GET,a,5,1\nLLM,потребность: модель уточнила разбор (фон),2,0\n,Aggregated,8,1\n")
    (out / "t_failures.csv").write_text("Method,Name,Error,Occurrences\nGET,a,\"ConnectionError('reset')\",1\n")
    m.nginx(type("A", (), {"tag": "t"})())
    txt = (out / "t_nginx.txt").read_text()
    assert "Прогон: строк журнала 5; коды: 200 — 2, 302 — 1, 429 — 1, 502 — 1" in txt
    assert "Всплеск: строк журнала 1" in txt
    assert "429 /criteria: 1" in txt and "502 /api/employer/needs: 1" in txt
    assert "запросов 6 (без событий фоновой модели 2), из них без ответа (код 0, обрыв связи) 1; дошло до nginx 5 — " \
           "разница +1" in txt
    assert "SeCrEtToKeN" not in txt and "203.0.113.7" not in txt


def test_run_load_preflight_without_server(capsys, monkeypatch):
    """preflight без KPY: проверяет Locust, health, meta (LLM), личную ссылку; при ошибке — код 1 и «не начинать»."""
    m = _run_load()
    monkeypatch.setattr(m, "KPY", "")
    monkeypatch.setattr(m, "LOCUST", "/nonexistent/locust")
    monkeypatch.setattr(m, "_get", lambda url: (200, '{"status": "ok"}', {}) if url.endswith("/health") else
                        (200, '{"llm": {"configured": false, "chain": []}}', {}))
    try:
        m.preflight(type("A", (), {"host": "http://h", "xlink_file": ""})())
    except SystemExit as e:
        assert e.code == 1
    out = capsys.readouterr().out
    assert "ERR Locust: нет /nonexistent/locust" in out and "OK  /api/health: 200" in out
    assert "LLM выкл." in out and "KPY не задан" in out and "прогон не начинать" in out
