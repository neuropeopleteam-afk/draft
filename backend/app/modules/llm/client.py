"""Цепочка провайдеров LLM поверх OpenAI-совместимого API (POST {base_url}/chat/completions).

Провайдеры (docs/LLM.md):
  yandex      — провайдер из LLM_* (/opt/spectrek_fsp/secrets/llm.env): LLM_PROVIDER (openai_compatible |
                yandex_ai_studio), LLM_BASE_URL, LLM_API_KEY, LLM_FOLDER_ID, LLM_MODEL, LLM_GRADING_MODEL.
                Yandex AI Studio: «Authorization: Api-Key <ключ>» и «OpenAI-Project: <каталог>».
  openrouter  — OpenRouter (OPENROUTER_API_KEY, OPENROUTER_BASE_URL); если задан LLM_RELAY_URL — запросы идут
                на ретранслятор с заголовком X-Relay-Token, ключ OpenRouter передаётся в Authorization как есть.

Порядок — LLM_CHAIN (например «openrouter,yandex»); без него — один провайдер из LLM_*, как раньше.
Модель и тайм-аут — на функцию: parse_need (разбор потребности), resume (резюме), grade (оценка ответа),
grade_second (вторая оценка спорных ответов): LLM_MODEL_<ФУНКЦИЯ>, LLM_TIMEOUT_<ФУНКЦИЯ>.

Переход к следующему провайдеру — при ошибке сети, тайм-ауте, HTTP ≠ 200, пустом ответе, невалидном JSON или
ответе, не прошедшем проверку вызывающего (validate). Автомат-выключатель: после LLM_BREAKER_FAILURES ошибок
подряд пара «провайдер + модель» пропускается LLM_BREAKER_COOLDOWN_S секунд (затем — одна пробная попытка),
чтобы сценарий жюри не ждал мёртвый провайдер. Все провайдеры недоступны — ok=False, вызывающий идёт по
правилам (последний рубеж). Ключи в логи и ответы API не попадают; персональные данные вырезают вызывающие
(resume.pii) до вызова chat.

Для моделей с рассуждениями (gpt-oss) текст ответа может прийти в reasoning_content — учитываем.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
import json
import logging
import re
import ssl
import threading
import time
from typing import Callable

import httpx

from app.core.config import Settings, get_settings

log = logging.getLogger("llm")

FUNCTIONS = ("parse_need", "resume", "grade", "grade_second")
PROVIDERS = ("openrouter", "yandex")
# Решение владельца (08.10): основная модель — Claude Sonnet 5.5, вторая оценка спорных ответов — Claude Fable 5.1
OPENROUTER_DEFAULTS = {"parse_need": "anthropic/claude-sonnet-5.5", "resume": "anthropic/claude-sonnet-5.5",
                       "grade": "anthropic/claude-sonnet-5.5", "grade_second": "anthropic/claude-fable-5.1"}
# Заголовки атрибуции OpenRouter — нейтральные, без названия продукта и домена
OPENROUTER_HEADERS = {"HTTP-Referer": "https://localhost", "X-Title": "llm-client"}
# Только провайдеры OpenRouter, которые не сохраняют и не обучаются на запросах
OPENROUTER_BODY = {"provider": {"data_collection": "deny"}}

_TRANSPORT: httpx.BaseTransport | None = None  # подмена транспорта в тестах (httpx.MockTransport)


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    data: dict | list | None = None
    error: str | None = None
    model: str | None = None  # модель, которая ответила (короткое имя: anthropic/claude-sonnet-5.5, yandexgpt/latest)
    latency_ms: int = 0
    provider: str | None = None
    func: str | None = None
    attempts: list[dict] = field(default_factory=list)  # попытки цепочки: провайдер, модель, ошибка, задержка
    usage: dict | None = None
    model_reported: str | None = None  # что вернул провайдер в поле model

    @property
    def label(self) -> str | None:
        return model_label(self.model) if self.model else None

    def info(self) -> dict:
        """Сводка для сохранения рядом с результатом (без текста ответа)."""
        return {"provider": self.provider, "model": self.model, "model_label": self.label,
                "latency_ms": self.latency_ms, "attempts": self.attempts}


@dataclass
class Route:
    provider: str
    model: str  # как в запросе (для Yandex AI Studio — gpt://<каталог>/…)
    timeout_s: float
    reasoning: str | None = None  # усилие рассуждений (OpenRouter): low | medium | high; None — не передаётся

    @property
    def key(self) -> str:
        return f"{self.provider}:{short_model(self.model)}"


# ------------------------------------------------------------------ имена моделей
def short_model(model: str | None) -> str:
    """gpt://<каталог>/yandexgpt/latest → yandexgpt/latest (каталог в подписи и журнале не нужен)."""
    return re.sub(r"^gpt://[^/]+/", "", model or "")


