"""И27: быстрый разбор потребности — словарь сразу, модель в фоне, кэш, происхождение, отказ модели.

Сеть не используется: транспорт httpx подменён (tests/test_llm_chain.py: Net, configure). Фоновая задача — настоящий
поток (проверка времени ответа) или синхронный запуск (_spawn подменён) там, где проверяется содержимое.
"""
from __future__ import annotations

from datetime import timedelta
import json
import time
import uuid

import httpx
import pytest

from app.core.db import SessionLocal
from app.modules.matching import fast_parse
from app.modules.matching.models import NeedParseJob
from tests.test_day2_rules import H, employer
from tests.test_llm_chain import SONNET, configure, net, reply  # noqa: F401 — фикстура net

TEXT = ("Backend-разработчик уровня middle: Python и брокеры сообщений, межсервисное взаимодействие. "
        "Docker — для локального запуска, ведущий разработчик проекта. Гибрид.")
DELTA = {"stack_required": [{"tag": "grpc", "weight": 0.7, "quote": "межсервисное взаимодействие"}],
         "stack_desired": [{"tag": "rabbitmq", "weight": 0.4, "quote": "брокеры сообщений"}],
         "confirm": ["python"],
         "remove": [{"tag": "docker", "reason": "только для локального запуска", "quote": "для локального запуска"}],
         "direction": None, "grade": "senior", "experience_years_min": None, "work_format": None,
         "quotes": {"direction": None, "grade": "ведущий разработчик проекта", "experience_years_min": None,
                    "work_format": None}}


def delta_reply(req, body):
    return reply(json.dumps(DELTA, ensure_ascii=False), body["model"])


def inline(monkeypatch):
    """Фоновая задача выполняется сразу внутри запроса (содержимое, а не время)."""
    monkeypatch.setattr(fast_parse, "_spawn", lambda fn, *a: fn(*a))


def parse(client, t, text=TEXT, **kw):
    r = client.post("/api/employer/needs/parse", json={"text": text, **kw}, headers=H(t))
    assert r.status_code == 200, r.text
    return r.json()


def poll(client, t, job_id, timeout=15.0) -> dict:
    end = time.monotonic() + timeout
    while True:
        r = client.get(f"/api/employer/needs/parse/{job_id}", headers=H(t))
        assert r.status_code == 200, r.text
        j = r.json()
        if j["status"] != "pending" or time.monotonic() > end:
            return j
        time.sleep(0.1)


def test_rules_answer_is_immediate_while_model_is_slow(client, monkeypatch, net):
    """Ответ словарём не ждёт модель (мок отвечает через 2,5 с); итог модели появляется в задаче сам."""
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, lambda req, body: (time.sleep(2.5), delta_reply(req, body))[1])
    t = employer(client)
    t0 = time.monotonic()
    r = parse(client, t)
    took = time.monotonic() - t0
    assert took < 1.0, took  # на сервере ≈ 0,05 с; запас — на общую песочницу
    assert r["method"] == "rules" and r["llm"] == {"used": False, "pending": True}
    assert r["parse_job"]["status"] == "pending" and {"python", "docker"} <= {i["tag"] for i in r["stack_required"]}
    assert all(i["evidence"]["source"] == "rules" for i in r["stack_required"])
    j = poll(client, t, r["parse_job"]["id"])
    assert j["status"] == "done", j
    assert j["result"]["method"] == "llm+rules" and j["llm"]["model_label"] == "Claude Sonnet 5.5"
    assert j["llm"]["total_ms"] >= 2400


