"""HTTP к зарубежным API поставщиков через ретранслятор «Мадрид» (см. engine/DEPLOY.md и infra/relay/README):
клиент шлёт запрос на INTERVIEW_RELAY_URL (или общий LLM_RELAY_URL) с заголовком X-Relay-Host — куда переслать;
ретранслятор проверяет токен, IP и белый список хостов и пересылает тело и заголовки как есть. Сертификат
ретранслятора — закреплённый CA из LLM_RELAY_CA_FILE / LLM_RELAY_CA_PEM_B64. Без ретранслятора в настройках — прямой
вызов (локальная разработка)."""
from __future__ import annotations

import base64
import logging
import os
import tempfile
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

from ..settings import get_interview_settings

log = logging.getLogger("interview.engine.relay")
_ca_cache: dict[str, str] = {}


@dataclass
class Route:
    url: str
    headers: dict[str, str]
    verify: str | bool


def _ca_path() -> str | bool:
    s = get_settings()
    path = getattr(s, "llm_relay_ca_file", None)
    if path and os.path.exists(path):
        return path
    pem_b64 = getattr(s, "llm_relay_ca_pem_b64", None)
    if pem_b64:
        if "pem" not in _ca_cache:
            fd, tmp = tempfile.mkstemp(prefix="interview_relay_ca_", suffix=".pem")
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(pem_b64))
            _ca_cache["pem"] = tmp
        return _ca_cache["pem"]
    return True


def route(host: str, path: str, headers: dict[str, str] | None = None) -> Route:
    """Куда и с какими заголовками слать запрос к https://{host}{path}."""
    iv, s = get_interview_settings(), get_settings()
    relay = iv.interview_relay_url or getattr(s, "llm_relay_url", None)
    token = iv.interview_relay_token or getattr(s, "llm_relay_token", None)
    h = dict(headers or {})
    if not relay:
        return Route(url=f"https://{host}{path}", headers=h, verify=True)
    h["X-Relay-Host"] = host
    if token:
        h["X-Relay-Token"] = token
    return Route(url=relay_root(relay) + path, headers=h, verify=_ca_path())


def relay_root(url: str) -> str:
    """LLM_RELAY_URL задан как база OpenRouter (…/api/v1); адаптерам нужен корень ретранслятора."""
    root = url.rstrip("/")
    return root[: -len("/api/v1")] if root.endswith("/api/v1") else root


def request(method: str, host: str, path: str, *, headers: dict[str, str] | None = None, json: object | None = None,
            content: bytes | None = None, timeout_s: float = 30.0) -> httpx.Response:
    r = route(host, path, headers)
    with httpx.Client(timeout=timeout_s, verify=r.verify) as c:
        return c.request(method, r.url, headers=r.headers, json=json, content=content)


def via_relay() -> bool:
    iv, s = get_interview_settings(), get_settings()
    return bool(iv.interview_relay_url or getattr(s, "llm_relay_url", None))