_LABELS = {"yandexgpt": "YandexGPT", "yandexgpt-lite": "YandexGPT Lite", "gpt-oss-120b": "gpt-oss-120b",
           "gpt-oss-20b": "gpt-oss-20b"}


def model_label(model: str | None) -> str:
    """Человекочитаемое имя для интерфейса: anthropic/claude-sonnet-5.5 → Claude Sonnet 5.5; yandexgpt/latest → YandexGPT."""
    m = short_model(model)
    if not m:
        return ""
    m = m.split(":")[0]  # суффиксы OpenRouter (:batch, :free)
    if m.startswith("anthropic/"):
        name = m.split("/", 1)[1]
        parts = name.split("-")
        return " ".join(p.capitalize() if not re.match(r"^\d", p) else p for p in parts)
    head, _, branch = m.partition("/")
    if branch in ("latest", "rc", "deprecated") or m.startswith("yandexgpt"):
        return _LABELS.get(head, head)
    return m.split("/", 1)[-1]


def _guess_provider(model: str) -> str:
    """Провайдер по имени модели: модели Yandex AI Studio — gpt://… или «имя/ветка» (latest, rc, deprecated)."""
    if model.startswith("gpt://") or re.search(r"/(?:latest|rc|deprecated)$", model):
        return "yandex"
    return "openrouter"


def parse_spec(spec: str | None) -> dict[str | None, str]:
    """«модель» → {None: модель}; «openrouter=a/b,yandex=c/latest» → {провайдер: модель}."""
    out: dict[str | None, str] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        prov, sep, model = part.partition("=")
        if sep and prov.strip().lower() in PROVIDERS:
            out[prov.strip().lower()] = model.strip()
        else:
            out[None] = part
    return out


def resolve_model(name: str | None) -> str | None:
    """Имя модели провайдера yandex: полное (gpt://…) или короткое (gpt-oss-120b/latest) — для Yandex AI Studio
    дополняется каталогом. Без имени — LLM_MODEL."""
    s = get_settings()
    if not name:
        return s.llm_model
    if s.llm_provider == "yandex_ai_studio" and s.llm_folder_id and not name.startswith("gpt://"):
        return f"gpt://{s.llm_folder_id}/{name}"
    return name


# ------------------------------------------------------------------ маршрут: провайдеры и модели функции
def model_for(func: str | None, provider: str, s: Settings | None = None) -> str | None:
    s = s or get_settings()
    f = func if func in FUNCTIONS else None
    spec = parse_spec(getattr(s, f"llm_model_{f}", None) if f else None)
    chain = s.llm_chain_list
    m = spec.get(provider) or (spec.get(None) if chain and chain[0] == provider else None)
    if not m:
        if provider == "openrouter":
            m = OPENROUTER_DEFAULTS.get(f or "parse_need")
        elif provider == "yandex":
            m = (s.llm_grading_model or s.llm_model) if f in ("grade", "grade_second") else s.llm_model
    if not m:
        return None
    return resolve_model(m) if provider == "yandex" else m


def timeout_for(func: str | None, s: Settings | None = None) -> float:
    s = s or get_settings()
    v = getattr(s, f"llm_timeout_{func}", None) if func in FUNCTIONS else None
    if v:
        return float(v)
    return float(s.llm_grading_timeout_s if func in ("grade", "grade_second") else s.llm_timeout_s)


def reasoning_for(func: str | None, s: Settings | None = None) -> str | None:
    s = s or get_settings()
    v = (getattr(s, f"llm_reasoning_{func}", None) if func in FUNCTIONS else None) or "default"
    return v if v in ("low", "medium", "high") else None


