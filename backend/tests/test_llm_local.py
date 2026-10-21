"""Провайдер local (открытая модель на этой машине, профиль docker compose llm-local): OpenAI-совместимый сервер
llama.cpp на CPU. Сеть не используется — транспорт httpx подменяется (как в test_llm_chain.py).

Проверяется: без local в LLM_CHAIN ничего не меняется; запрос уходит на LLM_LOCAL_BASE_URL с JSON-режимом и без
рассуждений; свой тайм-аут CPU; переход по цепочке и путь без LLM; подписи «(локально)»; /api/meta; разбор вакансии
и оценка ответа через local без ПДн; профиль в docker-compose.yml не трогает стек без профиля.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from app.core.config import get_settings
from app.modules.llm import client as llm

LOCAL_URL = "http://llm-local.test:8080/v1"
OR_URL = "https://or.test/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def reply(content, model="qwen3.5-9b", **msg):
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": content, **msg}}],
                                     "usage": {"prompt_tokens": 700, "completion_tokens": 300}})


class Net:
    def __init__(self):
        self.calls: list[dict] = []
        self.rules: dict = {}

    def on(self, host, fn):
        self.rules[host] = fn

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"url": str(request.url), "host": request.url.host, "headers": dict(request.headers),
                           "body": body, "timeout": request.extensions.get("timeout")})
        fn = self.rules.get(request.url.host)
        return fn(request, body) if fn else httpx.Response(500, json={"error": "no rule"})


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(llm, "_TRANSPORT", httpx.MockTransport(n))
    llm.reset_state()
    yield n
    llm.reset_state()
    get_settings.cache_clear()


def configure(monkeypatch, **env):
    base = {"LLM_DISABLED": "false", "LLM_BASE_URL": None, "LLM_API_KEY": None, "LLM_MODEL": None,
            "OPENROUTER_API_KEY": None, "LLM_RELAY_URL": None, "LLM_CHAIN": "local",
            "LLM_LOCAL_BASE_URL": LOCAL_URL, "LLM_LOCAL_MODEL": "qwen3.5-9b", "LLM_LOCAL_API_KEY": None,
            "LLM_LOCAL_TIMEOUT_S": None, "LLM_LOCAL_EXTRA_BODY": None, "LLM_LOCAL_JSON_MODE": None,
            "LLM_LOCAL_NO_THINK": None, "LLM_BREAKER_FAILURES": "3", "LLM_BREAKER_COOLDOWN_S": "60"}
    for k in ("LLM_MODEL_PARSE_NEED", "LLM_MODEL_RESUME", "LLM_MODEL_GRADE", "LLM_MODEL_GRADE_SECOND",
              "LLM_TIMEOUT_PARSE_NEED", "LLM_TIMEOUT_GRADE", "LLM_GRADING_MODEL"):
        base.setdefault(k, None)
    base.update(env)
    for k, v in base.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    get_settings.cache_clear()


MSG = [{"role": "user", "content": "привет"}]


# ------------------------------------------------------------------ без local в цепочке — как раньше
def test_local_settings_without_chain_change_nothing(monkeypatch, net):
    # docker-compose всегда передаёт api LLM_LOCAL_BASE_URL и LLM_LOCAL_MODEL; без LLM_CHAIN с local они не влияют
    configure(monkeypatch, LLM_CHAIN=None, OPENROUTER_API_KEY="sk-or-test", OPENROUTER_BASE_URL=OR_URL)
    assert llm.routes("parse_need") == []  # один провайдер yandex из LLM_* — не настроен, local не подмешивается
    assert llm.chat(MSG).error == "not_configured" and net.calls == []
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex", OPENROUTER_API_KEY="sk-or-test", OPENROUTER_BASE_URL=OR_URL)
    assert [r.provider for r in llm.routes("parse_need")] == ["openrouter"]
    assert all(x["provider"] != "local" for x in llm.status()["chain"])


def test_local_not_configured_without_url_or_model(monkeypatch, net):
    configure(monkeypatch, LLM_LOCAL_BASE_URL="")
    assert llm.routes("parse_need") == [] and not get_settings().llm_configured
    configure(monkeypatch, LLM_LOCAL_MODEL="")
    assert llm.chat(MSG).error == "not_configured" and net.calls == []


# ------------------------------------------------------------------ запрос к локальному серверу
def test_local_request_json_mode_no_thinking(monkeypatch, net):
    configure(monkeypatch)
    net.on("llm-local.test", lambda req, body: reply('{"a": 1}'))
    r = llm.chat(MSG, want_json=True, func="parse_need")
    assert r.ok and r.data == {"a": 1} and r.provider == "local" and r.model == "qwen3.5-9b"
    assert r.label == "языковая модель (локально)"  # интерфейс: без имён моделей (21.10)
    (c,) = net.calls
    assert c["url"] == LOCAL_URL + "/chat/completions"
    b = c["body"]
    assert b["model"] == "qwen3.5-9b" and b["response_format"] == {"type": "json_object"}
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    # ни параметров OpenRouter, ни ключа: локальному серверу они не нужны
    assert "provider" not in b and "reasoning" not in b and "authorization" not in c["headers"]
    assert "x-title" not in c["headers"] and "http-referer" not in c["headers"]
    # текстовый ответ — без JSON-режима
    net.calls.clear()
    assert llm.chat(MSG, func="parse_need").ok and "response_format" not in net.calls[0]["body"]


def test_local_key_extra_body_and_switches(monkeypatch, net):
    configure(monkeypatch, LLM_LOCAL_API_KEY="local-test-SECRET", LLM_LOCAL_JSON_MODE="false", LLM_LOCAL_NO_THINK="false",
              LLM_LOCAL_EXTRA_BODY='{"reasoning": {"enabled": false}, "top_k": 20}')
    net.on("llm-local.test", lambda req, body: reply('{"a": 1}'))
    assert llm.chat(MSG, want_json=True, func="resume").ok
    c = net.calls[0]
    assert c["headers"]["authorization"] == "Bearer local-test-SECRET"
    assert "response_format" not in c["body"] and "chat_template_kwargs" not in c["body"]
    assert c["body"]["reasoning"] == {"enabled": False} and c["body"]["top_k"] == 20
    assert "local-test-SECRET" not in json.dumps(llm.status(), ensure_ascii=False)
    # невалидные доп. поля игнорируются, запрос всё равно уходит
    configure(monkeypatch, LLM_LOCAL_EXTRA_BODY="[1, 2")
    net.calls.clear()
    assert llm.chat(MSG, want_json=True, func="resume").ok and "top_k" not in net.calls[0]["body"]


def test_local_strips_think_block(monkeypatch, net):
    configure(monkeypatch)
    net.on("llm-local.test", lambda req, body: reply('<think>\nпроверю {"черновик": 0}\n</think>\n\n{"a": 2}'))
    r = llm.chat(MSG, want_json=True, func="parse_need")
    assert r.ok and r.data == {"a": 2} and not r.text.startswith("<think>")


def test_local_truncated_reply_falls_to_rules(monkeypatch, net):
    # обрезанный JSON (лимит токенов) — невалиден, вызывающий идёт по правилам
    configure(monkeypatch)
    net.on("llm-local.test", lambda req, body: reply('{"stack_required": [{"tag": "python", "quo'))
    r = llm.chat(MSG, want_json=True, func="parse_need")
    assert not r.ok and r.error == "invalid_json" and r.attempts[0]["provider"] == "local"


# ------------------------------------------------------------------ тайм-аут CPU
def test_local_timeout_per_provider(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,local", OPENROUTER_API_KEY="sk-or-test", OPENROUTER_BASE_URL=OR_URL,
              LLM_LOCAL_TIMEOUT_S="50")
    o, loc = llm.routes("parse_need")
    assert (o.provider, o.timeout_s) == ("openrouter", 25.0)  # у облака — как у функции
    assert (loc.provider, loc.timeout_s) == ("local", 50.0)
    assert llm.routes("grade")[1].timeout_s == 50.0
    assert llm.routes("parse_need", timeout_s=7)[1].timeout_s == 7.0  # явный тайм-аут вызывающего важнее
    configure(monkeypatch, LLM_LOCAL_TIMEOUT_S=None)
    assert llm.routes("parse_need")[0].timeout_s == 25.0 and llm.routes("grade")[0].timeout_s == 40.0
    assert llm.status()["functions"]["parse_need"]["local_timeout_s"] == 25.0


def test_local_timeout_respects_deadline(monkeypatch, net):
    import time

    configure(monkeypatch, LLM_LOCAL_TIMEOUT_S="50")
    net.on("llm-local.test", lambda req, body: reply('{"a": 1}'))
    assert llm.chat(MSG, want_json=True, func="grade", deadline=time.monotonic() + 12).ok
    t = net.calls[0]["timeout"]
    assert t["read"] <= 12.0  # общий бюджет оценки урезает тайм-аут CPU


# ------------------------------------------------------------------ цепочка и путь без LLM
def test_local_down_goes_to_rules_and_breaker(monkeypatch, net):
    # модель ещё скачивается: сервер не слушает — сразу правила, после 3 ошибок автомат не ждёт её 60 с
    configure(monkeypatch)
    net.on("llm-local.test", lambda req, body: (_ for _ in ()).throw(httpx.ConnectError("down", request=req)))
    for _ in range(3):
        r = llm.chat(MSG, want_json=True, func="parse_need")
        assert not r.ok and r.error == "ConnectError"
    r = llm.chat(MSG, want_json=True, func="parse_need")
    assert r.error == "circuit_open" and len(net.calls) == 3
    assert llm.status()["breaker"]["local:qwen3.5-9b"]["open"] is True
    # сервер загружает модель: HTTP 503 — тоже переход дальше
    llm.reset_state()
    net.on("llm-local.test", lambda req, body: httpx.Response(503, json={"error": {"message": "Loading model"}}))
    assert llm.chat(MSG, want_json=True, func="parse_need").error == "http_503"


def test_cloud_then_local_fallback(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,local", OPENROUTER_API_KEY="sk-or-test", OPENROUTER_BASE_URL=OR_URL)
    net.on("or.test", lambda req, body: httpx.Response(403, json={"error": {"message": "region"}}))
    net.on("llm-local.test", lambda req, body: reply('{"a": 3}'))
    r = llm.chat(MSG, want_json=True, func="parse_need")
    assert r.ok and r.provider == "local" and [a["provider"] for a in r.attempts] == ["openrouter", "local"]
    assert llm.status()["last"]["parse_need"]["fallback"] is True
    assert llm.status()["last"]["parse_need"]["model_label"] == "Qwen3.5 9B (локально)"


def test_local_model_per_function_and_explicit(monkeypatch, net):
    configure(monkeypatch, LLM_MODEL_GRADE="local=qwen2.5-7b-instruct")
    assert llm.routes("grade")[0].model == "qwen2.5-7b-instruct"
    assert llm.routes("parse_need")[0].model == "qwen3.5-9b"
    (r,) = llm.routes("grade", model="local=qwen3.5-4b")
    assert (r.provider, r.model) == ("local", "qwen3.5-4b")
    # вторая оценка в цепочке local — та же модель (критерии в обратном порядке, docs/LLM.md, раздел 4)
    assert llm.routes("grade_second")[0].model == "qwen3.5-9b"


def test_function_off_goes_without_llm(monkeypatch, net):
    """LLM_MODEL_<FUNC>=off — функция без модели (сразу правила / эксперт), остальные функции — через модель."""
    from app.modules.matching import need_parser as NP

    configure(monkeypatch, LLM_MODEL_PARSE_NEED="off", LLM_MODEL_RESUME="local=off")
    assert llm.routes("parse_need") == [] and llm.routes("resume") == []
    assert llm.routes("grade")[0].model == "qwen3.5-9b" and llm.routes("grade_second")[0].model == "qwen3.5-9b"
    net.on("llm-local.test", lambda req, body: (_ for _ in ()).throw(AssertionError("parse_need не должен звать модель")))
    req = NP.parse_need("Ищем Python-разработчика: Django, PostgreSQL, Docker. Опыт от 3 лет.")
    assert req["method"] == "rules" and req["llm"] == {"used": False, "reason": "not_configured", "attempts": []}
    assert not net.calls
    assert llm.status()["functions"]["parse_need"]["models"] == []
    # «off» действует и для облачной цепочки; модель с подстрокой off в имени не выключает функцию
    configure(monkeypatch, LLM_CHAIN="openrouter", OPENROUTER_API_KEY="k", LLM_MODEL_PARSE_NEED="off",
              LLM_MODEL_GRADE="openrouter=vendor/offline-model")
    assert llm.routes("parse_need") == [] and llm.routes("grade")[0].model == "vendor/offline-model"


def test_llm_local_env_file_profile(monkeypatch, net):
    """Файл, который подключает make llm-local: цепочка local; разбор вакансии и резюме — правила (замер в
    docs/LLM.md, раздел 9), оценка открытых ответов и вторая оценка — Qwen; бюджет укладывается в 60 с nginx."""
    env = {}
    for line in (ROOT / "infra/llm-local/llm-local.env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    configure(monkeypatch, **env)
    assert llm.routes("parse_need") == [] and llm.routes("resume") == []
    (g,) = llm.routes("grade")
    assert (g.provider, g.model) == ("local", "qwen3.5-9b") and g.timeout_s <= 50
    assert float(env["LLM_GRADING_BUDGET_S"]) < 60


# ------------------------------------------------------------------ подписи и /api/meta
@pytest.mark.parametrize("model,label", [
    ("qwen3.5-9b", "Qwen3.5 9B"), ("qwen/qwen3.5-9b", "Qwen3.5 9B"), ("qwen3.5-4b", "Qwen3.5 4B"),
    ("qwen/qwen-2.5-7b-instruct", "Qwen2.5 7B Instruct"), ("qwen2.5-7b-instruct", "Qwen2.5 7B Instruct"),
    ("Qwen3.5-9B-GGUF", "Qwen3.5 9B"), ("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5"),
    ("gpt://b1/yandexgpt/latest", "YandexGPT"), ("qwen3.6-35b-a3b/latest", "qwen3.6-35b-a3b"),
])
def test_model_labels(model, label):
    assert llm.model_name(model) == label  # служебное имя (журналы, /api/meta)
    assert llm.route_name("openrouter", model) == label
    assert llm.route_name("local", model) == f"{label} (локально)"
    assert llm.route_label("openrouter", model) == "языковая модель"  # интерфейс: без имён моделей (21.10)
    assert llm.route_label("local", model) == "языковая модель (локально)"


def test_meta_shows_local_chain(monkeypatch, net):
    configure(monkeypatch, LLM_LOCAL_TIMEOUT_S="50")
    st = llm.status()
    assert st["configured"] is True and st["provider"] == "local" and st["model"] == "qwen3.5-9b"
    assert st["chain"] == [{"provider": "local", "configured": True, "relay": False, "local": True}]
    for f in llm.FUNCTIONS:
        assert st["functions"][f]["models"] == [{"provider": "local", "model": "qwen3.5-9b",
                                                 "label": "Qwen3.5 9B (локально)"}]
        assert st["functions"][f]["local_timeout_s"] == 50.0
    assert LOCAL_URL not in json.dumps(st)  # адрес сервера модели в /api/meta не нужен


# ------------------------------------------------------------------ функции продукта через local
def test_parse_need_through_local_without_pii(monkeypatch, net):
    from app.modules.matching import need_parser as NP

    configure(monkeypatch)
    text = ("Ищем Python-разработчика (middle). Обязательно: Django, PostgreSQL, Docker. Будет плюсом Kafka. "
            "Опыт от 3 лет, удалённо. Рекрутер — Пётр Сидоров, petr.sidorov@example.com, +7 916 123-45-67.")
    seen = {}

    def answer(req, body):
        seen["user"] = body["messages"][-1]["content"]
        return reply(json.dumps({"direction": "backend", "grade": "middle",
                                 "stack_required": [{"tag": "kafka", "weight": 0.4, "quote": "Будет плюсом Kafka"}],
                                 "stack_desired": [], "experience_years_min": 3, "work_format": "remote",
                                 "quotes": {}}, ensure_ascii=False))

    net.on("llm-local.test", answer)
    req = NP.parse_need(text)
    assert req["llm"]["used"] is True and req["llm"]["provider"] == "local"
    assert req["llm"]["model_label"] == "языковая модель (локально)" and req["method"] == "llm+rules"
    assert "petr.sidorov@example.com" not in seen["user"] and "123-45-67" not in seen["user"]
    assert "Сидоров" not in seen["user"]
    assert net.calls[0]["body"]["response_format"] == {"type": "json_object"}
    # модель недоступна — тот же текст разбирается словарём, без ошибки
    llm.reset_state()
    net.on("llm-local.test", lambda req, body: (_ for _ in ()).throw(httpx.ConnectError("down", request=req)))
    req2 = NP.parse_need(text)
    assert req2["llm"]["used"] is False and req2["llm"]["reason"] == "ConnectError"
    assert {i["tag"] for i in req2["stack_required"]} >= {"django", "postgresql", "docker"}


def test_grade_through_local_second_opinion_same_model(monkeypatch, net):
    from app.modules.assessment import grader as G

    configure(monkeypatch, LLM_LOCAL_TIMEOUT_S="50", LLM_GRADING_BUDGET_S="50")
    rubric = {"criteria": [{"id": "cause", "weight": 0.5, "description": "Названа причина"},
                           {"id": "fix", "weight": 0.5, "description": "Предложено исправление"}],
              "strong": "ЭТАЛОН-СИЛЬНЫЙ", "medium": "ЭТАЛОН-СРЕДНИЙ", "weak": "ЭТАЛОН-СЛАБЫЙ"}
    answer = ("Причина в том, что соединение с базой не закрывается при исключении, пул исчерпывается. "
              "Исправление: использовать контекстный менеджер with и ограничить размер пула.")

    def grade(req, body):
        # балл у порога (0,5) → вторая оценка той же локальной моделью, критерии в обратном порядке
        return reply(json.dumps({"criteria": {"cause": {"score": 0.5, "quote": "соединение с базой не закрывается"},
                                              "fix": {"score": 0.5, "quote": "контекстный менеджер with"}},
                                 "level": "medium", "comment": "частично", "manipulation": False},
                                ensure_ascii=False))

    net.on("llm-local.test", grade)
    out = G.grade_open(stem="Сервис падает под нагрузкой", code=None, step_prompt="Найдите причину",
                       rubric=rubric, answer=answer)
    assert out.provider == "local" and out.model == "qwen3.5-9b" and "near_threshold" in out.checks
    assert out.second["provider"] == "local" and out.second["model"] == "qwen3.5-9b"
    assert (out.status, out.method, out.score) == ("scored", "llm2", 0.5)
    assert len(net.calls) == 2 and all(c["host"] == "llm-local.test" for c in net.calls)
    first, second = (c["body"]["messages"][0]["content"] for c in net.calls)
    assert first != second  # независимый второй вызов: другой порядок критериев и эталонов
    assert all(c["body"]["response_format"] == {"type": "json_object"} for c in net.calls)


# ------------------------------------------------------------------ docker compose: профиль llm-local
def test_compose_profile_llm_local():
    dc = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = dc["services"]["llm-local"]
    assert svc["profiles"] == ["llm-local"]  # без профиля сервис не запускается
    assert "llama.cpp:server" in svc["image"] and "llm_models" in dc["volumes"]
    cmd = " ".join(str(x) for x in svc["command"])
    assert "--hf-repo" in cmd and "Q4_K_M" in cmd and "--reasoning off" in cmd and "--no-mmproj" in cmd
    # память предсказуема: веса целиком в памяти процесса, кэш подсказок ограничен (по умолчанию llama.cpp — 8 ГБ)
    assert "--load-mode none" in cmd and "--cache-ram" in cmd
    assert any(v.startswith("llm_models:") for v in svc["volumes"])  # модель — в томе, не в образе и не в репозитории
    assert svc["ports"][0].startswith("127.0.0.1:")
    api = dc["services"]["api"]
    # api не зависит от модели (стек без профиля поднимается), LLM_CHAIN в environment не переопределяется
    assert "llm-local" not in (api.get("depends_on") or {})
    assert "LLM_CHAIN" not in api["environment"]
    assert any("LLM_LOCAL_ENV_FILE" in e["path"] and e["required"] is False for e in api["env_file"])
    env = (ROOT / "infra/llm-local/llm-local.env").read_text(encoding="utf-8")
    assert "LLM_CHAIN=local" in env.splitlines()
    assert not any(k in env for k in ("API_KEY=", "TOKEN=", "SECRET"))
    assert "llm-local:" in (ROOT / "Makefile").read_text(encoding="utf-8")
    assert not list(ROOT.glob("**/*.gguf"))


def test_compose_llm_local_threads_from_nproc():
    """--threads -1 у llama.cpp считает все ядра хоста (на 8 vCPU сервера проверок — 192 потока), поэтому точка входа
    берёт nproc или LLM_LOCAL_THREADS. Проверяем сам скрипт точки входа ($$ — экранирование подстановки compose)."""
    import os
    import subprocess

    ep = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["llm-local"]["entrypoint"]
    assert ep[:2] == ["/bin/sh", "-c"] and "/app/llama-server" in ep[2]
    script = ep[2].replace("$$", "$").replace("exec /app/llama-server", "exec echo")

    def run(threads: str) -> list[str]:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LLM_THREADS": threads}
        return subprocess.run(["/bin/sh", "-c", script, *ep[3:], "--hf-repo", "x:Q4_K_M"], env=env,
                              capture_output=True, text=True, check=True).stdout.split()

    assert run("") == ["--threads", str(len(os.sched_getaffinity(0))), "--hf-repo", "x:Q4_K_M"]
    assert run("3") == ["--threads", "3", "--hf-repo", "x:Q4_K_M"]