def test_background_delta_provenance_and_suggestions(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    inline(monkeypatch)
    net.on("or.test", None, delta_reply)
    t = employer(client)
    r = parse(client, t)
    j = poll(client, t, r["parse_job"]["id"])
    assert j["status"] == "done"
    # короткий запрос-дельта: текст + найденное словарём, жёсткая JSON-схема, лимит ответа меньше прежнего
    (call,) = net.calls
    body = call["body"]
    assert body["max_tokens"] == 900 and body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]["schema"]
    assert "grpc" in schema["properties"]["stack_required"]["items"]["properties"]["tag"]["enum"]
    user = body["messages"][1]["content"]
    assert "УЖЕ НАЙДЕНО СЛОВАРЁМ" in user and "stack_required: python, docker" in user and "grade: middle" in user
    res = j["result"]
    tags = {i["tag"]: i for i in res["stack_required"] + res["stack_desired"]}
    # новое от модели — с цитатой и подписью модели; тег словаря, подтверждённый моделью, — confirmed_by
    assert tags["grpc"]["evidence"]["source"] == "llm" and tags["grpc"]["evidence"]["model"] == "Claude Sonnet 5.5"
    assert tags["grpc"]["evidence"]["quote"] == "межсервисное взаимодействие"
    assert tags["python"]["evidence"]["source"] == "rules" and tags["python"]["evidence"]["confirmed_by"] == "Claude Sonnet 5.5"
    # «убрать docker» и «грейд senior» — только предложения: требования словаря не тронуты
    assert "docker" in tags and res["grade"] == "middle"
    kinds = {d["id"]: d for d in j["delta"]}
    assert kinds["add:grpc"]["auto"] and kinds["add:grpc"]["zone"] == "required" and kinds["add:grpc"]["name"] == "gRPC"
    assert kinds["add:rabbitmq"]["zone"] == "desired" and kinds["confirm:python"]["kind"] == "confirm_tag"
    rm = kinds["remove:docker"]
    assert rm["auto"] is False and rm["kind"] == "remove_tag" and rm["evidence"]["quote"] == "для локального запуска"
    sg = kinds["suggest:grade"]
    assert sg["auto"] is False and (sg["value"], sg["current"]) == ("senior", "middle")
    assert sg["evidence"]["quote"] == "ведущий разработчик проекта" and sg["evidence"]["model"] == "Claude Sonnet 5.5"


