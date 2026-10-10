"""OpenAPI против живых ответов: каждая ошибка, которую метод реально вернул, описана в спецификации (Я3).

Не проверка «в коде есть api_error ⇒ описано» (это делает app.core.api_docs и она по построению сходится), а обратное:
реальные запросы всех ролей ко всем методам — с пустым телом, чужими и несуществующими идентификаторами, без токена —
и сверка фактического кода и `detail.code` с тем, что написано в схеме.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.core.enums import UserRole
from tests.conftest import register_and_verify

SKIP = {  # необратимые или внешние действия: уничтожают учётку/песочницу или ходят в сеть
    ("POST", "/api/me/data/delete"), ("POST", "/api/jury/reset"), ("DELETE", "/api/jury/sandbox"),
}


def _real_user(email: str, role: UserRole) -> str:
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.auth.service import issue_token

    with SessionLocal() as db:
        u = User(email=email, password_hash=hash_password("Runtime-pass-123"), role=role, is_email_verified=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        return issue_token(u).access_token


def _dummy(param: dict, spec: dict) -> str:
    schema = param.get("schema", {})
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    if schema.get("enum"):
        return str(schema["enum"][0])
    if schema.get("format") == "uuid":
        return str(uuid.uuid4())
    if schema.get("type") == "integer":
        return "1"
    return "x"


def _documented(spec: dict, op: dict, status: int) -> dict | None:
    resp = op["responses"].get(str(status))
    if resp is None:
        return None
    if "$ref" in resp:
        resp = spec["components"]["responses"][resp["$ref"].rsplit("/", 1)[-1]]
    return resp


def test_real_errors_are_documented(client):
    spec = client.get("/api/openapi.json").json()
    tokens = {
        "anon": None,
        "candidate": register_and_verify(client, "rt-cand@example.com"),
        "employer": register_and_verify(client, "rt-emp@example.com", role="employer"),
        "admin": _real_user("rt-admin@example.com", UserRole.admin),
        "expert": _real_user("rt-expert@example.com", UserRole.expert),
        "fsp": _real_user("rt-fsp@example.com", UserRole.fsp_analyst),
    }
    problems: list[str] = []
    calls = 0
    for path, ops in sorted(spec["paths"].items()):
        for method, op in sorted(ops.items()):
            if (method.upper(), path) in SKIP or not isinstance(op, dict):
                continue
            params = {p["name"]: _dummy(p, spec) for p in op.get("parameters", []) if p["in"] == "path"}
            url = path.format(**params)
            query = {p["name"]: _dummy(p, spec) for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")}
            body = (op.get("requestBody") or {}).get("content", {})
            kw: dict = {"params": query}
            if "application/json" in body:
                kw["json"] = {}
            elif "application/x-www-form-urlencoded" in body:
                kw["data"] = {"username": "nobody@example.com", "password": "wrong-password"}
            for role, token in tokens.items():
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                r = client.request(method.upper(), url, headers=headers, follow_redirects=False, **kw)
                calls += 1
                if r.status_code < 400 or r.status_code >= 500 and r.status_code not in (502, 503):  # 3xx — переходы, не ошибки
                    if r.status_code >= 500:
                        problems.append(f"{method.upper()} {path} [{role}] → {r.status_code} (ошибка сервера)")
                    continue
                resp = _documented(spec, op, r.status_code)
                if resp is None:
                    problems.append(f"{method.upper()} {path} [{role}] → {r.status_code}: код не описан")
                    continue
                try:
                    detail = r.json().get("detail")
                except ValueError:
                    continue
                if isinstance(detail, dict) and detail.get("code"):
                    text = json.dumps(resp, ensure_ascii=False)
                    if f"`{detail['code']}`" not in text and f'"{detail["code"]}"' not in text:
                        problems.append(f"{method.upper()} {path} [{role}] → {r.status_code} {detail['code']}: кода нет в описании")
    assert calls > 1500
    assert not problems, f"{len(problems)} расхождений ответов с OpenAPI:\n" + "\n".join(problems[:80])
