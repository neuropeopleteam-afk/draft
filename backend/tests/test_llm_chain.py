"""Цепочка провайдеров LLM (llm/client.py): переход при ошибках, автомат-выключатель, ретранслятор, модели по
функции, вторая оценка спорных ответов, подписи «какая модель ответила» и отсутствие ПДн в запросах к модели.

Сеть не используется: транспорт httpx подменяется (httpx.MockTransport), ответы провайдеров — фиктивные.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import get_settings
from app.modules.llm import client as llm

SONNET, FABLE = "anthropic/claude-sonnet-5.5", "anthropic/claude-fable-5.1"
YA_URL, OR_URL, RELAY = "https://ya.test/v1", "https://or.test/api/v1", "https://relay.test/api/v1"
SECRET_OR, SECRET_YA, SECRET_RELAY = "sk-or-test-SECRET", "ya-test-SECRET", "relay-test-SECRET"


def reply(content: str | None, model: str = "m") -> httpx.Response:
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


class Net:
    """Подменённая сеть: обработчик по (хост, модель) → ответ или исключение; журнал запросов."""

    def __init__(self):
        self.calls: list[dict] = []
        self.rules: dict = {}

    def on(self, host: str, model: str | None, fn):
        self.rules[(host, model)] = fn

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"url": str(request.url), "host": request.url.host, "headers": dict(request.headers),
                           "body": body, "model": body.get("model")})
        fn = self.rules.get((request.url.host, body.get("model"))) or self.rules.get((request.url.host, None))
        if fn is None:
            return httpx.Response(500, json={"error": "no rule"})
        return fn(request, body)


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(llm, "_TRANSPORT", httpx.MockTransport(n))
    llm.reset_state()
    yield n
    llm.reset_state()
    get_settings.cache_clear()


def configure(monkeypatch, **env):
    base = {"LLM_DISABLED": "false", "LLM_PROVIDER": "yandex_ai_studio", "LLM_BASE_URL": YA_URL,
            "LLM_API_KEY": SECRET_YA, "LLM_FOLDER_ID": "b1folder", "LLM_MODEL": "gpt://b1folder/yandexgpt/latest",
            "OPENROUTER_API_KEY": SECRET_OR, "OPENROUTER_BASE_URL": OR_URL, "LLM_BREAKER_FAILURES": "2",
            "LLM_BREAKER_COOLDOWN_S": "30"}
    base.update(env)
    for k, v in base.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    get_settings.cache_clear()


MSG = [{"role": "user", "content": "привет"}]
OK_JSON = lambda req, body: reply('{"a": 1}', body["model"])  # noqa: E731


# ------------------------------------------------------------------ без новых переменных — как раньше
def test_legacy_single_provider_unchanged(monkeypatch, net):
    configure(monkeypatch, OPENROUTER_API_KEY=None)
    net.on("ya.test", None, OK_JSON)
    r = llm.chat(MSG, want_json=True)
    assert r.ok and r.data == {"a": 1} and r.provider == "yandex" and r.model == "yandexgpt/latest"
    (c,) = net.calls
    assert c["url"] == YA_URL + "/chat/completions" and c["model"] == "gpt://b1folder/yandexgpt/latest"
    assert c["headers"]["authorization"] == f"Api-Key {SECRET_YA}" and c["headers"]["openai-project"] == "b1folder"
    assert "provider" not in c["body"]  # параметры OpenRouter провайдеру LLM_* не отправляются
    st = llm.status()
    assert (st["configured"], st["provider"], st["model"]) == (True, "yandex_ai_studio", "yandexgpt/latest")
    assert [x["provider"] for x in st["chain"]] == ["yandex"]
    # оценка — LLM_GRADING_MODEL, тайм-аут оценки — LLM_GRADING_TIMEOUT_S
    configure(monkeypatch, OPENROUTER_API_KEY=None, LLM_GRADING_MODEL="gpt-oss-120b/latest")
    (g,) = llm.routes("grade")
    assert g.model == "gpt://b1folder/gpt-oss-120b/latest" and g.timeout_s == 40.0
    assert llm.routes("grade_second")[0].model == g.model  # та же модель → второй оценки не будет
    assert llm.routes("parse_need")[0].timeout_s == 25.0


def test_disabled_and_not_configured(monkeypatch, net):
    configure(monkeypatch, LLM_DISABLED="true", LLM_CHAIN="openrouter,yandex")
    assert llm.chat(MSG).error == "not_configured" and not get_settings().llm_configured
    configure(monkeypatch, LLM_CHAIN="openrouter", OPENROUTER_API_KEY=None)
    assert llm.chat(MSG).error == "not_configured" and net.calls == []


# ------------------------------------------------------------------ переход по цепочке
@pytest.mark.parametrize("failure,error", [
    (lambda req, body: httpx.Response(503, text="busy"), "http_503"),
    (lambda req, body: httpx.Response(403, json={"error": {"message": "region"}}), "http_403"),
    (lambda req, body: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=req)), "timeout"),
    (lambda req, body: (_ for _ in ()).throw(httpx.ConnectError("down", request=req)), "ConnectError"),
    (lambda req, body: reply("извините, не могу", body["model"]), "invalid_json"),
    (lambda req, body: reply("", body["model"]), "empty"),
    (lambda req, body: httpx.Response(200, json={"error": {"message": "overloaded"}}), "provider_error"),
    (lambda req, body: httpx.Response(200, text="<html>bad gateway</html>"), "JSONDecodeError"),
])
def test_chain_falls_back(monkeypatch, net, failure, error):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", None, failure)
    net.on("ya.test", None, OK_JSON)
    r = llm.chat(MSG, want_json=True, func="parse_need")
    assert r.ok and r.provider == "yandex" and r.model == "yandexgpt/latest"
    assert [a["provider"] for a in r.attempts] == ["openrouter", "yandex"]
    assert r.attempts[0]["error"] == error and r.attempts[0]["model"] == SONNET
    assert llm.status()["last"]["parse_need"]["fallback"] is True


def test_validate_rejects_reply_and_goes_next(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", None, lambda req, body: reply('{"wrong": true}', body["model"]))
    net.on("ya.test", None, OK_JSON)
    r = llm.chat(MSG, want_json=True, validate=lambda d: "a" in d)
    assert r.ok and r.provider == "yandex" and r.attempts[0]["error"] == "invalid_reply"


def test_all_fail_returns_error_without_exception(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", None, lambda req, body: httpx.Response(500))
    net.on("ya.test", None, lambda req, body: httpx.Response(429))
    r = llm.chat(MSG, want_json=True, func="resume")
    assert not r.ok and r.error == "http_429" and len(r.attempts) == 2
    assert llm.status()["last"]["resume"]["error"] == "http_429"


def test_openrouter_first_success(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", None, OK_JSON)
    r = llm.chat(MSG, want_json=True, func="grade")
    assert r.ok and r.provider == "openrouter" and r.model == SONNET and r.label == "языковая модель"
    (c,) = net.calls
    assert c["url"] == OR_URL + "/chat/completions" and c["headers"]["authorization"] == f"Bearer {SECRET_OR}"
    assert c["body"]["provider"] == {"data_collection": "deny"}
    assert "x-relay-token" not in c["headers"]


# ------------------------------------------------------------------ автомат-выключатель
def test_circuit_breaker_skips_dead_provider(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    clock = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    net.on("or.test", None, lambda req, body: (_ for _ in ()).throw(httpx.ConnectTimeout("x", request=req)))
    net.on("ya.test", None, OK_JSON)
    for _ in range(2):  # две ошибки подряд → автомат открыт
        assert llm.chat(MSG, want_json=True).provider == "yandex"
    n = len(net.calls)
    r = llm.chat(MSG, want_json=True)
    assert r.provider == "yandex" and r.attempts[0]["error"] == "circuit_open"
    assert len(net.calls) == n + 1 and net.calls[-1]["host"] == "ya.test"  # мёртвый провайдер не вызывался
    br = llm.status()["breaker"][f"openrouter:{SONNET}"]
    assert br["open"] and br["retry_in_s"] == 30
    # через M секунд — одна пробная попытка; провайдер ожил → автомат закрыт
    clock[0] += 31
    net.on("or.test", None, OK_JSON)
    assert llm.chat(MSG, want_json=True).provider == "openrouter"
    assert llm.status()["breaker"] == {}
    # снова ошибка после пробной — открывается сразу (не ждёт N ошибок)
    net.on("or.test", None, lambda req, body: httpx.Response(502))
    clock[0] += 1
    llm.chat(MSG, want_json=True)
    llm.chat(MSG, want_json=True)
    assert llm.status()["breaker"][f"openrouter:{SONNET}"]["open"]


def test_breaker_is_per_model(monkeypatch, net):
    """Недоступная модель второй оценки не выключает основную модель того же провайдера."""
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", FABLE, lambda req, body: httpx.Response(404))
    net.on("or.test", SONNET, OK_JSON)
    net.on("ya.test", None, OK_JSON)
    for _ in range(3):
        assert llm.chat(MSG, want_json=True, func="grade_second").provider == "yandex"
    assert llm.chat(MSG, want_json=True, func="grade").provider == "openrouter"


def test_deadline_limits_chain(monkeypatch, net):
    """Общий бюджет вызывающего: тайм-аут попытки урезается до остатка, после бюджета провайдеры не вызываются."""
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    seen = []

    def slow(req, body):
        seen.append(req.extensions["timeout"]["read"])
        raise httpx.ReadTimeout("slow", request=req)

    net.on("or.test", None, slow)
    net.on("ya.test", None, OK_JSON)
    r = llm.chat(MSG, want_json=True, func="grade", deadline=llm.time.monotonic() + 5)
    assert r.ok and r.provider == "yandex" and 4 <= seen[0] <= 5  # 40 с по настройке → остаток бюджета
    n = len(net.calls)
    r = llm.chat(MSG, want_json=True, func="grade", deadline=llm.time.monotonic() + 0.5)
    assert not r.ok and r.error == "deadline" and len(net.calls) == n


def test_grader_budget_skips_second_opinion(monkeypatch, net):
    """Первая оценка съела бюджет — вторую не ждём, ответ «на проверке» (повтор при завершении теста)."""
    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_GRADING_BUDGET_S="3")
    clock = [100.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])

    def first(req, body):
        clock[0] += 2.5
        return _grade({"cause": 1, "fix": 0})(req, body)

    net.on("or.test", SONNET, first)
    net.on("or.test", FABLE, _grade({"cause": 1, "fix": 0}))
    g = _go()
    assert g.status == "pending" and g.error == "second_opinion_failed" and g.second["error"] == "deadline"
    assert [c["model"] for c in net.calls] == [SONNET]


# ------------------------------------------------------------------ ретранслятор и заголовки
def test_relay_url_and_token(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_RELAY_URL=RELAY, LLM_RELAY_TOKEN=SECRET_RELAY)
    net.on("relay.test", None, OK_JSON)
    assert llm.chat(MSG, want_json=True).ok
    (c,) = net.calls
    assert c["url"] == RELAY + "/chat/completions"
    assert c["headers"]["x-relay-token"] == SECRET_RELAY and c["headers"]["authorization"] == f"Bearer {SECRET_OR}"
    # атрибуция OpenRouter — нейтральная: без названия продукта и домена
    s = get_settings()
    neutral = (c["headers"]["http-referer"] + c["headers"]["x-title"]).lower()
    for word in (s.product_name.lower(), "neuropeople", "fsp", "фсп", "драфт"):
        assert word not in neutral
    st = llm.status()
    assert st["chain"] == [{"provider": "openrouter", "configured": True, "relay": True}]
    dump = json.dumps(st)
    for secret in (SECRET_OR, SECRET_RELAY, SECRET_YA, "relay.test", "b1folder"):
        assert secret not in dump


# ------------------------------------------------------------------ модели и тайм-ауты по функции
def test_models_and_timeouts_per_function(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex", LLM_GRADING_MODEL="gpt-oss-120b/latest",
              LLM_MODEL_RESUME="anthropic/claude-haiku-5.5",
              LLM_MODEL_PARSE_NEED="openrouter=anthropic/claude-opus-5.5,yandex=qwen3.6-35b-a3b/latest",
              LLM_TIMEOUT_PARSE_NEED="7", LLM_TIMEOUT_GRADE_SECOND="55")
    m = lambda f: [(r.provider, llm.short_model(r.model), r.timeout_s) for r in llm.routes(f)]  # noqa: E731
    assert m("parse_need") == [("openrouter", "anthropic/claude-opus-5.5", 7.0), ("yandex", "qwen3.6-35b-a3b/latest", 7.0)]
    assert m("resume") == [("openrouter", "anthropic/claude-haiku-5.5", 25.0), ("yandex", "yandexgpt/latest", 25.0)]
    assert m("grade") == [("openrouter", SONNET, 40.0), ("yandex", "gpt-oss-120b/latest", 40.0)]
    assert m("grade_second") == [("openrouter", FABLE, 55.0), ("yandex", "gpt-oss-120b/latest", 55.0)]
    fn = llm.status()["functions"]
    assert fn["grade_second"]["models"][0] == {"provider": "openrouter", "model": FABLE, "label": "Claude Fable 5.1"}
    # явная модель (сравнение моделей): одна попытка у провайдера по имени модели, без перехода
    assert [(r.provider, r.model) for r in llm.routes(model="yandexgpt/latest")] == [
        ("yandex", "gpt://b1folder/yandexgpt/latest")]
    assert [(r.provider, r.model) for r in llm.routes(model=FABLE)] == [("openrouter", FABLE)]
    assert [r.provider for r in llm.routes(model="yandex=deepseek-v4.1-flash/latest")] == ["yandex"]


def test_reasoning_effort_per_function(monkeypatch, net):
    """Рассуждения OpenRouter: разбор, резюме и вторая оценка — low (быстрее, дешевле, ответ не обрезается), первая
    оценка — по умолчанию модели; default — параметр не передаётся; провайдеру yandex — никогда."""
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex", LLM_REASONING_GRADE="medium", LLM_BREAKER_FAILURES="0")
    net.on("or.test", None, lambda req, body: httpx.Response(500))
    net.on("ya.test", None, OK_JSON)
    for func in ("parse_need", "resume", "grade", "grade_second"):
        llm.chat(MSG, want_json=True, func=func)
    sent = [(c["host"], c["body"].get("reasoning")) for c in net.calls]
    assert sent == [("or.test", {"effort": "low"}), ("ya.test", None), ("or.test", {"effort": "low"}), ("ya.test", None),
                    ("or.test", {"effort": "medium"}), ("ya.test", None), ("or.test", {"effort": "low"}), ("ya.test", None)]
    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_REASONING_GRADE_SECOND="default")
    llm.chat(MSG, want_json=True, func="grade_second")
    assert "reasoning" not in net.calls[-1]["body"]


def test_extract_json_tolerant():
    ex = llm._extract_json
    assert ex('```json\n{"a": 1}\n```') == {"a": 1}
    # модель «поправила» свой ответ вторым объектом — берётся последний целый объект
    assert ex('{"a": 1, "note": "x"}\n\nПоправка: поле note лишнее.\n{"a": 2}') == {"a": 2}
    assert ex('Ответ: {"a": 1} — и пояснение без скобок') == {"a": 1}
    # обрезанный ответ (лимит токенов) — невалиден, а не внутренний объект
    assert ex('{"criteria": {"c1": {"score": 1, "quote": "x"}, "c2": {"score": 0.5, "quo') is None
    assert ex("[1, 2]") == [1, 2] and ex("нет JSON") is None


def test_model_labels():
    assert llm.model_name("anthropic/claude-sonnet-5.5") == "Claude Sonnet 5.5"
    assert llm.model_name("anthropic/claude-fable-5.1:batch") == "Claude Fable 5.1"
    assert llm.model_name("gpt://b1abc/yandexgpt/latest") == "YandexGPT"
    assert llm.model_name("yandexgpt-5.1/latest") == "YandexGPT 5.1"  # подпись в режиме LLM_CHAIN=yandex
    assert llm.model_name("gpt-oss-120b/latest") == "gpt-oss-120b"
    assert llm.model_name(None) == "" and llm.model_label(None) == ""
    assert llm.model_label("anthropic/claude-sonnet-5.5") == "языковая модель"  # интерфейс: без имён моделей (21.10)


def test_meta_endpoint_reports_chain(monkeypatch, net, client):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex", LLM_RELAY_URL=RELAY, LLM_RELAY_TOKEN=SECRET_RELAY)
    j = client.get("/api/meta").json()["llm"]
    assert j["configured"] and j["provider"] == "openrouter" and j["model"] == SONNET
    assert [c["provider"] for c in j["chain"]] == ["openrouter", "yandex"]
    assert [x["label"] for x in j["functions"]["grade_second"]["models"]] == ["Claude Fable 5.1", "YandexGPT"]
    raw = json.dumps(j)
    assert SECRET_OR not in raw and SECRET_RELAY not in raw and "relay.test" not in raw


# ------------------------------------------------------------------ подписи: какая модель ответила
NEED_TEXT = "Backend-разработчик: Python и брокеры сообщений, межсервисное взаимодействие. Гибрид."


def _need_reply(req, body):
    return reply(json.dumps({"direction": "backend", "stack_required": [
        {"tag": "grpc", "weight": 0.7, "quote": "межсервисное взаимодействие"}]}), body["model"])


def test_need_parser_reports_actual_model(monkeypatch, net):
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", None, _need_reply)
    r = parse_need(NEED_TEXT)
    assert r["method"] == "llm+rules"
    assert r["llm"]["model_label"] == "языковая модель" and not {"provider", "model"} & set(r["llm"])  # провайдер и id модели в ответе API не отдаются (обход А19 №10) — кто ответил, видно по сети
    assert net.calls[-1]["host"] == "or.test" and net.calls[-1]["model"] == SONNET
    grpc = next(i for i in r["stack_required"] if i["tag"] == "grpc")
    assert grpc["evidence"]["source"] == "llm" and grpc["evidence"]["model"] == "языковая модель"
    # основная модель недоступна → ответила запасная, подпись — её
    net.on("or.test", None, lambda req, body: httpx.Response(403))
    net.on("ya.test", None, _need_reply)
    r = parse_need(NEED_TEXT)
    assert r["llm"]["model_label"] == "языковая модель" and r["llm"]["fallback"] is True
    # никто не ответил → правила
    net.on("ya.test", None, lambda req, body: httpx.Response(500))
    r = parse_need(NEED_TEXT)
    assert r["method"] == "rules" and r["llm"]["used"] is False and r["llm"]["reason"] == "http_500"
    assert {i["tag"] for i in r["stack_required"]} >= {"python"}


# ------------------------------------------------------------------ вторая оценка спорных ответов
RUBRIC = {"criteria": [{"id": "cause", "weight": 0.5, "description": "Названа причина"},
                       {"id": "fix", "weight": 0.5, "description": "Предложено исправление"}],
          "strong": "ЭТАЛОН-СИЛЬНЫЙ", "medium": "ЭТАЛОН-СРЕДНИЙ", "weak": "ЭТАЛОН-СЛАБЫЙ"}
ANSWER = "Причина — гонка при бронировании: два запроса читают остаток одновременно. Исправление — блокировка строки."


# цитаты из ANSWER — формат v2 оценщика (feat/integrity): балл > 0 без цитаты из ответа обнуляется, без цитат вовсе —
# причина сомнения (no_quotes) и вторая оценка
QUOTES = {"cause": "два запроса читают остаток одновременно", "fix": "блокировка строки"}


def _grade(crit: dict, level: str = "medium"):
    v2 = {k: {"score": v, "quote": QUOTES[k]} for k, v in crit.items()}
    return lambda req, body: reply(json.dumps({"criteria": v2, "level": level, "comment": "ок"}), body["model"])


def _go(**kw):
    from app.modules.assessment.grader import grade_open

    return grade_open(stem="Найдите ошибку бронирования", code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER,
                      **kw)


def test_second_opinion_only_for_disputed(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 1}, "strong"))  # уверенный балл — второй оценки нет
    g = _go()
    assert g.status == "scored" and g.score == 1.0 and g.method == "llm" and g.second is None and g.checks == []
    assert (g.provider, g.model, g.model_label) == ("openrouter", SONNET, "языковая модель")
    assert [c["model"] for c in net.calls] == [SONNET]


def test_second_opinion_agrees_mean(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 0}))  # 0,5 — у порога
    net.on("or.test", FABLE, _grade({"cause": 1, "fix": 0.5}))  # 0,75
    g = _go()
    assert "near_threshold" in g.checks and [c["model"] for c in net.calls] == [SONNET, FABLE]
    assert g.status == "scored" and g.method == "llm2" and g.score == 0.625 and g.scores == [0.5, 0.75]
    assert g.criteria == {"cause": 1.0, "fix": 0.25}
    assert g.second["model"] == FABLE and g.second["model_label"] == "вторая модель" and g.second["score"] == 0.75
    # второй вызов независимый: эталоны в обратном порядке, первая оценка не передаётся
    sys2 = net.calls[1]["body"]["messages"][0]["content"]
    assert sys2.startswith("Ты — второй, независимый проверяющий")
    assert sys2.index("ЭТАЛОН-СЛАБЫЙ") < sys2.index("ЭТАЛОН-СИЛЬНЫЙ") and "0.5" not in net.calls[1]["body"]["messages"][1]["content"]
    d = g.to_dict()
    assert d["second"]["score"] == 0.75 and d["scores"] == [0.5, 0.75]  # обе оценки — в журнале проверки


def test_second_opinion_disagree_goes_to_expert(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 0.5}, "weak"))  # 0,75 и «weak» — уровень не согласован
    net.on("or.test", FABLE, _grade({"cause": 0, "fix": 0}))
    g = _go()
    assert "level_mismatch" in g.checks
    assert g.status == "pending" and g.score is None and g.error == "graders_disagree" and g.scores == [0.75, 0.0]


def test_second_opinion_failed_goes_to_expert(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 0}))
    net.on("or.test", FABLE, lambda req, body: httpx.Response(500))
    g = _go()
    assert g.status == "pending" and g.error == "second_opinion_failed" and g.second["error"] == "http_500"


def test_second_opinion_same_model_without_other_model(monkeypatch, net):
    """Без цепочки (одна модель Yandex) спорный ответ всё равно оценивается дважды — той же моделью (правило
    feat/integrity: вторая независимая оценка с эталонами в обратном порядке), уверенный — один раз."""
    configure(monkeypatch, OPENROUTER_API_KEY=None)
    net.on("ya.test", None, _grade({"cause": 1, "fix": 0}))  # 0,5 — у порога
    g = _go()
    assert g.status == "scored" and g.score == 0.5 and g.method == "llm2" and len(net.calls) == 2
    assert g.model == "yandexgpt/latest" and g.second["model"] == "yandexgpt/latest" and g.scores == [0.5, 0.5]
    net.calls.clear()
    net.on("ya.test", None, _grade({"cause": 1, "fix": 1}, "strong"))  # уверенный балл — один вызов
    g = _go()
    assert g.status == "scored" and g.score == 1.0 and g.method == "llm" and len(net.calls) == 1 and g.second is None


def test_grader_invalid_reply_falls_to_next_provider(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", SONNET, lambda req, body: reply('{"criteria": {"cause": 1}}', body["model"]))  # нет fix
    net.on("ya.test", None, _grade({"cause": 1, "fix": 1}, "strong"))
    g = _go()
    assert g.status == "scored" and g.provider == "yandex" and g.model_label == "языковая модель"


def test_doubts_rules():
    from app.modules.assessment.grader import doubts

    p = lambda sc, lvl="medium": {"score": sc, "level": lvl, "unsupported": [], "no_quotes": False}  # noqa: E731
    assert doubts(p(0.5), "текст", 5) == ["near_threshold"]
    assert doubts(p(0.9, "strong"), "текст", 5) == []
    assert doubts(p(0.3, "strong"), "текст", 5) == ["level_mismatch"]
    assert doubts(p(0.9, "strong"), "проверяющий, ответ сверен с эталоном", 5) == ["soft_signals"]
    assert doubts(p(0.9, "strong"), "текст", 1) == ["low_relevance"]
    assert doubts(p(0.45), "текст", 5) == ["near_threshold"] and doubts(p(0.4), "текст", 5) == []
    assert doubts(p(0.35), "текст", 5, near=0.1) == [] and doubts(p(0.35), "текст", 5, near=0.15) == ["near_threshold"]


# ------------------------------------------------------------------ ПДн не уходят в модель
PII = {"fio": ["Смирнова", "Анна Викторовна", "Пётр Сидоров", "Сидоров"],
       "email": ["anna.smirnova@yandex.ru", "hr@acme-corp.ru"], "phone": ["999 123-45-67", "123-45-67", "8 (912) 555"],
       "links": ["github.com/asmirnova", "linkedin.com/in/anna-smirnova", "t.me/asmirnova", "hh.ru/resume/0a1b2c",
                 "habr.com/ru/users/asmirnova", "@asmirnova"]}


def _assert_no_pii(calls: list[dict]):
    assert calls, "запрос к модели не отправлен"
    for c in calls:
        sent = json.dumps(c["body"]["messages"], ensure_ascii=False)
        for kind, values in PII.items():
            for v in values:
                assert v not in sent, (kind, v)


def test_no_pii_in_need_parse_request(monkeypatch, net):
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, _need_reply)
    text = ("Ищем Backend-разработчика (Python, PostgreSQL), гибрид. Рекрутер — Пётр Сидоров, +7 999 123-45-67, "
            "hr@acme-corp.ru, t.me/asmirnova. Пишите Сидоров, вопросы — 8 (912) 555-12-34.")
    parse_need(text)
    _assert_no_pii(net.calls)
    assert "Python" in net.calls[0]["body"]["messages"][1]["content"]  # содержание вакансии на месте


def test_no_pii_in_resume_request(monkeypatch, net, client):
    from tests.test_day2_rules import H, _pdf_bytes
    from tests.conftest import register_and_verify

    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, lambda req, body: reply('{"stack": ["react"], "roles": [], "soft_skills": []}', body["model"]))
    t = register_and_verify(client, email="pii@example.com")
    pdf = _pdf_bytes(["Смирнова Анна Викторовна", "Frontend-разработчик", "anna.smirnova@yandex.ru, +7 999 123-45-67",
                      "github.com/asmirnova  linkedin.com/in/anna-smirnova  hh.ru/resume/0a1b2c",
                      "habr.com/ru/users/asmirnova, Telegram: @asmirnova",
                      "Опыт работы 3 года: React, TypeScript. Анна Викторовна — автор доклада о React."])
    r = client.post("/api/me/resume", files={"file": ("cv.pdf", pdf, "application/pdf")}, headers=H(t))
    assert r.status_code == 201, r.text
    _assert_no_pii(net.calls)
    assert r.json()["extracted"]["llm"]["model_label"] == "языковая модель"


def test_no_pii_in_grader_request(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, _grade({"cause": 1, "fix": 1}, "strong"))
    from app.modules.assessment.grader import grade_open

    answer = ("Причина — гонка при бронировании, исправление — SELECT FOR UPDATE. Меня зовут Смирнова Анна Викторовна, "
              "почта anna.smirnova@yandex.ru, телефон +7 999 123-45-67, код — github.com/asmirnova, "
              "профиль linkedin.com/in/anna-smirnova.")
    g = grade_open(stem="Найдите ошибку", code=None, step_prompt=None, rubric=RUBRIC, answer=answer)
    assert g.status == "scored"
    _assert_no_pii(net.calls)