def test_cache_same_text_is_instant_and_offline(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    inline(monkeypatch)
    net.on("or.test", None, delta_reply)
    t = employer(client)
    first = parse(client, t)
    poll(client, t, first["parse_job"]["id"])
    assert len(net.calls) == 1
    # тот же текст (пробелы и переводы строк по краям) — из кэша, без сети; другой работодатель — тоже
    again = parse(client, t, text="  " + TEXT + "\r\n")
    other = parse(client, employer(client, "hr2@corp.ru", "ООО Лютик"), text=TEXT)
    for r in (again, other):
        assert r["llm"]["cached"] is True and r["method"] == "llm+rules" and r["parse_job"]["status"] == "done"
        assert {d["id"] for d in r["delta"]} >= {"add:grpc", "remove:docker"}
        assert r["text"] == TEXT
    assert len(net.calls) == 1
    # подсказка направления — другой ключ
    parse(client, t, direction="backend")
    assert len(net.calls) == 2
    # ключ — хеш, текста в таблице нет
    with SessionLocal() as db:
        keys = [k for (k,) in db.query(NeedParseJob.key).all()]
    assert all(len(k) == 64 and "Python" not in k for k in keys)


def test_cache_key_normalization():
    k = fast_parse.cache_key(TEXT)
    assert k == fast_parse.cache_key("  " + TEXT + "\n")
    assert fast_parse.cache_key("Python\r\nKafka") == fast_parse.cache_key("Python\nKafka")
    assert k != fast_parse.cache_key(TEXT, "backend") and k != fast_parse.cache_key(TEXT + " Kafka")


def test_model_failure_is_honest(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    inline(monkeypatch)
    net.on("or.test", None, lambda req, body: httpx.Response(500))
    t = employer(client)
    j = poll(client, t, parse(client, t)["parse_job"]["id"])
    assert j["status"] == "failed" and j["llm"]["used"] is False and j["llm"]["reason"] == "http_500"
    assert j["result"]["method"] == "rules" and j["delta"] == []
    assert {"python", "docker"} <= {i["tag"] for i in j["result"]["stack_required"]}
    # отказ не кэшируется: следующий разбор снова идёт к модели
    parse(client, t)
    assert len(net.calls) == 2


def test_schema_rejected_retries_without_schema(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    inline(monkeypatch)
    net.on("or.test", None, lambda req, body: httpx.Response(400, json={"error": "schema"})
           if "response_format" in body else delta_reply(req, body))
    t = employer(client)
    j = poll(client, t, parse(client, t)["parse_job"]["id"])
    assert j["status"] == "done"
    assert [("response_format" in c["body"]) for c in net.calls] == [True, False]


def test_no_llm_keeps_old_contract(client):
    """LLM_DISABLED (conftest): ответ — правила, reason not_configured, задачи нет."""
    t = employer(client)
    r = parse(client, t)
    assert r["method"] == "rules" and r["llm"]["reason"] == "not_configured" and r["parse_job"] is None
    with SessionLocal() as db:
        assert db.query(NeedParseJob).count() == 0


def test_job_owner_404_and_stale(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    monkeypatch.setattr(fast_parse, "_spawn", lambda fn, *a: None)  # процесс «умер» до ответа модели
    t = employer(client)
    r = parse(client, t)
    jid = r["parse_job"]["id"]
    other = employer(client, "hr2@corp.ru", "ООО Лютик")
    assert client.get(f"/api/employer/needs/parse/{jid}", headers=H(other)).status_code == 404
    assert client.get(f"/api/employer/needs/parse/{uuid.uuid4()}", headers=H(t)).status_code == 404
    # повторное нажатие с тем же текстом — та же задача
    assert parse(client, t)["parse_job"]["id"] == jid
    assert poll(client, t, jid, timeout=0)["status"] == "pending"
    with SessionLocal() as db:
        job = db.get(NeedParseJob, uuid.UUID(jid))
        job.created_at = job.created_at - timedelta(seconds=fast_parse.STALE_S + 5)
        db.commit()
    j = poll(client, t, jid, timeout=0)
    assert j["status"] == "failed" and j["llm"]["reason"] == "timeout" and j["result"]["method"] == "rules"


def test_pending_limit_per_user(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    monkeypatch.setattr(fast_parse, "_spawn", lambda fn, *a: None)
    t = employer(client)
    for n in range(fast_parse.MAX_PENDING_PER_USER):
        assert parse(client, t, text=f"{TEXT} Вариант {n}.")["parse_job"]["status"] == "pending"
    r = parse(client, t, text=TEXT + " Ещё один.")
    assert r["parse_job"] is None and r["llm"]["reason"] == "busy" and r["method"] == "rules"


def test_full_mode_is_synchronous_legacy(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, delta_reply)
    t = employer(client)
    r = parse(client, t, mode="full")
    assert r["method"] == "llm+rules" and "parse_job" not in r
    body = net.calls[0]["body"]
    assert "response_format" not in body and body["max_tokens"] == 2500


def test_saved_need_keeps_model_provenance(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    inline(monkeypatch)
    net.on("or.test", None, delta_reply)
    t = employer(client)
    res = poll(client, t, parse(client, t)["parse_job"]["id"])["result"]
    req = {k: res[k] for k in ("direction", "grade", "stack_required", "stack_desired", "work_format", "evidence")}
    r = client.post("/api/employer/needs", json={"text": TEXT, "requirements": req}, headers=H(t))
    assert r.status_code == 201, r.text
    saved = {i["tag"]: i["evidence"] for i in r.json()["requirements"]["stack_required"]}
    assert saved["grpc"]["model"] == "Claude Sonnet 5.5" and saved["python"]["confirmed_by"] == "Claude Sonnet 5.5"


@pytest.mark.parametrize("bad", [{"evidence": {"quote": "x", "model": "m" * 61}}])
def test_evidence_model_label_is_bounded(client, bad):
    t = employer(client)
    req = {"stack_required": [{"tag": "python", **bad}]}
    r = client.post("/api/employer/needs", json={"text": TEXT, "requirements": req}, headers=H(t))
    assert r.status_code == 422


def test_no_format_suggestion_inside_allowed_formats(monkeypatch, net):
    """«Офис или гибрид»: словарь принял оба формата — предложение модели «гибрид» вместо «офис» не показываем."""
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, LLM_CHAIN="openrouter")
    text = "Go-разработчик middle: Kafka, PostgreSQL. Москва, офис или гибрид."
    net.on("or.test", None, lambda req, body: reply(json.dumps({**DELTA, "stack_required": [], "stack_desired": [],
                                                                 "remove": [], "grade": None, "work_format": "hybrid",
                                                                 "quotes": {**DELTA["quotes"], "grade": None,
                                                                            "work_format": "офис или гибрид"}}),
                                                     body["model"]))
    r = parse_need(text)
    assert r["work_formats"] and "hybrid" in r["work_formats"] and r["llm_suggest"] == []
    assert "допустимые форматы работы:" in net.calls[0]["body"]["messages"][1]["content"]


def test_migration_fp01_up_down(tmp_path):
    """fp01 — над головой integ (mu01): вверх создаёт need_parse_jobs, вниз до mu01 — убирает."""
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from tests.conftest import alembic_config

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    assert {"key", "status", "result", "user_id"} <= {c["name"] for c in inspect(eng).get_columns("need_parse_jobs")}
    eng.dispose()
    command.downgrade(cfg, "mu01")
    eng = create_engine(url)
    assert "need_parse_jobs" not in inspect(eng).get_table_names()
    eng.dispose()
