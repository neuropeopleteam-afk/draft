"""Я17 п. 3: разбор потребности при отказе модели — правила, а не 500. Модель недоступна (HTTP 500/503), молчит
(таймаут, обрыв), отвечает мусором (не JSON, JSON не той формы) — ответ 200, method «rules», llm.used = false,
требования из словаря на месте; быстрый режим (фон), полный режим и создание потребности без готовых требований.
LLM_DISABLED (conftest) — тот же контракт без модели. Сеть не используется (tests/test_llm_chain.py: Net, configure).
"""
from __future__ import annotations

import httpx
import pytest

from app.modules.matching import fast_parse
from tests.test_day2_rules import H, employer
from tests.test_fast_parse import TEXT, inline, parse, poll
from tests.test_llm_chain import configure, net, reply  # noqa: F401 — фикстура net


def _raise(exc):
    def fn(req, body):
        raise exc
    return fn


FAILURES = {
    "http_503": lambda req, body: httpx.Response(503, json={"error": "overloaded"}),
    "timeout": _raise(httpx.ReadTimeout("read timeout")),
    "connect": _raise(httpx.ConnectError("connection refused")),
    "not_json": lambda req, body: reply("Конечно! Вот требования: python, docker", body["model"]),
    "broken_json": lambda req, body: reply('{"stack_required": [{"tag": "python", "weight": 0.9', body["model"]),
    "wrong_shape": lambda req, body: reply('["python", "docker"]', body["model"]),
    "empty": lambda req, body: reply(None, body["model"]),
    "html": lambda req, body: httpx.Response(200, text="<html>502 Bad Gateway</html>", headers={"content-type": "text/html"}),
}


def _rules_ok(r: dict):
    assert r["method"] == "rules", r.get("method")
    assert r["llm"]["used"] is False and r["llm"].get("reason")
    assert {"python", "docker"} <= {i["tag"] for i in r["stack_required"] + r["stack_desired"]}
    for i in r["stack_required"]:
        assert i["evidence"]["quote"]  # у каждого требования — цитата из текста


@pytest.fixture
def model(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_BREAKER_FAILURES="50")
    inline(monkeypatch)
    return net


@pytest.mark.parametrize("kind", sorted(FAILURES))
def test_fast_mode_falls_back_to_rules(client, model, kind):
    model.on("or.test", None, FAILURES[kind])
    t = employer(client)
    first = parse(client, t)
    assert first["method"] == "rules"  # словарь отвечает сразу
    j = poll(client, t, first["parse_job"]["id"])
    assert j["status"] == "failed" and j["delta"] == []
    _rules_ok(j["result"])


@pytest.mark.parametrize("kind", sorted(FAILURES))
def test_full_mode_falls_back_to_rules(client, model, kind):
    model.on("or.test", None, FAILURES[kind])
    t = employer(client)
    _rules_ok(parse(client, t, mode="full"))
    assert model.calls


@pytest.mark.parametrize("kind", ["timeout", "not_json", "http_503"])
def test_create_need_without_requirements_survives_model_failure(client, model, kind):
    model.on("or.test", None, FAILURES[kind])
    t = employer(client)
    r = client.post("/api/employer/needs", json={"title": "Backend middle", "text": TEXT}, headers=H(t))
    assert r.status_code in (200, 201), r.text
    req = r.json().get("requirements") or r.json()
    assert {"python", "docker"} <= {i["tag"] for i in req["stack_required"] + req["stack_desired"]}
    assert model.calls, "создание потребности действительно обращалось к модели"


def test_unexpected_exception_in_background_job_is_failed_not_hanging(client, model, monkeypatch):
    """Любая ошибка внутри фонового разбора: задача «failed» с итогом словаря, а не вечное «pending»."""
    model.on("or.test", None, FAILURES["timeout"])
    real = fast_parse.parse_need

    def boom(*a, use_llm=True, **kw):
        if use_llm:
            raise RuntimeError("неожиданная ошибка")
        return real(*a, use_llm=use_llm, **kw)

    monkeypatch.setattr(fast_parse, "parse_need", boom)
    t = employer(client)
    j = poll(client, t, parse(client, t)["parse_job"]["id"])
    assert j["status"] == "failed" and j["result"]["method"] == "rules" and j["result"]["llm"]["reason"] == "error"


def test_llm_disabled_full_mode_and_create(client):
    """LLM_DISABLED: полный режим и создание — правила, без задачи и без 500."""
    t = employer(client)
    r = parse(client, t, mode="full")
    assert r["method"] == "rules" and r["llm"]["used"] is False and r["llm"]["reason"] == "not_configured"
    r = client.post("/api/employer/needs", json={"title": "Backend middle", "text": TEXT}, headers=H(t))
    assert r.status_code in (200, 201), r.text
