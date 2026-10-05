"""Метрики кода для инвариантов семейства: размер кода и число операций.

Определения намеренно простые и воспроизводимые — их же пересчитывает валидатор.

* code_lines — число непустых строк, не являющихся только комментарием.
* operations:
  - python: число операторов AST (присваивания, вызовы-выражения, return, if/for/while…),
    без def/class/import/pass и строк документации;
  - javascript/typescript: число «значимых» строк — без строк из одних скобок,
    комментариев, объявлений interface/type;
  - sql: число предложений (SELECT, FROM, JOIN, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, WITH);
  - bash: число команд (разделители — перевод строки, |, &&, ;) без определения функций.
"""
from __future__ import annotations

import ast
import re

_COMMENT_PREFIX = {"python": "#", "bash": "#", "sql": "--", "javascript": "//",
                   "typescript": "//"}


def count_code_lines(code: str | None, language: str) -> int:
    if not code:
        return 0
    prefix = _COMMENT_PREFIX.get(language)
    n = 0
    for line in code.splitlines():
        s = line.strip()
        if not s:
            continue
        if prefix and s.startswith(prefix):
            continue
        n += 1
    return n


def _py_ops(code: str) -> int:
    tree = ast.parse(code)
    skip = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom,
            ast.Pass)
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or isinstance(node, skip):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str):
            continue  # строка документации
        n += 1
    return n


_JS_SKIP = re.compile(r"^[\s{}()\[\];,]*$")
_JS_DECL = re.compile(r"^\s*(export\s+)?(interface|type)\s+\w+")


def _js_ops(code: str) -> int:
    n = 0
    in_iface = 0
    for line in code.splitlines():
        s = line.strip()
        if not s or s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        if _JS_DECL.match(s):
            in_iface = 0 if s.endswith(";") or (s.endswith("}") and "{" in s) else 1
            continue
        if in_iface:
            if s.startswith("}"):
                in_iface = 0
            continue
        if _JS_SKIP.match(s):
            continue
        n += 1
    return n


_SQL_CLAUSES = re.compile(
    r"\b(SELECT|FROM|(?:LEFT |RIGHT |INNER |FULL )?JOIN|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|WITH)\b",
    re.IGNORECASE)


def _sql_ops(code: str) -> int:
    no_comments = "\n".join(l for l in code.splitlines() if not l.strip().startswith("--"))
    return len(_SQL_CLAUSES.findall(no_comments))


def _bash_ops(code: str) -> int:
    n = 0
    for line in code.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.match(r"^\w+\s*\(\)\s*\{", s):  # определение функции — не операция
            continue
        parts = [p for p in re.split(r"\|\||&&|\||;", s) if p.strip() and p.strip() != "}"]
        n += len(parts)
    return n


def count_operations(code: str | None, language: str) -> int:
    if not code:
        return 0
    if language == "python":
        return _py_ops(code)
    if language in ("javascript", "typescript"):
        return _js_ops(code)
    if language == "sql":
        return _sql_ops(code)
    if language == "bash":
        return _bash_ops(code)
    return 0


def normalize_output(text: str) -> str:
    """Нормализация вывода программы и ответа кандидата перед сравнением.

    Схлопываем пробелы внутри строк, убираем пустые строки по краям. Так ответ не зависит
    от ширины выравнивания (например, `uniq -c` в GNU и uutils) и лишних пробелов.
    """
    lines = [" ".join(l.split()) for l in text.strip().splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