def routes(func: str | None = None, model: str | None = None, provider: str | None = None,
           timeout_s: float | None = None) -> list[Route]:
    """Попытки по порядку. Явная модель (сравнение моделей) — одна попытка без перехода: провайдер из префикса
    «openrouter=…»/«yandex=…», аргумента provider или по имени модели."""
    s = get_settings()
    if s.llm_disabled:
        return []
    t = float(timeout_s or timeout_for(func, s))
    if model:
        spec = parse_spec(model)
        prov, m = next(iter(spec.items())) if spec else (None, model)
        prov = provider or prov or _guess_provider(m)
        if not s.llm_provider_configured(prov):
            return []
        return [Route(prov, resolve_model(m) if prov == "yandex" else m, t,
                      reasoning_for(func, s) if prov == "openrouter" else None)]
    out = []
    for p in ([provider] if provider else s.llm_chain_list):
        if not s.llm_provider_configured(p):
            continue
        m = model_for(func, p, s)
        if m:
            out.append(Route(p, m, t, reasoning_for(func, s) if p == "openrouter" else None))
    return out


# ------------------------------------------------------------------ автомат-выключатель
class _Breaker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._st: dict[str, dict] = {}

    def allow(self, key: str) -> bool:
        with self._lock:
            st = self._st.get(key)
            if not st or st["open_until"] <= 0:
                return True
            if time.monotonic() >= st["open_until"]:
                st["open_until"] = 0.0  # полуоткрыт: одна пробная попытка; новая ошибка снова откроет
                st["fails"] = max(0, get_settings().llm_breaker_failures - 1)
                return True
            return False

    def success(self, key: str) -> None:
        with self._lock:
            self._st[key] = {"fails": 0, "open_until": 0.0, "last_error": None}

    def failure(self, key: str, error: str | None) -> None:
        s = get_settings()
        with self._lock:
            st = self._st.setdefault(key, {"fails": 0, "open_until": 0.0, "last_error": None})
            st["fails"] += 1
            st["last_error"] = error
            if s.llm_breaker_failures > 0 and st["fails"] >= s.llm_breaker_failures:
                st["open_until"] = time.monotonic() + s.llm_breaker_cooldown_s
                log.warning("LLM: %s пропускается %.0f с после %d ошибок подряд", key, s.llm_breaker_cooldown_s,
                            st["fails"])

    def snapshot(self) -> dict[str, dict]:
        now = time.monotonic()
        with self._lock:
            return {k: {"fails": v["fails"], "open": v["open_until"] > now,
                        "retry_in_s": max(0, round(v["open_until"] - now)) if v["open_until"] > now else 0,
                        "last_error": v["last_error"]} for k, v in self._st.items()}

    def reset(self) -> None:
        with self._lock:
            self._st.clear()


breaker = _Breaker()
_last_lock = threading.Lock()
_last: dict[str, dict] = {}  # функция → кто ответил последним (для /api/meta)


def reset_state() -> None:
    """Сброс автомата и журнала «кто ответил» (тесты)."""
    breaker.reset()
    with _last_lock:
        _last.clear()


# ------------------------------------------------------------------ один запрос к одному провайдеру
def _extract_json(text: str) -> dict | list | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                pass
            if opener == "{":
                found = _last_object(text, i)
                if found is not None:
                    return found
    return None


def _last_object(text: str, i: int) -> dict | None:
    """Несколько объектов верхнего уровня подряд («JSON … Поправка: … JSON») — последний целый объект.
    Внутрь объектов не спускаемся: обрезанный ответ остаётся невалидным, и цепочка идёт к следующей модели."""
    dec, found = json.JSONDecoder(), None
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            found = obj
        i = text.find("{", end)
    return found


def _headers(s: Settings) -> dict[str, str]:
    """Заголовки провайдера yandex (LLM_*)."""
    h = {"Content-Type": "application/json"}
    if s.llm_provider == "yandex_ai_studio":
        h["Authorization"] = f"Api-Key {s.llm_api_key}"
        if s.llm_folder_id:
            h["OpenAI-Project"] = s.llm_folder_id
    else:
        h["Authorization"] = f"Bearer {s.llm_api_key}"
    return h


def _endpoint(provider: str, s: Settings) -> tuple[str, dict[str, str], dict]:
    if provider == "openrouter":
        h = {"Content-Type": "application/json", "Authorization": f"Bearer {s.openrouter_api_key}",
             **OPENROUTER_HEADERS}
        base = s.openrouter_base_url
        if s.llm_relay_url:
            base = s.llm_relay_url
            if s.llm_relay_token:
                h["X-Relay-Token"] = s.llm_relay_token
        return base.rstrip("/") + "/chat/completions", h, dict(OPENROUTER_BODY)
    return (s.llm_base_url or "").rstrip("/") + "/chat/completions", _headers(s), {}


