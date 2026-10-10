"""Полнота описания OpenAPI: типовые ошибки, «Доступ» и описания групп — в одном месте, без правки каждого роутера.

Что делает ``install_openapi(app)`` (вызывается из ``create_app``): оборачивает ``app.openapi()`` и к собранной
FastAPI схеме добавляет то, что можно вывести из самого кода обработчика:

* **Ошибки по факту кода.** Статический разбор (AST) обработчика, его зависимостей (``get_current_user``,
  ``require_role``) и вызываемых из них функций пакета ``app`` (до 6 уровней) находит вызовы ``api_error(<код>, "<code>",
  "<сообщение>")``, ``HTTPException``, ``hit(<лимит>, …)`` (429). Для каждого найденного HTTP-кода в ``responses``
  операции появляется описание с моделью ``ErrorResponse``, перечнем кодов ``detail.code`` и примером. Уже описанные
  вручную (``responses=``) ответы не затираются: к ним добавляются коды и пример.
* **«Доступ».** К описанию каждой операции — строка: нужен ли вход (JWT), какие роли пускает ``require_role``.
* Всё это — документация: поведение API не меняется. Разбор нижний по охвату: вызовы методов объектов
  (``service.method()`` на экземпляре) и коды, вычисленные в рантайме, он не видит — такие ответы описывают вручную
  через ``responses=errors(...)`` и ``err(...)``.

Файл спецификации в репозитории (``docs/api/openapi.json``) создаёт ``make openapi``; тест
``tests/test_openapi_file.py`` проверяет, что он совпадает с ``app.openapi()``.
"""
from __future__ import annotations

import ast
import copy
import importlib
import inspect
import json
from pathlib import Path
import textwrap
import threading
from typing import Any

from fastapi import FastAPI

from app.core.errors import ErrorResponse, err

# ---------------------------------------------------------------- типовые ответы для роутеров

STATUS_TEXT: dict[int, str] = {
    400: "Некорректный запрос",
    401: "Нужен вход или токен недействителен",
    403: "Недостаточно прав",
    404: "Не найдено",
    405: "Метод не поддерживается",
    409: "Конфликт с текущим состоянием",
    410: "Объект или ссылка больше не доступны",
    413: "Слишком большой запрос или файл",
    415: "Неподдерживаемый тип данных",
    422: "Данные не прошли проверку",
    423: "Временно заблокировано",
    429: "Слишком много запросов",
    500: "Внутренняя ошибка сервера",
    502: "Внешняя система ответила ошибкой",
    503: "Функция или внешний сервис недоступны",
    504: "Внешняя система не ответила вовремя",
}

COMMON_ERRORS: dict[int, str] = {
    401: "Нужен вход: заголовок `Authorization: Bearer <JWT>` не передан или токен недействителен",
    403: "Недостаточно прав: роль пользователя не подходит для метода",
    404: "Объект не найден или принадлежит другому пользователю",
    409: "Действие недопустимо в текущем состоянии объекта",
    429: "Слишком много запросов; заголовок `Retry-After` — через сколько секунд повторить",
}


def errors(*statuses: int, **custom: str) -> dict[int, dict]:
    """Типовой набор ``responses=`` для роутера: ``responses=errors(401, 403, 404, **{"409": "Уже есть"})``.

    Коды без своего текста берут формулировку из COMMON_ERRORS / STATUS_TEXT; формат тела — ``ErrorResponse``.
    """
    out = {s: err(COMMON_ERRORS.get(s) or STATUS_TEXT.get(s, "Ошибка")) for s in statuses}
    out.update({int(k): err(v) for k, v in custom.items()})
    return out


# ---------------------------------------------------------------- разбор кода: какие ошибки возвращает метод

_MAX_DEPTH = 6
Facts = dict[int, dict[str, str]]  # HTTP-код → {detail.code: сообщение}; "" — код неизвестен (передан переменной)


