"""Спецификация OpenAPI в репозитории: файл docs/api/openapi.json = app.openapi(); схема цельная и полная (Я3).

ТЗ, 3.5: «все методы описаны через спецификацию OpenAPI (Swagger), эндпоинты документированы — запросы, ответы,
коды ошибок». Проверяющий по репозиторию видит файл без запуска сервера, поэтому он не должен отставать от кода.
Если тест упал на сравнении с файлом — выполните `make openapi` и закоммитьте docs/api/openapi.json.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def exporter():
    return _load("export_openapi")


@pytest.fixture(scope="module")
def spec(exporter) -> dict:
    return exporter.build_spec()


def test_openapi_file_is_current(exporter, spec):
    path = ROOT / "docs" / "api" / "openapi.json"
    assert path.exists(), "нет docs/api/openapi.json — выполните `make openapi`"
    text = path.read_text(encoding="utf-8")
    assert json.loads(text) == spec, exporter.HINT
    assert text == exporter.render(spec), "файл записан не каноническим способом: " + exporter.HINT


def test_served_spec_equals_file(client, spec):
    """/api/openapi.json (то, что видит Swagger UI) — та же схема, что в файле."""
    served = client.get("/api/openapi.json").json()
    served.get("info", {}).pop("version", None)
    expected = json.loads(json.dumps(spec))
    expected.get("info", {}).pop("version", None)
    assert served == expected


def _refs(node, acc: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                acc.add(v)
            else:
                _refs(v, acc)
    elif isinstance(node, list):
        for v in node:
            _refs(v, acc)


def test_all_refs_resolve(spec):
    refs: set[str] = set()
    _refs(spec, refs)
    missing = []
    for ref in sorted(refs):
        assert ref.startswith("#/"), ref
        node = spec
        for part in ref[2:].split("/"):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            missing.append(ref)
    assert not missing, missing


def test_operations_have_unique_ids_and_known_tags(spec):
    ids, tags = [], {t["name"]: t.get("description") for t in spec.get("tags", [])}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            ids.append(op["operationId"])
            assert op.get("summary", "").strip(), f"{method} {path}: нет summary"
            assert op.get("description", "").strip(), f"{method} {path}: нет описания"
            assert op.get("tags"), f"{method} {path}: нет тега"
            for t in op["tags"]:
                assert tags.get(t), f"{method} {path}: у тега {t!r} нет описания в openapi_tags (app/main.py)"
            assert len(set(op["tags"])) == len(op["tags"]), f"{method} {path}: повтор тега"
    assert len(ids) == len(set(ids)), "operationId повторяются"
    assert len(ids) >= 300


def test_error_responses_use_error_model(spec):
    """Любая описанная ошибка 4xx/5xx — в формате {"detail": {"code", "message"}} (кроме проверки полей и заглушек ATS)."""
    comps = spec["components"].get("responses", {})
    bad = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            for status, resp in op["responses"].items():
                if not status.isdigit() or int(status) < 400:
                    continue
                if "$ref" in resp:
                    resp = comps[resp["$ref"].rsplit("/", 1)[-1]]
                schema = json.dumps(((resp.get("content") or {}).get("application/json") or {}).get("schema") or {})
                if "ErrorResponse" in schema or "HTTPValidationError" in schema:
                    continue
                if "ats-stub" in op["tags"]:
                    continue  # заглушки сторонних систем отвечают их форматом — это написано в описании ответа
                bad.append(f"{method} {path} {status}")
    assert not bad, bad[:20]


def test_audit_finds_no_gaps(spec):
    """tools/openapi_audit.py: у каждого метода summary, описание, тег; все ошибки из кода описаны с моделью ErrorResponse."""
    audit = _load("openapi_audit")
    from app.main import create_app

    rows = audit.audit(create_app())
    gaps = audit.gap_rows(rows)
    assert not gaps, "\n".join(f"{r['method']} {r['path']}: не описаны {r['missing_errors']}, без модели {r['errors_without_model']}"
                              for r in gaps[:30])