def _verify(provider: str, s: Settings) -> ssl.SSLContext | bool:
    """TLS для ретранслятора с собственным сертификатом (LLM_RELAY_CA_FILE) — доверяем только ему; иначе — обычная проверка."""
    if provider == "openrouter" and s.llm_relay_url:
        if s.llm_relay_ca_file:
            return ssl.create_default_context(cafile=s.llm_relay_ca_file)
        if s.llm_relay_ca_pem_b64:
            return ssl.create_default_context(cadata=base64.b64decode(s.llm_relay_ca_pem_b64).decode())
    return True


def _attempt(route: Route, messages: list[dict], *, temperature: float, max_tokens: int, want_json: bool,
             client: httpx.Client | None, validate: Callable[[object], bool] | None,
             response_format: dict | None = None) -> LLMResult:
    s = get_settings()
    url, headers, extra = _endpoint(route.provider, s)
    body = {"model": route.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
            **extra}
    if route.reasoning:
        body["reasoning"] = {"effort": route.reasoning}
    if response_format and route.provider == "openrouter":
        body["response_format"] = response_format  # жёсткая JSON-схема ответа (structured output, И27)
    name = short_model(route.model)
    t0 = time.monotonic()
    try:
        c = client or httpx.Client(timeout=httpx.Timeout(route.timeout_s, connect=min(5.0, route.timeout_s)),
                                   transport=_TRANSPORT, verify=_verify(route.provider, s))
        try:
            r = c.post(url, headers=headers, json=body)
        finally:
            if client is None:
                c.close()
        latency = int((time.monotonic() - t0) * 1000)
        res = LLMResult(ok=False, provider=route.provider, model=name, latency_ms=latency)
        if r.status_code != 200:
            # Тело ответа может содержать отладочную информацию провайдера, но не наш ключ.
            log.warning("LLM %s/%s: HTTP %s за %d мс: %s", route.provider, name, r.status_code, latency, r.text[:300])
            res.error = f"http_{r.status_code}"
            return res
        payload = r.json()
        if not isinstance(payload, dict) or payload.get("error"):
            res.error = "provider_error"
            return res
        msg = (payload.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or msg.get("reasoning_content") or ""
        res.text, res.usage = text, payload.get("usage")
        res.model_reported = short_model(str(payload.get("model") or "")) or None  # без каталога Yandex Cloud
        if not text.strip():
            res.error = "empty"
            return res
        res.ok = True
        if want_json:
            res.data = _extract_json(text)
            # Если JSON был только в рассуждениях — пробуем и их
            if res.data is None and msg.get("reasoning_content") and msg.get("content"):
                res.data = _extract_json(msg["reasoning_content"])
            if res.data is None:
                res.ok, res.error = False, "invalid_json"
        if res.ok and validate is not None:
            try:
                good = bool(validate(res.data if want_json else res.text))
            except Exception:  # noqa: BLE001 — проверка вызывающего не должна ронять цепочку
                good = False
            if not good:
                res.ok, res.error = False, "invalid_reply"
        log.info("LLM %s/%s: ответ за %d мс, ok=%s", route.provider, name, latency, res.ok)
        return res
    except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError, TypeError) as e:
        latency = int((time.monotonic() - t0) * 1000)
        err = "timeout" if isinstance(e, httpx.TimeoutException) else type(e).__name__
        log.warning("LLM %s/%s: ошибка запроса за %d мс: %s", route.provider, name, latency, err)
        return LLMResult(ok=False, error=err, provider=route.provider, model=name, latency_ms=latency)


