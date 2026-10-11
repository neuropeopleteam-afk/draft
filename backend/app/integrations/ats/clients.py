"""Клиенты ATS: Хантфлоу (публичный API v2) и универсальный вебхук с подписью HMAC-SHA256.

Хантфлоу API v2 (https://api.huntflow.ru/v2/docs, OpenAPI /v2/openapi.json), авторизация ``Authorization: Bearer <token>``:
* ``GET  /me`` — владелец токена; ``GET /accounts`` — организации (account_id);
* ``GET  /accounts/{account_id}/vacancies/statuses`` — этапы подбора (id первого этапа, если работодатель его не задал);
* ``POST /accounts/{account_id}/applicants`` — создать кандидата: first_name, last_name, middle_name, email, phone,
  money, position, externals[{auth_type: "NATIVE", data: {body: текст резюме}}], social[{social_type: "TELEGRAM"}];
* ``POST /accounts/{account_id}/applicants/{applicant_id}/vacancy`` — закрепить на вакансии: vacancy, status, comment.

Вебхук: ``POST <url>``, тело — JSON (схема ``draft.candidate.v1``), заголовки
``X-Draft-Event``, ``X-Draft-Delivery``, ``X-Draft-Timestamp`` и
``X-Draft-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<unix>.<тело>")>``.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

import httpx

from app.integrations.settings import get_isettings

USER_AGENT = "Draft-ATS/1.0 (+https://fsp.neuropeople.pro/docs/ATS)"


def _send(method: str, url: str, **kw) -> httpx.Response:
    """Единая точка HTTP-вызовов к ATS (в тестах подменяется на TestClient)."""
    return httpx.request(method, url, **kw)


class AtsError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


STUB_PATH = "/api/ats-stub/"


def check_url(url: str) -> str:
    """Защита от SSRF: только https и публичные адреса (исключение — наша тестовая ATS-заглушка: её публичный адрес
    из настроек компании переписывается на внутренний stub_base — так api не зависит от доступности сайта изнутри)."""
    s = get_isettings()
    for base in (s.stub_base, s.stub_public_base):
        if url.startswith(base + STUB_PATH):
            return s.stub_base + url[len(base):]
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        raise AtsError("Адрес должен начинаться с https://")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise AtsError(f"Не удалось найти хост {p.hostname}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise AtsError("Адрес указывает во внутреннюю сеть — запрещено")
    return url


def sign(secret: str, body: bytes, ts: int | None = None) -> tuple[str, int]:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}", ts


def verify_signature(secret: str, body: bytes, header: str | None, tolerance_s: int = 300) -> bool:
    """Проверка подписи на стороне получателя (так же делает тестовая ATS-заглушка)."""
    if not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts.get("t", "0"))
    except ValueError:
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


class HuntflowClient:
    def __init__(self, base_url: str, token: str, timeout: float | None = None):
        self.base = check_url(base_url.rstrip("/"))
        self.token = token
        self.timeout = timeout or get_isettings().ats_timeout_s

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = _send(method, self.base + path, json=body, timeout=self.timeout,
                              headers={"Authorization": f"Bearer {self.token}", "User-Agent": USER_AGENT,
                                       "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise AtsError(f"Хантфлоу недоступен ({type(e).__name__})") from None
        if r.status_code == 401:
            raise AtsError("Хантфлоу: токен недействителен или истёк (401)", 401)
        if r.status_code >= 400:
            try:
                detail = json.dumps(r.json().get("errors") or r.json(), ensure_ascii=False)[:200]
            except ValueError:
                detail = r.text[:200]
            raise AtsError(f"Хантфлоу ответил {r.status_code}: {detail}", r.status_code)
        try:
            return r.json()
        except ValueError:
            return {}

    def me(self) -> dict:
        return self._req("GET", "/me")

    def accounts(self) -> list[dict]:
        return self._req("GET", "/accounts").get("items", [])

    def statuses(self, account_id: int) -> list[dict]:
        return self._req("GET", f"/accounts/{account_id}/vacancies/statuses").get("items", [])

    def create_applicant(self, account_id: int, payload: dict) -> dict:
        return self._req("POST", f"/accounts/{account_id}/applicants", payload)

    def add_to_vacancy(self, account_id: int, applicant_id: int, vacancy_id: int, status_id: int,
                       comment: str) -> dict:
        return self._req("POST", f"/accounts/{account_id}/applicants/{applicant_id}/vacancy",
                         {"vacancy": vacancy_id, "status": status_id, "comment": comment})


def post_webhook(url: str, secret: str, event: str, delivery_id: str, payload: dict) -> int:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    sig, ts = sign(secret, body)
    try:
        r = _send("POST", check_url(url), content=body, timeout=get_isettings().ats_timeout_s,
                       headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT,
                                "X-Draft-Event": event, "X-Draft-Delivery": delivery_id,
                                "X-Draft-Timestamp": str(ts), "X-Draft-Signature": sig})
    except httpx.HTTPError as e:
        raise AtsError(f"Вебхук недоступен ({type(e).__name__})") from None
    if r.status_code >= 300:
        raise AtsError(f"Вебхук ответил {r.status_code}", r.status_code)
    return r.status_code
