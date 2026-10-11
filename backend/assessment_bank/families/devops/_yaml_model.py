"""Общий помощник семейств devops: вывод YAML-манифестов и разбор того же подмножества в песочнице.

Песочница Python запускается с ``-I -S`` — PyYAML там недоступен. Поэтому проверки ключа (модели
Kubernetes, CI, Prometheus) встраивают в программу исходник :data:`PARSER_SRC` — небольшой разборщик
подмножества YAML (блочные словари и списки, скаляры, списки в квадратных скобках, блочный текст ``|``),
и разбирают ровно тот текст, который видит кандидат. :func:`emit` выводит словари и списки Python в это
подмножество; круговая проверка ``parse(emit(x)) == x`` — в тестах банка (tests/test_devops_de.py).
"""
from __future__ import annotations

import re
from typing import Any


class Flow(list):
    """Список скаляров, который выводится одной строкой: ``["CMD", "curl", "-f"]``."""


class Block(str):
    """Многострочный текст, который выводится блоком ``|``."""


_PLAIN_RE = re.compile(r"^[A-Za-z0-9_./@=+$-][A-Za-z0-9_./@=+$:()*, -]*$")


def scalar(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    needs_quotes = (not s or not _PLAIN_RE.match(s) or ": " in s or s.endswith(":") or s in ("true", "false", "null")
                    or re.fullmatch(r"-?\d+", s) is not None or s.startswith("- ") or s != s.strip())
    if needs_quotes:
        if '"' in s or "\\" in s:
            raise ValueError(f"строку с кавычкой или обратной косой не выводим: {s!r}")
        return f'"{s}"'
    return s


def emit(obj: Any, indent: int = 0) -> str:
    """Словарь/список Python → YAML (подмножество, которое понимает PARSER_SRC)."""
    return "\n".join(_emit(obj, indent)) + "\n"


def _emit(obj: Any, ind: int) -> list[str]:
    pad = " " * ind
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_emit_kv(str(k), v, ind))
        return out
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item:
                sub = _emit(item, ind + 2)
                out.append(pad + "- " + sub[0][ind + 2:])
                out.extend(sub[1:])
            elif isinstance(item, (dict, list)):
                raise ValueError("пустые словари и вложенные списки в списке не выводим")
            else:
                out.append(pad + "- " + scalar(item))
        return out
    raise TypeError(type(obj))


def _emit_kv(k: str, v: Any, ind: int) -> list[str]:
    pad = " " * ind
    if isinstance(v, Flow):
        return [pad + f"{k}: [" + ", ".join(scalar(x) for x in v) + "]"]
    if isinstance(v, Block):
        body = [pad + "  " + line if line else "" for line in v.rstrip("\n").split("\n")]
        return [pad + f"{k}: |"] + body
    if isinstance(v, dict):
        if not v:
            return [pad + f"{k}: {{}}"]
        return [pad + f"{k}:"] + _emit(v, ind + 2)
    if isinstance(v, list):
        if not v:
            return [pad + f"{k}: []"]
        return [pad + f"{k}:"] + _emit(v, ind + 2)
    return [pad + f"{k}: {scalar(v)}"]


# Исходник разборщика для программ проверки (исполняется в песочнице как есть).
PARSER_SRC = r'''
import re as _re

_KEY_RE = _re.compile(r"^[A-Za-z0-9_.\-/\"']+:( |$)")


def _split_flow(s):
    out, cur, q = [], "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _scalar(v):
    v = v.strip()
    if v == "" or v in ("null", "~"):
        return None
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_scalar(x) for x in _split_flow(inner)] if inner else []
    if v == "{}":
        return {}
    if v in ("true", "false"):
        return v == "true"
    if _re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _lines(text):
    out = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw.strip() == "---":
            continue
        out.append([len(raw) - len(raw.lstrip(" ")), raw.strip(), raw])
    return out


def _block(ls, i, ind):
    if ls[i][1] == "-" or ls[i][1].startswith("- "):
        return _seq(ls, i, ind)
    return _map(ls, i, ind)


def _map(ls, i, ind):
    out = {}
    while i < len(ls) and ls[i][0] == ind and not (ls[i][1] == "-" or ls[i][1].startswith("- ")):
        key, _, rest = ls[i][1].partition(":")
        key = key.strip().strip("\"'")
        rest = rest.strip()
        i += 1
        if rest in ("|", "|-", ">"):
            body = []
            base = None
            while i < len(ls) and ls[i][0] > ind:
                base = ls[i][0] if base is None else base
                body.append(ls[i][2][base:])
                i += 1
            val = "\n".join(body) + ("\n" if rest == "|" else "")
        elif rest == "":
            if i < len(ls) and (ls[i][0] > ind or (ls[i][0] == ind and ls[i][1].startswith("- "))):
                val, i = _block(ls, i, ls[i][0])
            else:
                val = None
        else:
            val = _scalar(rest)
        out[key] = val
    return out, i


def _seq(ls, i, ind):
    out = []
    while i < len(ls) and ls[i][0] == ind and (ls[i][1] == "-" or ls[i][1].startswith("- ")):
        content = ls[i][1][2:]
        if _KEY_RE.match(content) and not content.startswith("["):
            ls[i] = [ind + 2, content, " " * (ind + 2) + content]
            val, i = _map(ls, i, ind + 2)
        else:
            val = _scalar(content)
            i += 1
        out.append(val)
    return out, i


def parse_yaml(text):
    ls = _lines(text)
    if not ls:
        return None
    val, i = _block(ls, 0, ls[0][0])
    if i != len(ls):
        raise ValueError("не разобрана строка: " + ls[i][2])
    return val


def parse_yaml_docs(text):
    """Несколько документов через ---."""
    docs, cur = [], []
    for raw in text.splitlines():
        if raw.strip() == "---":
            if any(x.strip() for x in cur):
                docs.append(parse_yaml("\n".join(cur)))
            cur = []
        else:
            cur.append(raw)
    if any(x.strip() for x in cur):
        docs.append(parse_yaml("\n".join(cur)))
    return docs
'''


def parse(text: str) -> Any:
    """Тот же разборщик в процессе генератора (для самопроверки и тестов)."""
    ns: dict[str, Any] = {}
    exec(compile(PARSER_SRC, "<yaml_model>", "exec"), ns)  # noqa: S102 — исходник банка, не кандидата
    return ns["parse_yaml"](text)


def parse_docs(text: str) -> list[Any]:
    ns: dict[str, Any] = {}
    exec(compile(PARSER_SRC, "<yaml_model>", "exec"), ns)  # noqa: S102
    return ns["parse_yaml_docs"](text)


def program(model_body: str, **texts: str) -> str:
    """Программа проверки: разборщик + показанные тексты дословно (r-строки) + тело модели."""
    parts = [PARSER_SRC]
    for name, text in texts.items():
        if '"""' in text or text.endswith("\\"):
            raise ValueError("текст нельзя встроить в r-строку")
        parts.append(f'{name} = r"""{text}"""')
    parts.append(model_body)
    return "\n\n".join(parts) + "\n"
