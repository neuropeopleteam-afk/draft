#!/usr/bin/env python
"""Аудит полноты OpenAPI: что описано у каждого метода и каких задокументированных ошибок не хватает.

Для каждой пары «метод × путь» проверяется:
  * summary и описание заданы явно (а не взяты из имени функции FastAPI);
  * тег из списка openapi_tags (группа в Swagger UI);
  * модель ответа: typed (модель с полями), generic (`-> dict`, объект без полей), none (схемы нет), file, empty;
  * коды ошибок «по факту кода»: статический разбор (AST) тела обработчика, его зависимостей (get_current_user,
    require_role, лимиты частоты) и вызываемых из них функций пакета `app` (до 6 уровней вложенности) — общий
    с обогащением схемы код `app.core.api_docs.error_facts`; сравнивается с кодами 4xx/5xx в `responses` операции
    и с моделью ErrorResponse у них;
  * примеры (example/examples) в операции или в схемах, на которые она ссылается.

Разбор статический: вызовы методов объектов (`service.method()`), фабрики и коды, вычисленные в рантайме, он не видит —
поэтому «по факту кода» означает «то, что находится в коде явными вызовами `api_error(<код>, …)`, `HTTPException(<код>, …)`,
`hit(<лимит>, …)` и числовыми литералами 400–599 в `raise …(…)`». Это нижняя оценка, не доказательство.

`--raw` — схема FastAPI до обогащения (что описано вручную в роутерах); без флага — как её отдаёт /api/openapi.json.

Запуск (из корня репозитория):
  python tools/openapi_audit.py                 # сводка и таблица пробелов в stdout
  python tools/openapi_audit.py --md out.md     # то же в Markdown-файл
  python tools/openapi_audit.py --json out.json # полные данные по каждой операции
  python tools/openapi_audit.py --check         # код возврата 1, если есть пробелы (для CI и тестов)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/openapi_audit.db")  # приложению нужен адрес БД, соединение не открывается



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


# ---------------------------------------------------------------- коды «по факту кода»: общий разбор приложения

def code_facts(ctx) -> dict[int, dict[str, str]]:
    from app.core.api_docs import error_facts

    return error_facts(ctx)


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


def _is_error_model(resp: dict, spec: dict | None = None) -> bool:
    if "$ref" in resp and spec is not None:  # components.responses (общие 401/403)
        resp = spec.get("components", {}).get("responses", {}).get(resp["$ref"].rsplit("/", 1)[-1], {})
    s = _json_schema(resp) or {}
    return "ErrorResponse" in json.dumps(s)


def _table_descriptions() -> dict:
    from app.core.api_docs_text import DESCRIPTIONS

    return DESCRIPTIONS


def audit(app=None, spec: dict | None = None, raw: bool = False) -> list[dict]:
    """raw=True — схема FastAPI до обогащения app.core.api_docs (что описано вручную в роутерах)."""
    if app is None:
        from app.main import create_app

        app = create_app()
    if spec is None:
        spec = FastAPI.openapi(app) if raw else app.openapi()
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
            # заглушки ATS отвечают в формате имитируемых систем (это сказано в описании ответа) — модель платформы не требуется
            no_model = [] if "ats-stub" in (ctx.tags or []) else sorted(
                c for c in documented if c != 422 and not _is_error_model(responses[str(c)], spec))
            rows.append({
                "method": method, "path": ctx.path, "endpoint": f"{ctx.endpoint.__module__}.{ctx.endpoint.__name__}",
                "tags": list(ctx.tags or []),
                "has_summary": bool(ctx.summary), "has_description": bool((op.get("description") or "").strip()),
                "has_authored_description": bool((ctx.description or "").strip()) or (not raw and f"{method} {ctx.path}" in _table_descriptions()),
                "has_access": "**Доступ:**" in (op.get("description") or ""),
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
        "with_authored_description": f("has_authored_description"), "with_access": f("has_access"),
        "with_response_model": f("has_response_model"),
        "response_kinds": dict(sorted(Counter(r["response_kind"] for r in rows).items())),
        "with_all_actual_errors_documented": sum(1 for r in rows if not r["missing_errors"]),
        "missing_error_pairs": sum(len(r["missing_errors"]) for r in rows),
        "errors_without_model_pairs": sum(len(r["errors_without_model"]) for r in rows),
        "with_example": f("has_example"),
        "missing_by_code": dict(sorted(Counter(c for r in rows for c in r["missing_errors"]).items())),
    }


def gap_rows(rows: list[dict], strict: bool = False) -> list[dict]:
    """Операции с пробелами: нет summary/описания/тега, не описаны найденные в коде ошибки или у ошибок нет модели.
    strict — ещё и без описанного ответа (модель с полями, файл, пустой)."""
    return [r for r in rows if not (r["has_summary"] and r["has_description"] and r["has_tag"])
            or (strict and not r["has_response_model"]) or r["missing_errors"] or r["errors_without_model"]]


def to_markdown(rows: list[dict]) -> str:
    s = summarize(rows)
    lines = ["| Показатель | Операций | Доля |", "|---|---:|---:|"]
    for key, label in (("with_summary", "явный summary"), ("with_authored_description", "авторское описание (docstring, description у метода или таблица api_docs_text.py)"),
                       ("with_description", "описание в схеме (авторское и/или строка «Доступ»)"),
                       ("with_access", "строка «Доступ» (вход, роль)"),
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
    gaps = gap_rows(rows, strict=True)
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
    ap.add_argument("--raw", action="store_true", help="схема FastAPI до обогащения api_docs (описано вручную в роутерах)")
    ap.add_argument("--check", action="store_true", help="код возврата 1, если остались пробелы")
    ap.add_argument("--strict", action="store_true", help="с --check: считать пробелом и ответ без модели с полями")
    a = ap.parse_args()
    rows = audit(raw=a.raw)
    s = summarize(rows)
    md = to_markdown(rows)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.md and not a.json:
        print(md)
    return 1 if a.check and gap_rows(rows, a.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