class _Scan:
    """Результат разбора одной функции: ошибки в её теле, вызываемые функции app, шаблоны «код передан параметром»."""

    def __init__(self) -> None:
        self.facts: Facts = {}
        self.calls: list[tuple[Any, ast.Call]] = []
        self.params: list[str] = []
        self.templates: list[tuple[int, str | None, str | None]] = []  # (HTTP-код, параметр с detail.code, параметр с сообщением)


_SCAN_CACHE: dict[Any, _Scan] = {}
_ERR_HELPER = ("err", "error", "fail", "abort")  # _tx_err(401, …): помощник ответа с ошибкой, код — первым аргументом


def _text(node: ast.AST | None) -> str | None:
    """Строка из константы, склейки через + и f-строки (подстановки → «…»)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(p.value if isinstance(p, ast.Constant) else "…" for p in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _text(node.left), _text(node.right)
        return None if a is None or b is None else a + b
    return None


def _status(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value if 400 <= node.value <= 599 else None
    if isinstance(node, ast.Attribute) and node.attr.startswith("HTTP_"):  # status.HTTP_404_NOT_FOUND
        parts = node.attr.split("_")
        if len(parts) > 1 and parts[1].isdigit() and 400 <= int(parts[1]) <= 599:
            return int(parts[1])
    return None


def _arg(call: ast.Call, pos: int, *names: str) -> ast.AST | None:
    if len(call.args) > pos:
        return call.args[pos]
    for k in call.keywords:
        if k.arg in names:
            return k.value
    return None


def _local_imports(body: list[ast.stmt]) -> dict[str, Any]:
    """`from app.x import y` внутри тела функции (отложенные импорты) → {имя: объект}."""
    out: dict[str, Any] = {}
    for st in body:
        for n in ast.walk(st):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").startswith("app."):
                try:
                    mod = importlib.import_module(n.module)
                except Exception:  # noqa: BLE001 — разбор документации не должен ронять приложение
                    continue
                for a in n.names:
                    obj = getattr(mod, a.name, None)
                    if obj is None:
                        try:
                            obj = importlib.import_module(f"{n.module}.{a.name}")
                        except Exception:  # noqa: BLE001
                            continue
                    out[a.asname or a.name] = obj
    return out


def _resolve(node: ast.AST, fn: Any, local: dict[str, Any] | None = None) -> Any:
    """Имя или цепочка a.b.c → объект из локальных импортов, глобальных имён и замыкания функции."""
    if isinstance(node, ast.Name):
        if local and node.id in local:
            return local[node.id]
        try:
            cv = inspect.getclosurevars(fn)
            for ns in (cv.nonlocals, cv.globals):
                if node.id in ns:
                    return ns[node.id]
        except (TypeError, ValueError):
            pass
        return getattr(fn, "__globals__", {}).get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, fn, local)
        return getattr(base, node.attr, None) if base is not None else None
    return None


def _own(obj: Any) -> Any:
    if inspect.isfunction(obj) or inspect.ismethod(obj):
        return obj if (getattr(obj, "__module__", "") or "").startswith("app.") else None
    return None


def _add(facts: Facts, status: int, code: str | None = None, message: str | None = None) -> None:
    slot = facts.setdefault(status, {})
    slot.setdefault(code or "", message or "")


def _param(node: ast.AST | None, params: list[str]) -> str | None:
    return node.id if isinstance(node, ast.Name) and node.id in params else None


def _scan(fn: Any) -> _Scan:
    """Ошибки, поднятые в теле функции напрямую, и функции пакета app, которые она вызывает."""
    if fn in _SCAN_CACHE:
        return _SCAN_CACHE[fn]
    sc = _SCAN_CACHE[fn] = _Scan()  # до разбора: защита от рекурсии
    try:
        node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return sc
    except (OSError, TypeError, SyntaxError, IndexError):
        return sc
    sc.params = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
    local = _local_imports(node.body)
    raised = {id(n.exc) for st in node.body for n in ast.walk(st) if isinstance(n, ast.Raise) and n.exc is not None}
    for st in node.body:
        for n in ast.walk(st):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            if name == "api_error":
                s = _status(_arg(n, 0, "status_code"))
                if s:
                    code, msg = _arg(n, 1, "code"), _arg(n, 2, "message")
                    _add(sc.facts, s, _text(code), _text(msg))
                    if _param(code, sc.params):  # api_error(404, code, message) внутри помощника: код задаёт вызывающий
                        sc.templates.append((s, _param(code, sc.params), _param(msg, sc.params)))
            elif name == "HTTPException":
                s = _status(_arg(n, 0, "status_code"))
                detail = _arg(n, 1, "detail")
                if s and isinstance(detail, ast.Dict):
                    d = {_text(k): _text(v) for k, v in zip(detail.keys, detail.values)}
                    _add(sc.facts, s, d.get("code"), d.get("message"))
                elif s:
                    _add(sc.facts, s)
            elif name == "hit" and len(n.args) >= 4:  # app.core.ratelimit.hit(limiter, key, code, message) → 429
                _add(sc.facts, 429, _text(n.args[2]), (_text(n.args[3]) or "") + ". Повторите через …")
            else:
                lit = [k.value for k in n.keywords if k.arg in ("status_code", "status")]
                if id(n) in raised:  # raise _helper(409, …)
                    lit += n.args[:2]
                elif name.lstrip("_").endswith(_ERR_HELPER) and n.args:  # return _tx_err(401, …)
                    lit += n.args[:1]
                for a in lit:
                    s = _status(a)
                    if s:
                        _add(sc.facts, s)
            target = _own(_resolve(n.func, fn, local))
            if target is not None:
                sc.calls.append((target, n))
    return sc


def _bind(target: Any, call: ast.Call, out: Facts) -> None:
    """Помощник вида _own(db, Model, id, user, "not_found", "Не найдено") — подставить код и сообщение из вызова."""
    sc = _scan(target)
    for status, cparam, mparam in sc.templates:
        def at(param: str | None) -> ast.AST | None:
            if param is None or param not in sc.params:
                return None
            return _arg(call, sc.params.index(param), param)

        _add(out, status, _text(at(cparam)), _text(at(mparam)))


def _collect(fn: Any, out: Facts, seen: set, depth: int = 0) -> None:
    if fn is None or fn in seen or depth > _MAX_DEPTH:
        return
    seen.add(fn)
    sc = _scan(fn)
    for s, codes in sc.facts.items():
        for c, m in codes.items():
            _add(out, s, c, m)
    for target, call in sc.calls:
        _bind(target, call, out)
        _collect(target, out, seen, depth + 1)


def dependency_calls(dependant: Any, acc: list | None = None) -> list:
    acc = [] if acc is None else acc
    for d in getattr(dependant, "dependencies", []) or []:
        if d.call is not None:
            acc.append(d.call)
        dependency_calls(d, acc)
    return acc


def error_facts(ctx: Any) -> Facts:
    """Все HTTP-коды ошибок, которые код метода (обработчик + зависимости) может вернуть, с кодами detail.code."""
    out: Facts = {}
    seen: set = set()
    _collect(ctx.endpoint, out, seen)
    for dep in dependency_calls(ctx.dependant):
        _collect(dep, out, seen)
    for s in list(out):  # безымянный код при наличии именованных не нужен
        if len(out[s]) > 1:
            out[s].pop("", None)
    return out


ROLE_RU = {"candidate": "кандидат", "employer": "работодатель", "admin": "администратор",
           "fsp_analyst": "аналитик ФСП", "expert": "эксперт"}


def required_roles(ctx: Any) -> list[str] | None:
    """Роли из require_role(...) в зависимостях метода; None — проверки роли нет."""
    for dep in dependency_calls(ctx.dependant):
        if getattr(dep, "__qualname__", "").startswith("require_role.<locals>"):
            try:
                roles = inspect.getclosurevars(dep).nonlocals.get("roles", ())
            except (TypeError, ValueError):
                continue
            return [ROLE_RU.get(str(getattr(r, "value", r)), str(r)) for r in roles]
    return None


def access_line(ctx: Any, op: dict) -> str:
    roles = required_roles(ctx)
    if roles is not None:
        return "**Доступ:** нужен вход (JWT, `Authorization: Bearer`); роль — " + ", ".join(roles) + "."
    if op.get("security"):
        return "**Доступ:** нужен вход (JWT, `Authorization: Bearer`); любая роль."
    headers = [p["name"] for p in op.get("parameters", []) if p.get("in") == "header"]
    if headers:
        return "**Доступ:** вход по JWT не требуется; ключ или подпись передаются в заголовке " + ", ".join(
            f"`{h}`" for h in headers) + "."
    return "**Доступ:** вход не требуется (публичный метод или токен в самом запросе)."


# ---------------------------------------------------------------- сборка схемы

_ERR_REF = {"$ref": "#/components/schemas/ErrorResponse"}


def _error_schemas(spec: dict) -> None:
    comps = spec.setdefault("components", {}).setdefault("schemas", {})
    if "ErrorResponse" not in comps:
        schema = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
        comps.update(schema.pop("$defs", {}))
        comps["ErrorResponse"] = schema


def _codes_text(codes: dict[str, str]) -> str:
    named = [(c, m) for c, m in codes.items() if c]
    if not named:
        return ""
    shown = named[:8]
    items = "; ".join(f"`{c}`" + (f" — {m}" if m else "") for c, m in shown)
    more = f"; ещё {len(named) - len(shown)}" if len(named) > len(shown) else ""
    return f"Коды `detail.code`: {items}{more}."


def _example(status: int, codes: dict[str, str]) -> dict | None:
    named = [(c, m) for c, m in codes.items() if c]
    if not named:
        return None
    c, m = named[0]
    return {"detail": {"code": c, "message": m or STATUS_TEXT.get(status, "")}}


# 401 и 403 одинаковы у ~250 методов: описаны один раз в components.responses, у операций — $ref
_STD_CODES = {401: {"not_authenticated", "invalid_token", "second_factor_required"}, 403: {"forbidden"}}
_STD_RESPONSES = {
    401: ("Unauthorized", "Нужен вход: заголовок `Authorization: Bearer <JWT>` не передан или токен недействителен.", {
        "not_authenticated": "Требуется вход в систему", "invalid_token": "Токен недействителен или истёк",
        "second_factor_required": "Подтвердите вход кодом из приложения-аутентификатора"}),
    403: ("Forbidden", "Недостаточно прав: роль пользователя не подходит для метода (нужная роль — в строке «Доступ» "
                       "описания).", {"forbidden": "Недостаточно прав для этого действия"}),
}


def _std_responses(spec: dict) -> None:
    store = spec.setdefault("components", {}).setdefault("responses", {})
    for status, (name, text, codes) in _STD_RESPONSES.items():
        first = next(iter(codes))
        store[name] = {"description": text + " Коды `detail.code`: " + "; ".join(f"`{c}` — {m}" for c, m in codes.items()) + ".",
                       "content": {"application/json": {"schema": _ERR_REF,
                                                         "example": {"detail": {"code": first, "message": codes[first]}}}}}


def _document_error(op: dict, status: int, codes: dict[str, str]) -> None:
    responses = op.setdefault("responses", {})
    key = str(status)
    named = {c for c in codes if c}
    if "ats-stub" in (op.get("tags") or []) and not named:  # заглушки сторонних API отвечают в формате имитируемой системы
        responses.setdefault(key, {"description": STATUS_TEXT.get(status, "Ошибка") + ". Тело — в формате имитируемой "
                                                  "системы (Хантфлоу, Talantix, «Поток»), не `ErrorResponse`."})
        return
    if status in _STD_CODES and named <= _STD_CODES[status]:  # типовой 401/403 — общий ответ
        responses[key] = {"$ref": f"#/components/responses/{_STD_RESPONSES[status][0]}"}
        return
    text, listing, example = STATUS_TEXT.get(status, "Ошибка"), _codes_text(codes), _example(status, codes)
    resp = responses.get(key)
    if resp is None:
        resp = responses[key] = {"description": " ".join(x for x in (text + ".", listing) if x),
                                 "content": {"application/json": {"schema": _ERR_REF}}}
    else:
        resp.setdefault("content", {}).setdefault("application/json", {"schema": _ERR_REF})
        schema = resp["content"]["application/json"].get("schema") or {}
        auto_422 = status == 422 and "HTTPValidationError" in json.dumps(schema)
        if auto_422:  # FastAPI описала только проверку полей; бизнес-ошибки 422 идут в формате ErrorResponse
            resp["description"] = ("Данные не прошли проверку: либо ошибка полей `{\"detail\": [{loc, msg, type}]}`, либо "
                                   "нарушено правило предметной области `{\"detail\": {code, message}}`. " + listing).strip()
            resp["content"] = {"application/json": {"schema": {"anyOf": [_ERR_REF, schema]}}}
        elif listing and listing not in resp.get("description", ""):
            base = resp.get("description", "").rstrip()
            resp["description"] = (base + ("" if base.endswith((".", "!", "?")) or not base else ".") + " " + listing).strip()
    if example and "example" not in resp["content"]["application/json"]:
        resp["content"]["application/json"]["example"] = example


from app.core.api_docs_text import DESCRIPTIONS, FILE_RESPONSES  # noqa: E402

EXAMPLES_FILE = Path(__file__).with_name("api_examples.json")


def load_examples() -> dict[str, dict]:
    """Примеры «METHOD /путь» → {status, response, request?}: снимаются с демо-мира `make openapi-examples`."""
    try:
        return json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _attach_examples(op: dict, rec: dict) -> None:
    resp = op.get("responses", {}).get(str(rec.get("status")))
    media = ((resp or {}).get("content") or {}).get("application/json")
    if media is not None and "example" not in media and "response" in rec:
        media["example"] = copy.deepcopy(rec["response"])
        resp["description"] = (resp.get("description", "").rstrip() + " Пример — реальный ответ на демо-данных (сокращён).").strip()
    req = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if req is not None and "example" not in req and "examples" not in req and rec.get("request"):
        req["example"] = copy.deepcopy(rec["request"])


def response_refs() -> tuple[dict[str, dict], dict[str, dict]]:
    """Ссылки на модели ответов из app/core/api_models.py: «METHOD /путь» → схема, и сами схемы компонентов."""
    import typing

    from pydantic.json_schema import models_json_schema

    from app.core.api_models import all_types

    RESPONSE_TYPES = all_types()

    def base(tp):  # list[M] и dict[str, M] → M
        origin = typing.get_origin(tp)
        return typing.get_args(tp)[-1] if origin in (list, dict) else tp

    models = list(dict.fromkeys(base(tp) for tp in RESPONSE_TYPES.values()))
    _, defs = models_json_schema([(m, "serialization") for m in models], ref_template="#/components/schemas/{model}")
    refs = {}
    for key, tp in RESPONSE_TYPES.items():
        ref = {"$ref": f"#/components/schemas/{base(tp).__name__}"}
        origin = typing.get_origin(tp)
        refs[key] = {"type": "array", "items": ref} if origin is list else (
            {"type": "object", "additionalProperties": ref} if origin is dict else ref)
    return refs, defs.get("$defs", {})


def _attach_model(op: dict, schema: dict) -> bool:
    """Подставляет модель в успешный ответ, если у него нет своей схемы (обработчик возвращает dict)."""
    ok = next((c for c in op.get("responses", {}) if c.startswith("2")), None)
    if ok is None:
        return False
    media = op["responses"][ok].setdefault("content", {}).setdefault("application/json", {})
    current = media.get("schema") or {}
    if "$ref" in current or "$ref" in (current.get("items") or {}) or current.get("type") in ("string", "integer"):
        return False  # у ответа уже есть своя модель
    media["schema"] = copy.deepcopy(schema)
    return True


def _attach_file(op: dict, spec: tuple[str, dict, str]) -> None:
    media, schema, text = spec
    ok = next((c for c in op.get("responses", {}) if c.startswith("2")), None)
    if ok is not None:
        op["responses"][ok] = {"description": text, "content": {media: {"schema": copy.deepcopy(schema)}}}


def enrich(app: FastAPI, spec: dict) -> dict:
    from app.core.deps import oauth2_scheme  # noqa: F401  (импорт — чтобы зависимость была загружена до разбора)

    _error_schemas(spec)
    _std_responses(spec)
    examples = load_examples()
    refs, model_schemas = response_refs()
    spec.setdefault("components", {}).setdefault("schemas", {}).update(model_schemas)
    contexts = {}
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            for c in r.effective_route_contexts():
                for m in c.methods or ():
                    contexts.setdefault((c.path, m.lower()), c)
        elif hasattr(r, "dependant") and hasattr(r, "methods"):
            for m in r.methods or ():
                contexts.setdefault((r.path, m.lower()), r)
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            ctx = contexts.get((path, method))
            if ctx is None or not isinstance(op, dict):
                continue
            for status, codes in sorted(error_facts(ctx).items()):
                _document_error(op, status, codes)
            for key, resp in op.get("responses", {}).items():  # английские заглушки FastAPI → по-русски
                if resp.get("description") == "Validation Error":
                    resp["description"] = "Ошибка проверки полей запроса: `detail` — список `{loc, msg, type}`."
                elif resp.get("description") == "Successful Response":
                    resp["description"] = "Успешный ответ."
            if op.get("tags"):
                op["tags"] = list(dict.fromkeys(op["tags"]))
            if op.get("responses"):  # коды ответов — по возрастанию, как их читают
                op["responses"] = dict(sorted(op["responses"].items(), key=lambda kv: (not kv[0].isdigit(), kv[0])))
            if f"{method.upper()} {path}" in FILE_RESPONSES:
                _attach_file(op, FILE_RESPONSES[f"{method.upper()} {path}"])
            if f"{method.upper()} {path}" in refs:
                _attach_model(op, refs[f"{method.upper()} {path}"])
            if f"{method.upper()} {path}" in examples:
                _attach_examples(op, examples[f"{method.upper()} {path}"])
            line = access_line(ctx, op)
            base = (op.get("description") or "").rstrip()
            if not base:  # авторского описания у обработчика нет — берём из таблицы api_docs_text.py
                base = DESCRIPTIONS.get(f"{method.upper()} {path}", "")
            op["description"] = f"{base}\n\n{line}" if base else line
    return spec


def install_openapi(app: FastAPI) -> None:
    """Подменяет app.openapi(): схема FastAPI + выведенные из кода ошибки и доступ (кэшируется, как в FastAPI)."""
    original = app.openapi
    lock = threading.Lock()
    done = False

    def openapi() -> dict[str, Any]:
        nonlocal done
        with lock:  # два первых запроса одновременно не должны отдать схему до обогащения
            if not done:
                app.openapi_schema = enrich(app, original())
                done = True
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def canonical_json(spec: dict) -> str:
    """Каноническая запись спецификации для docs/api/openapi.json: отсортированные ключи, UTF-8, перевод строки в конце."""
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
