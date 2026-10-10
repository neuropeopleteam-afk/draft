"""Модели ответов для документации OpenAPI (app/core/api_models.py) не врут: типы полей совпадают с реальными ответами (Я3).

Модели только описывают ответы (в декораторах нет `response_model`), поэтому их соответствие кодом не обеспечено —
его держат эти тесты: примеры (app/core/api_examples.json, снятые с реальных ответов) проверяются моделями, лишние
и устаревшие строки таблицы находятся сразу, а доля описанных ответов не падает (ратчет).
"""
from __future__ import annotations

import json

from pydantic import TypeAdapter, ValidationError
import pytest

from app.core import api_docs
from app.core.api_docs_text import DESCRIPTIONS, FILE_RESPONSES
from app.core.api_models import MODULES, all_types
from tests.test_openapi_file import _load

RESPONSE_TYPES = all_types()


@pytest.fixture(scope="module")
def spec() -> dict:
    return _load("export_openapi").build_spec()


# Ратчет: можно повышать, понижать — только осознанно. Фактически сейчас: моделей ответов — 81, примеров — 192.
MIN_TYPED_RESPONSES = 78
MIN_WITH_EXAMPLE = 185


def test_every_model_row_matches_an_operation(spec):
    ops = {f"{m.upper()} {p}" for p, item in spec["paths"].items() for m in item if m in ("get", "post", "put", "patch", "delete")}
    stale = sorted(set(RESPONSE_TYPES) - ops)
    assert not stale, f"в RESPONSE_TYPES нет таких операций (маршрут переименован?): {stale}"


def test_model_names_do_not_clash_with_app_schemas():
    from fastapi import FastAPI

    from app.main import create_app

    raw = set(FastAPI.openapi(create_app())["components"]["schemas"])
    own = {tp.__name__ if isinstance(tp, type) else tp.__args__[-1].__name__ for tp in RESPONSE_TYPES.values()}
    assert not (raw & own), f"имена моделей совпали со схемами приложения: {sorted(raw & own)}"


def test_all_documentation_models_have_unique_names_and_are_used():
    """Имена всех моделей из api_models*.py различны (иначе в components.schemas одна затрёт другую); неиспользуемых нет."""
    import importlib
    import inspect

    from pydantic import BaseModel

    from app.core.api_models_base import Doc

    seen: dict[str, str] = {}
    for modname in ("api_models", *MODULES):
        mod = importlib.import_module(f"app.core.{modname}")
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == mod.__name__ and obj is not Doc:
                assert name not in seen, f"модель {name} определена и в {seen[name]}, и в {modname}"
                seen[name] = modname
    used = set()

    def walk(tp):
        import typing

        for a in typing.get_args(tp):
            walk(a)
        if inspect.isclass(tp) and issubclass(tp, BaseModel):
            if tp.__name__ in used:
                return
            used.update(b.__name__ for b in tp.__mro__ if issubclass(b, BaseModel))  # базовые классы — часть модели
            for f in tp.model_fields.values():
                walk(f.annotation)

    for tp in RESPONSE_TYPES.values():
        walk(tp)
    assert not (set(seen) - used), f"модели без операции: {sorted(set(seen) - used)}"


def test_models_are_attached_in_the_schema(spec):
    for key, tp in RESPONSE_TYPES.items():
        method, path = key.split(" ", 1)
        op = spec["paths"][path][method.lower()]
        ok = next(c for c in op["responses"] if c.startswith("2"))
        schema = op["responses"][ok]["content"]["application/json"]["schema"]
        name = (tp if isinstance(tp, type) else tp.__args__[-1]).__name__
        assert name in json.dumps(schema), f"{key}: в успешном ответе нет модели {name}"
        assert name in spec["components"]["schemas"], name


def test_models_agree_with_captured_examples():
    """Типы полей в моделях = типы в реальных ответах. Пропуски полей допустимы: примеры сокращены (api_docs/сниматель)."""
    examples = api_docs.load_examples()
    checked, bad = 0, []
    for key, tp in RESPONSE_TYPES.items():
        rec = examples.get(key)
        if not rec:
            continue
        checked += 1
        try:
            TypeAdapter(tp).validate_python(rec["response"])
        except ValidationError as e:
            wrong = [x for x in e.errors() if x["type"] != "missing"]
            if wrong:
                bad.append(f"{key}: " + "; ".join(f"{'.'.join(map(str, x['loc']))} — {x['type']}" for x in wrong[:4]))
    assert checked >= 40, f"слишком мало примеров для проверки моделей: {checked}"
    assert not bad, "модель расходится с реальным ответом:\n" + "\n".join(bad)


def test_documentation_ratchet(spec):
    audit = _load("openapi_audit")
    from app.main import create_app

    s = audit.summarize(audit.audit(create_app()))
    typed = s["response_kinds"].get("typed", 0)
    assert typed >= MIN_TYPED_RESPONSES, f"описанных моделью ответов стало меньше: {typed} < {MIN_TYPED_RESPONSES}"
    assert s["with_example"] >= MIN_WITH_EXAMPLE, f"примеров стало меньше: {s['with_example']} < {MIN_WITH_EXAMPLE}"
    assert s["with_summary"] == s["operations"] == s["with_tag"]


def test_authored_descriptions_match_operations_and_reach_the_schema(spec):
    ops = {f"{m.upper()} {p}": op for p, item in spec["paths"].items() for m, op in item.items() if m in ("get", "post", "put", "patch", "delete")}
    stale = sorted(set(DESCRIPTIONS) - set(ops))
    assert not stale, f"в api_docs_text.DESCRIPTIONS нет таких операций: {stale}"
    for key, text in DESCRIPTIONS.items():
        assert text.strip() and len(text) >= 40 or key == "GET /api/health", key
        # текст попал в схему, если у обработчика нет своего описания (иначе остаётся авторский docstring)
        assert ops[key].get("description"), key


def test_file_responses_are_documented_with_their_media_type(spec):
    for key, (media, _schema, _text) in FILE_RESPONSES.items():
        method, path = key.split(" ", 1)
        op = spec["paths"][path][method.lower()]
        ok = next(c for c in op["responses"] if c.startswith("2"))
        assert list(op["responses"][ok]["content"]) == [media], key
