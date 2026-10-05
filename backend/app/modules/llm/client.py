"""OpenAI-совместимый клиент чата (POST {base_url}/chat/completions).

Провайдер выбирается переменными окружения из /opt/spectrek_fsp/secrets/llm.env:
  LLM_PROVIDER   openai_compatible | yandex_ai_studio
  LLM_BASE_URL   например https://llm.api.cloud.yandex.net/v1
  LLM_API_KEY    ключ (в логи не пишется)
  LLM_FOLDER_ID  каталог Yandex Cloud (для yandex_ai_studio — заголовок OpenAI-Project)
  LLM_MODEL      например gpt://<folder>/yandexgpt/latest

Yandex AI Studio: «Authorization: Api-Key <ключ>» и «OpenAI-Project: <каталог>»; модели размещены в РФ.
Для моделей с рассуждениями (gpt-oss) текст ответа может прийти в reasoning_content — учитываем.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time

import httpx

from app.core.config import Settings, get_settings

log = logging.getLogger("llm")


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    data: dict | list | None = None
    error: str | None = None
    model: str | None = None
    latency_ms: int = 0


def _headers(s: Settings) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if s.llm_provider == "yandex_ai_studio":
        h["Authorization"] = f"Api-Key {s.llm_api_key}"
        if s.llm_folder_id:
            h["OpenAI-Project"] = s.llm_folder_id
    else:
        h["Authorization"] = f"Bearer {s.llm_api_key}"
    return h


def status() -> dict:
    s = get_settings()
    return {
        "configured": s.llm_configured,
        "provider": s.llm_provider if s.llm_configured else None,
        # Модель без каталога: gpt://<folder>/yandexgpt/latest → yandexgpt/latest
        "model": re.sub(r"^gpt://[^/]+/", "", s.llm_model or "") or None if s.llm_configured else None,
    }


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
                continue
    return None


def chat(messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 1200, want_json: bool = False,
         client: httpx.Client | None = None) -> LLMResult:
    """Один запрос к LLM. Никогда не бросает исключений: при ошибке ok=False и вызывающий идёт по правилам."""
    s = get_settings()
    if not s.llm_configured:
        return LLMResult(ok=False, error="not_configured")
    url = s.llm_base_url.rstrip("/") + "/chat/completions"
    body = {"model": s.llm_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    t0 = time.monotonic()
    try:
        c = client or httpx.Client(timeout=httpx.Timeout(s.llm_timeout_s, connect=5.0))
        try:
            r = c.post(url, headers=_headers(s), json=body)
        finally:
            if client is None:
                c.close()
        latency = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            # Тело ответа может содержать отладочную информацию провайдера, но не наш ключ.
            log.warning("LLM: HTTP %s за %d мс: %s", r.status_code, latency, r.text[:300])
            return LLMResult(ok=False, error=f"http_{r.status_code}", latency_ms=latency)
        payload = r.json()
        msg = (payload.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or msg.get("reasoning_content") or ""
        res = LLMResult(ok=bool(text), text=text, model=payload.get("model"), latency_ms=latency)
        if want_json:
            res.data = _extract_json(text)
            # Если JSON был только в рассуждениях — пробуем и их
            if res.data is None and msg.get("reasoning_content") and msg.get("content"):
                res.data = _extract_json(msg["reasoning_content"])
            if res.data is None:
                res.ok, res.error = False, "invalid_json"
        log.info("LLM: ответ за %d мс, модель %s, ok=%s", latency, res.model, res.ok)
        return res
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
        latency = int((time.monotonic() - t0) * 1000)
        log.warning("LLM: ошибка запроса за %d мс: %s", latency, type(e).__name__)
        return LLMResult(ok=False, error=type(e).__name__, latency_ms=latency)


def chat_json(system: str, user: str, **kw) -> LLMResult:
    return chat([{"role": "system", "content": system}, {"role": "user", "content": user}], want_json=True, **kw)
