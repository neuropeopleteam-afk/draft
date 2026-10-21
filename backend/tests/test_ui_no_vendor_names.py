"""Аудит заявлений (21.10, P0 А19 №3): ответы API, которые рисует интерфейс, не называют модели и поставщиков.

Было: на /employer/needs у навыка «подтверждено: Claude Sonnet 5.5», «разбор: словарь + Claude Sonnet 5.5 · из кэша»;
в итоге теста — «Две оценки: Claude Sonnet 5.5 … · Claude Fable 5.1». Правило владельца: на сайте поставщиков и имена
моделей не называть. Стало: подпись для интерфейса — «языковая модель», вторая оценка — «вторая модель»
(llm.client.model_label); служебные идентификаторы (поле provider, id вида anthropic/…) и журналы не меняются.

Проверяются: разбор потребности (сразу, фоновая задача и режим full), сохранённая потребность и её подборка, оценка
развёрнутого ответа с второй оценкой и проверкой скептиком, данные первого экрана /validation. Сеть не используется
(tests/test_llm_chain.py: Net).
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from app.modules.llm import client as llm
from tests.test_day2_rules import H, employer
from tests.test_fast_parse import TEXT, delta_reply, inline, parse, poll
from tests.test_llm_chain import FABLE, SONNET, _go, _grade, configure, net  # noqa: F401 — фикстура net

VENDOR = re.compile(r"claude|sonnet|fable|anthropic|openai|\bgpt|gemini|yandex|deepseek|grok|kimi|openrouter", re.I)
ID = re.compile(r"^(?:[\w.\-]+/)+[\w.\-:]+$|^gpt://")  # служебный идентификатор модели (anthropic/claude-…), не подпись
INTERNAL_KEYS = {"provider", "model_reported"}


def leaks(obj, path="") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in INTERNAL_KEYS:
                out += leaks(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += leaks(v, f"{path}[{i}]")
    elif isinstance(obj, str) and VENDOR.search(obj) and not ID.match(obj.strip()):
        out.append(f"{path}: {obj[:120]}")
    return out


def test_labels_are_neutral_names_stay_internal():
    assert llm.model_label("anthropic/claude-sonnet-5.5") == "языковая модель"
    assert llm.model_label("anthropic/claude-fable-5.1", second=True) == "вторая модель"
    assert llm.route_label("local", "qwen3.5-9b") == "языковая модель (локально)"
    assert llm.model_label(None) == "" and llm.model_label("") == ""
    assert llm.model_name("anthropic/claude-sonnet-5.5") == "Claude Sonnet 5.5"  # журналы и служебные места


def test_need_parse_need_and_selection_have_no_vendor_names(client, monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    inline(monkeypatch)
    net.on("or.test", None, delta_reply)
    t = employer(client)
    first = parse(client, t)
    job = poll(client, t, first["parse_job"]["id"])
    assert job["status"] == "done" and job["result"]["method"] == "llm+rules", job
    assert job["llm"]["model_label"] == "языковая модель"
    full = parse(client, t, mode="full")
    assert full["method"] == "llm+rules"
    res = job["result"]
    req = {k: res[k] for k in ("direction", "grade", "stack_required", "stack_desired", "work_format", "evidence")}
    r = client.post("/api/employer/needs", json={"text": TEXT, "requirements": req}, headers=H(t))
    assert r.status_code == 201, r.text
    need = r.json()
    ev = {i["tag"]: i["evidence"] for i in need["requirements"]["stack_required"]}
    assert ev["grpc"]["model"] == "языковая модель" and ev["python"]["confirmed_by"] == "языковая модель"
    got = client.get(f"/api/employer/needs/{need['id']}", headers=H(t))
    assert got.status_code == 200, got.text
    versions = got.json().get("selections") or got.json().get("versions") or []
    sel = None
    if versions:
        v = versions[-1].get("version", 1) if isinstance(versions[-1], dict) else 1
        s = client.get(f"/api/employer/needs/{need['id']}/selections/{v}", headers=H(t))
        assert s.status_code == 200, s.text
        sel = s.json()
    found = leaks({"parse": first, "job": job, "full": full, "need": need, "need_get": got.json(), "selection": sel})
    assert not found, "\n".join(found)


def test_open_answer_grade_and_second_have_no_vendor_names(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 0}))  # 0,5 — у порога: нужна вторая оценка
    net.on("or.test", FABLE, _grade({"cause": 1, "fix": 0.5}))
    g = _go()
    assert g.method == "llm2" and g.model_label == "языковая модель", g
    assert g.second and g.second.get("model_label") == "вторая модель", g.second
    found = leaks(dataclasses.asdict(g))
    assert not found, "\n".join(found)


A4_TEXTS = pytest.mark.xfail(strict=True, reason="тексты методики А4 называют модели и поставщиков (expert_surrogate, "
                              "критерий «Техника»): правка — в зоне А4 по решению штаба; после неё xfail снять")


@pytest.mark.parametrize("path", ["/api/validation/report",
                                  pytest.param("/api/validation/headline", marks=A4_TEXTS),
                                  pytest.param("/api/validation/criteria", marks=A4_TEXTS)])
def test_validation_first_screen_has_no_vendor_names(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    found = leaks(r.json())
    assert not found, "\n".join(found[:20])