# ------------------------------------------------------------------ публичный интерфейс
def chat(messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 1200, want_json: bool = False,
         client: httpx.Client | None = None, model: str | None = None, timeout_s: float | None = None,
         func: str | None = None, provider: str | None = None,
         validate: Callable[[object], bool] | None = None, deadline: float | None = None,
         response_format: dict | None = None) -> LLMResult:
    """Запрос по цепочке провайдеров функции func. Никогда не бросает исключений: при ошибке всех провайдеров
    ok=False и вызывающий идёт по правилам.

    model — явная модель (сравнение моделей на проверочных наборах): одна попытка без перехода по цепочке.
    validate — проверка разобранного ответа (JSON или текст); False — переход к следующему провайдеру.
    latency_ms результата — суммарное время всех попыток (столько ждал пользователь).
    deadline — момент time.monotonic(), к которому нужен ответ (общий бюджет вызывающего): тайм-аут попытки
    урезается до остатка, при остатке меньше секунды следующие провайдеры не вызываются (ошибка deadline).
    response_format — JSON-схема ответа ({"type": "json_schema", ...}) для OpenRouter (structured output); провайдер
    её не принял (HTTP 400) — одна повторная попытка того же маршрута без схемы, ответ проверяется как обычно."""
    rs = routes(func, model, provider, timeout_s)
    if not rs:
        return LLMResult(ok=False, error="not_configured", func=func)
    attempts: list[dict] = []
    total = 0
    last: LLMResult | None = None
    for r in rs:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left < 1.0:
                attempts.append({"provider": r.provider, "model": short_model(r.model), "ok": False,
                                 "error": "deadline", "latency_ms": 0})
                last = LLMResult(ok=False, error="deadline")
                break
            if left < r.timeout_s:
                r = replace(r, timeout_s=round(left, 1))
        if not breaker.allow(r.key):
            attempts.append({"provider": r.provider, "model": short_model(r.model), "ok": False,
                             "error": "circuit_open", "latency_ms": 0})
            continue
        res = _attempt(r, messages, temperature=temperature, max_tokens=max_tokens, want_json=want_json,
                       client=client, validate=validate, response_format=response_format)
        if response_format and r.provider == "openrouter" and res.error == "http_400":
            attempts.append({"provider": r.provider, "model": res.model, "ok": False, "error": "schema_rejected",
                             "latency_ms": res.latency_ms})
            total += res.latency_ms
            res = _attempt(r, messages, temperature=temperature, max_tokens=max_tokens, want_json=want_json,
                           client=client, validate=validate)
        total += res.latency_ms
        attempts.append({"provider": r.provider, "model": res.model, "ok": res.ok, "error": res.error,
                         "latency_ms": res.latency_ms})
        if res.ok:
            breaker.success(r.key)
            res.func, res.attempts, res.latency_ms = func, attempts, total
            if func:
                with _last_lock:
                    _last[func] = {"provider": res.provider, "model": res.model, "model_label": res.label,
                                   "at": time.time(), "latency_ms": total, "fallback": len(attempts) > 1}
            return res
        breaker.failure(r.key, res.error)
        last = res
    out = LLMResult(ok=False, error=(last.error if last else "circuit_open"), func=func, attempts=attempts,
                    latency_ms=total)
    if func:
        with _last_lock:
            _last[func] = {"provider": None, "model": None, "model_label": None, "at": time.time(),
                           "latency_ms": total, "fallback": True, "error": out.error}
    return out


def chat_json(system: str, user: str, **kw) -> LLMResult:
    return chat([{"role": "system", "content": system}, {"role": "user", "content": user}], want_json=True, **kw)


def available(func: str | None = None) -> bool:
    return bool(routes(func))


def status() -> dict:
    """Статус для /api/meta: цепочка, модель и тайм-аут по функции, состояние автомата, кто ответил последним.
    Ключей, адресов ретранслятора и каталога Yandex Cloud здесь нет."""
    s = get_settings()
    configured = s.llm_configured
    chain = [{"provider": p, "configured": s.llm_provider_configured(p) and not s.llm_disabled,
              "relay": bool(p == "openrouter" and s.llm_relay_url)} for p in s.llm_chain_list]
    funcs = {}
    for f in FUNCTIONS:
        rs = routes(f)
        funcs[f] = {"models": [{"provider": r.provider, "model": short_model(r.model),
                                "label": model_label(r.model)} for r in rs],
                    "timeout_s": timeout_for(f, s)}
    first = funcs["parse_need"]["models"][0] if configured and funcs["parse_need"]["models"] else None
    with _last_lock:
        last = {k: dict(v) for k, v in _last.items()}
    return {
        "configured": configured,
        # Прежние поля: первый провайдер цепочки и его модель (без каталога: gpt://<folder>/yandexgpt/latest →
        # yandexgpt/latest)
        "provider": (s.llm_provider if first["provider"] == "yandex" else first["provider"]) if first else None,
        "model": first["model"] if first else None,
        "chain": chain,
        "functions": funcs,
        "breaker": {k: v for k, v in breaker.snapshot().items() if v["fails"] or v["open"]},
        "last": last,
    }
