"""Примеры запросов и ответов для OpenAPI: снимаются с настоящих ответов приложения на демо-данных (Я3).

Обычный прогон pytest только проверяет файл `app/core/api_examples.json` (без секретов, компактный, без ошибок).
Пересъёмка — `make openapi-examples` (то же с OPENAPI_CAPTURE=1): тот же мир и те же запросы, что в матрице прав
(`tests/test_access_matrix.py`), каждым маршрутом и каждой ролью; в файл попадает самый содержательный успешный ответ
маршрута, сокращённый (списки — до двух элементов, длинные строки обрезаны) и очищенный от токенов и почт.
После пересъёмки выполните `make openapi`: примеры входят в docs/api/openapi.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

import pytest

from tests.route_walk import iter_routes
from tests.security_policy import LAST, POLICY, SKIP
from tests.test_access_matrix import (FILES, ROLE_ORDER, body_for, build_world, expectation, fill, no_ats_network,  # noqa: F401
                                      params_for)
from tests.test_day2_rules import H

EXAMPLES = Path(__file__).resolve().parents[1] / "app" / "core" / "api_examples.json"
CAPTURE = os.environ.get("OPENAPI_CAPTURE") == "1"
MAX_BYTES = 6000  # на один пример; больше — сокращаем глубже

_SECRET_KEY = re.compile(r"token|secret|password|passwd|hash|signature|cookie|authorization|jwt|otp|verification_code|api_key|private",
                         re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_JWT = re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}")
_REPLACE = ((re.compile(r"\s*\((?:матрица прав|матрицы прав)\)"), ""), (re.compile(r"Кубок матрицы прав"), "Кубок: Backend middle"),
            (re.compile(r"Матрица [12]"), "Компания «Пример»"), (re.compile(r"[Мм]атриц\w* прав\w*"), "проверка прав"))


_DROP = object()


def scrub(value, key: str = "", *, strings: int = 120, items: int = 2, depth: int = 6, keys: tuple = (40, 14, 9, 7, 5, 4)):
    """Очистка и сокращение примера: секреты → заглушка, почты → example.com; списки, строки, число полей и глубина —
    короче (на глубине больше предела вложенный объект выбрасывается целиком, пустых «{}» не остаётся)."""
    if _SECRET_KEY.search(key) and isinstance(value, str) and value:
        return "<скрыто>"
    if isinstance(value, (dict, list)) and depth <= 0:
        return _DROP
    if isinstance(value, dict):
        limit = keys[min(len(keys) - 1, 6 - depth)]
        out = {}
        for k, v in list(value.items())[:limit]:
            sv = scrub(v, k, strings=strings, items=items, depth=depth - 1, keys=keys)
            if sv is not _DROP:
                out[k] = sv
        return out
    if isinstance(value, list):
        out = [x for x in (scrub(v, key, strings=strings, items=items, depth=depth - 1, keys=keys) for v in value[:items])
               if x is not _DROP]
        return out
    if isinstance(value, str):
        v = _JWT.sub("<JWT>", value)
        v = re.sub(r"\+[a-z0-9]{10}@", "@", _EMAIL.sub(lambda m: m.group(0) if m.group(0).endswith(("example.com", "example.org")) else "user@example.com", v))
        for rx, sub in _REPLACE:
            v = rx.sub(sub, v)
        return v if len(v) <= strings else v[: strings - 1].rstrip() + "…"
    return value


def shrink(value):
    for strings, items, depth, keys in ((110, 2, 6, (40, 14, 10, 8, 6, 5)), (90, 2, 5, (40, 12, 8, 6, 5, 4)),
                                         (70, 1, 5, (30, 10, 7, 5, 4, 3)), (50, 1, 4, (24, 8, 6, 4, 3, 3)),
                                         (40, 1, 3, (16, 6, 4, 3, 3, 3))):
        out = scrub(value, strings=strings, items=items, depth=depth, keys=keys)
        if len(json.dumps(out, ensure_ascii=False)) <= MAX_BYTES:
            return out
    return out


def _richness(body) -> int:
    return len(json.dumps(body, ensure_ascii=False)) if isinstance(body, (dict, list)) else 0


@pytest.mark.skipif(not CAPTURE, reason="пересъёмка примеров: make openapi-examples (OPENAPI_CAPTURE=1)")
def test_capture_examples(client, no_ats_network):  # noqa: F811
    routes = iter_routes(client.app)
    world = build_world(client)
    tokens = world["tokens"]
    last = {k: i for i, k in enumerate(LAST)}
    ordered = sorted(routes, key=lambda r: (r.key in last, last.get(r.key, 0), r.path, r.method))
    found: dict[str, dict] = {}
    for route in ordered:
        want_by_role = expectation(POLICY[route.key])
        for role in ROLE_ORDER:
            if want_by_role[role] in (SKIP, 401, 403, 404, "hidden") or route.path.startswith(("/api/static", "/api/openapi")):
                continue
            side = world["sandbox"] if role.startswith("jury_") else world["real"]
            url = fill(route.path, params_for(route.key, side))
            kw: dict = {"headers": H(tokens[role]) if tokens[role] else {}}
            body = None
            if route.key in FILES:
                kw["files"] = FILES[route.key]()
            else:
                body = body_for(route.key, side)
                if body is not None:
                    kw["json"] = body
            resp = client.request(route.method, url, follow_redirects=False, **kw)
            if route.key == ("POST", "/api/jury/reset") and resp.status_code == 200 and "access_token" in resp.json():
                tokens[role] = resp.json()["access_token"]
            if not 200 <= resp.status_code < 300 or "application/json" not in resp.headers.get("content-type", ""):
                continue
            try:
                payload = resp.json()
            except ValueError:  # 204 и пустое тело
                continue
            key = f"{route.method} {route.path}"
            if key not in found or _richness(payload) > _richness(found[key]["response"]):
                found[key] = {"status": resp.status_code, "response": payload,
                              **({"request": body} if isinstance(body, dict) and body else {})}
    if os.environ.get("OPENAPI_RAW_DUMP"):  # сырые ответы — для подбора правил сокращения без новой съёмки
        Path(os.environ["OPENAPI_RAW_DUMP"]).write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    out = {}
    for key, rec in sorted(found.items()):
        item = {"status": rec["status"], "response": shrink(rec["response"])}
        if "request" in rec:
            item["request"] = shrink(rec["request"])
        out[key] = item
    EXAMPLES.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nпримеров: {len(out)} из {len(routes)} маршрутов → {EXAMPLES}")
    assert len(out) > 150


def test_examples_file_is_clean():
    """Файл примеров: валиден, без секретов и сторонних почт, каждый пример компактен."""
    if not EXAMPLES.exists():
        pytest.skip("нет app/core/api_examples.json — выполните make openapi-examples")
    data = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    assert data, "пустой файл примеров"
    text = EXAMPLES.read_text(encoding="utf-8")
    assert not _JWT.search(text), "в примерах остался JWT"
    foreign = {m for m in _EMAIL.findall(text) if not m.endswith(("example.com", "example.org"))}
    assert not foreign, f"сторонние почты в примерах: {sorted(foreign)[:5]}"
    for key, rec in data.items():
        assert len(json.dumps(rec, ensure_ascii=False)) <= 2 * MAX_BYTES + 200, f"{key}: пример слишком длинный"
        assert 200 <= rec["status"] < 300, key
    # поля с секретами не должны нести значения
    def walk(node, k=""):
        if isinstance(node, dict):
            for kk, vv in node.items():
                walk(vv, kk)
        elif isinstance(node, list):
            for vv in node:
                walk(vv, k)
        elif isinstance(node, str) and _SECRET_KEY.search(k) and node:
            assert node in ("<скрыто>", "<JWT>", "bearer") or len(node) <= 8, f"секретное поле {k!r} со значением {node[:12]!r}…"
    walk(data)
