#!/usr/bin/env python
"""Аудит полноты OpenAPI: что описано у каждого метода и каких задокументированных ошибок не хватает.

Для каждой пары «метод × путь» проверяется:
  * summary и описание заданы явно (а не взяты из имени функции FastAPI);
  * тег из списка openapi_tags (группа в Swagger UI);
  * модель ответа: в схеме успешного JSON-ответа не пустой `{}` (иначе dict без response_model);
  * коды ошибок «по факту кода»: статический разбор (AST) тела обработчика, его зависимостей (get_current_user,
    require_role, лимиты частоты) и вызываемых из них функций пакета `app` (до 6 уровней вложенности);
    сравнивается с кодами 4xx/5xx, которые есть в `responses` операции, и с моделью ErrorResponse у них.

Разбор статический: вызовы методов объектов (`service.method()`), фабрики и коды, вычисленные в рантайме, он не видит —
поэтому «по факту кода» означает «то, что находится в коде явными вызовами `api_error(<код>, …)`,
`HTTPException(<код>, …)` и числовыми литералами 400–599 в аргументах вызовов». Это нижняя оценка, не доказательство.

Запуск (из корня репозитория):
  python tools/openapi_audit.py                 # сводка и таблица пробелов в stdout
  python tools/openapi_audit.py --md out.md     # то же в Markdown-файл
  python tools/openapi_audit.py --json out.json # полные данные по каждой операции
  python tools/openapi_audit.py --check         # код возврата 1, если есть пробелы (для CI и тестов)
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
import textwrap
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/openapi_audit.db")  # приложению нужен адрес БД, соединение не открывается

HTTP_METHODS = ("get", "put", "post", "delete", "patch")
ERROR_CODES = {400, 401, 403, 404, 409, 410, 413, 415, 422, 423, 429, 500, 502, 503, 504}
_STATUS_NAME = re.compile(r"HTTP_(\d{3})_")
_MAX_DEPTH = 6


# ---------------------------------------------------------------- обход маршрутов

def route_contexts(app) -> list[Any]:
    """Все «эффективные» маршруты приложения (FastAPI 0.142: app.routes хранит _IncludedRouter)."""
    out: list[Any] = []

    def walk(routes):
        for r in routes:
            if type(r).__name__ == "_IncludedRouter":
                out.extend(c for c in r.effective_route_contexts() if getattr(c, "include_in_schema", True))
            elif hasattr(r, "dependant") and getattr(r, "include_in_schema", True):
                out.append(r)
            elif hasattr(r, "routes"):
                walk(r.routes)

    walk(app.routes)
    return out


# ---------------------------------------------------------------- статический разбор кодов ошибок

def _const_status(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value if 400 <= node.value <= 599 else None
    if isinstance(node, ast.Attribute):
        m = _STATUS_NAME.search(node.attr)
        if m and 400 <= int(m.group(1)) <= 599:
            return int(m.group(1))
    return None


def _resolve(node: ast.AST, fn: Any) -> Any:
    """Имя или цепочка a.b.c → объект из пространства имён функции (глобальные и замыкание)."""
    if isinstance(node, ast.Name):
        try:
            cv = inspect.getclosurevars(fn)
            for ns in (cv.nonlocals, cv.globals):
                if node.id in ns:
                    return ns[node.id]
        except (TypeError, ValueError):
            pass
        return getattr(fn, "__globals__", {}).get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, fn)
        return getattr(base, node.attr, None) if base is not None else None
    return None


def _own_function(obj: Any) -> Any:
    if inspect.isfunction(obj) or inspect.ismethod(obj):
        mod = getattr(obj, "__module__", "") or ""
        return obj if mod.startswith("app.") else None
    return None


_SRC_CACHE: dict[Any, tuple[ast.AST | None, set[int], list[Any]]] = {}


def _scan(fn: Any) -> tuple[set[int], list[Any]]:
    """Коды, найденные в теле функции напрямую, и функции пакета app, которые она вызывает."""
    if fn in _SRC_CACHE:
        _, codes, calls = _SRC_CACHE[fn]
        return codes, calls
    codes: set[int] = set()
    calls: list[Any] = []
    tree = None
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError, IndentationError):
        pass
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            args = list(node.args) + [k.value for k in node.keywords]
            if fname in ("api_error", "HTTPException", "JSONResponse") or fname.endswith("_error") or fname.endswith("_err"):
                for a in args[:2]:
                    c = _const_status(a)
                    if c:
                        codes.add(c)
            else:  # числовой литерал 4xx/5xx в аргументах любого вызова — код, переданный в общий помощник
                for a in args:
                    c = _const_status(a)
                    if c:
                        codes.add(c)
            target = _own_function(_resolve(node.func, fn))
            if target is not None:
                calls.append(target)
    _SRC_CACHE[fn] = (tree, codes, calls)
    return codes, calls


def codes_in_function(fn: Any, seen: set | None = None, depth: int = 0) -> set[int]:
    seen = set() if seen is None else seen
    if fn is None or fn in seen or depth > _MAX_DEPTH:
        return set()
    seen.add(fn)
    codes, calls = _scan(fn)
    out = set(codes)
    for c in calls:
        out |= codes_in_function(c, seen, depth + 1)
    return out


def dependency_calls(dependant, acc: list | None = None) -> list:
    acc = [] if acc is None else acc
    for d in getattr(dependant, "dependencies", []) or []:
        if d.call is not None:
            acc.append(d.call)
        dependency_calls(d, acc)
    return acc


def code_facts(ctx) -> dict[int, str]:
    """Код → откуда он взят: handler / dependency (для 401 и 403 — вход и роль)."""
    facts: dict[int, str] = {}
    seen: set = set()
    for c in sorted(codes_in_function(ctx.endpoint, seen)):
        facts[c] = "handler"
    for dep in dependency_calls(ctx.dependant):
        for c in sorted(codes_in_function(dep, seen)):
            facts.setdefault(c, "dependency")
    return facts


# ---------------------------------------------------------------- проверки схемы

def _json_schema(resp: dict) -> dict | None:
    content = (resp or {}).get("content") or {}
    js = content.get("application/json")
    return None if js is None else (js.get("schema") or {})


def schema_kind(schema: dict | None) -> str:
    """typed — ссылка на модель или объект с полями; generic — «объект без полей» (dict без модели); none — схемы нет."""
    if not schema:
        return "none"
    if "$ref" in schema or schema.get("properties"):
        return "typed"
    if schema.get("type") == "array":
        return {"typed": "typed", "generic": "generic"}.get(schema_kind(schema.get("items")), "generic")
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            kinds = {schema_kind(x) for x in schema[key] if x.get("type") != "null"}
            return "typed" if kinds == {"typed"} else "generic"
    return "generic" if schema.get("type") == "object" else "typed"  # скаляр (строка, число) — описан типом


def _is_error_model(resp: dict) -> bool:
    s = _json_schema(resp) or {}
    return "ErrorResponse" in json.dumps(s)


def audit(app=None, spec: dict | None = None) -> list[dict]:
    if app is None:
        from app.main import create_app

        app = create_app()
    spec = spec or app.openapi()
    tag_names = {t["name"] for t in spec.get("tags", [])}
    rows: list[dict] = []
    for ctx in route_contexts(app):
        for method in sorted(ctx.methods or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            op = (spec["paths"].get(ctx.path) or {}).get(method.lower())
            if op is None:
                continue
            responses = op.get("responses", {})
            ok = {k: v for k, v in responses.items() if k.startswith("2")}
            ok_resp = ok.get(str(ctx.status_code or 200)) or next(iter(ok.values()), {})
            content = ok_resp.get("content") or {}
            media = [m for m in content if m != "application/json"]
            if media and "application/json" in content and not content["application/json"].get("schema"):
                kind = "file"  # responses={200: {"content": {"image/png": …}}}: документированный не-JSON ответ
            elif "application/json" in content:
                kind = schema_kind(content["application/json"].get("schema"))
            elif content:
                kind = "file"
            else:
                kind = "empty" if str(ctx.status_code or 200) in ("204", "302", "303", "307") else "none"
            has_model = kind in ("typed", "file", "empty")
            documented = {int(k) for k in responses if k.isdigit() and int(k) >= 400}
            facts = code_facts(ctx)
            actual = set(facts)
            # 422 FastAPI добавляет сама, если есть параметры; прочие 422 — по коду
            missing = sorted(c for c in actual if c not in documented)
            no_model = sorted(c for c in documented if c != 422 and not _is_error_model(responses[str(c)]))
            rows.append({
                "method": method, "path": ctx.path, "endpoint": f"{ctx.endpoint.__module__}.{ctx.endpoint.__name__}",
                "tags": list(ctx.tags or []),
                "has_summary": bool(ctx.summary), "has_description": bool((ctx.description or "").strip()),
                "has_tag": bool(ctx.tags) and all(t in tag_names for t in ctx.tags),
                "has_response_model": has_model, "response_kind": kind,
                "documented_errors": sorted(documented), "actual_errors": sorted(actual),
                "missing_errors": missing, "errors_without_model": no_model,
                "has_example": _has_example(op, spec),
            })
    rows.sort(key=lambda r: (r["path"], r["method"]))
    return rows


def _refs(node: Any, acc: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                acc.add(v.rsplit("/", 1)[-1])
            else:
                _refs(v, acc)
    elif isinstance(node, list):
        for v in node:
            _refs(v, acc)


def _has_example(op: dict, spec: dict) -> bool:
    """Пример есть в самой операции (тело запроса, успешный ответ) или в схемах, на которые они ссылаются."""
    parts = [op.get("requestBody"), {k: v for k, v in op.get("responses", {}).items() if k.startswith("2")}]
    todo: set[str] = set()
    _refs(parts, todo)
    seen: set[str] = set()
    schemas = spec.get("components", {}).get("schemas", {})
    while todo:
        name = todo.pop()
        seen.add(name)
        _refs(schemas.get(name, {}), (more := set()))
        todo |= more - seen
    blobs = [json.dumps(parts, ensure_ascii=False)] + [json.dumps(schemas.get(n, {}), ensure_ascii=False) for n in seen]
    return any('"example"' in b or '"examples"' in b for b in blobs)


# ---------------------------------------------------------------- вывод

def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    f = lambda key: sum(1 for r in rows if r[key])  # noqa: E731
    return {
        "operations": n,
        "with_summary": f("has_summary"), "with_description": f("has_description"), "with_tag": f("has_tag"),
        "with_response_model": f("has_response_model"),
        "response_kinds": dict(sorted(Counter(r["response_kind"] for r in rows).items())),
        "with_all_actual_errors_documented": sum(1 for r in rows if not r["missing_errors"]),
        "missing_error_pairs": sum(len(r["missing_errors"]) for r in rows),
        "errors_without_model_pairs": sum(len(r["errors_without_model"]) for r in rows),
        "with_example": f("has_example"),
        "missing_by_code": dict(sorted(Counter(c for r in rows for c in r["missing_errors"]).items())),
    }


def gap_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not (r["has_summary"] and r["has_description"] and r["has_tag"] and r["has_response_model"])
            or r["missing_errors"] or r["errors_without_model"]]


def to_markdown(rows: list[dict]) -> str:
    s = summarize(rows)
    lines = ["| Показатель | Операций | Доля |", "|---|---:|---:|"]
    for key, label in (("with_summary", "явный summary"), ("with_description", "описание (docstring или description)"),
                       ("with_tag", "тег из openapi_tags"), ("with_response_model", "описан ответ: модель с полями, файл или пустой ответ"),
                       ("with_all_actual_errors_documented", "все найденные в коде ошибки описаны в responses"),
                       ("with_example", "есть пример (example/examples)")):
        lines.append(f"| {label} | {s[key]} из {s['operations']} | {100 * s[key] / s['operations']:.0f} % |".replace(".", ","))
    kinds = s["response_kinds"]
    lines += ["", "Успешный ответ: " + ", ".join(
        f"{label} — {kinds.get(k, 0)}" for k, label in (("typed", "модель с полями"), ("file", "файл/не JSON"),
                                                       ("empty", "пустой"), ("generic", "объект без полей (dict)"),
                                                       ("none", "схемы нет")))]
    lines += ["", f"Не описано пар «операция × код»: {s['missing_error_pairs']} "
                  f"(по кодам: {', '.join(f'{k}: {v}' for k, v in s['missing_by_code'].items()) or '—'}); "
                  f"описанных ошибок без модели `ErrorResponse`: {s['errors_without_model_pairs']}.", ""]
    gaps = gap_rows(rows)
    if gaps:
        lines += ["| Метод | Путь | Нет | Не описаны коды |", "|---|---|---|---|"]
        for r in gaps:
            lack = [name for name, ok in (("summary", r["has_summary"]), ("описания", r["has_description"]),
                                         ("тега", r["has_tag"]), ("модели ответа", r["has_response_model"])) if not ok]
            if r["errors_without_model"]:
                lack.append("модели ошибки " + "/".join(map(str, r["errors_without_model"])))
            lines.append(f"| {r['method']} | `{r['path']}` | {', '.join(lack) or '—'} | "
                         f"{', '.join(map(str, r['missing_errors'])) or '—'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--md", help="записать таблицу в Markdown-файл")
    ap.add_argument("--json", help="записать данные по каждой операции в JSON")
    ap.add_argument("--check", action="store_true", help="код возврата 1, если остались пробелы")
    a = ap.parse_args()
    rows = audit()
    s = summarize(rows)
    md = to_markdown(rows)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.md and not a.json:
        print(md)
    return 1 if a.check and gap_rows(rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
