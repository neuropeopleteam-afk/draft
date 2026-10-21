"""Очистка истории для публикации, вариант В (`ops/publish_repo.sh --filter`): обратные вызовы git filter-repo.

Правила — те же, что у tools/publish/check_public_tree.py (модуль загружается из исходного репозитория):
* пути из списка исключений (`PUBLISH_EXCLUDE` — файл, по одному пути или каталогу `dir/` в строке) удаляются из всех
  коммитов;
* у остальных файлов содержимое меняется ТОЛЬКО в тех версиях, где check_public_tree нашёл бы нарушение: публичный
  IPv4 → 198.51.100.1 (документационный, RFC 5737), пути рабочего места, ссылки на внутренние документы, жаргон,
  закрытые ссылки Google Drive → нейтральные заглушки, значения секретов из `PUBLISH_VALUES` → «***»;
  версии без нарушений не трогаются (поэтому дерево головы совпадает с исходным за вычетом исключённых путей);
* сообщения коммитов — те же текстовые замены.

Переменные окружения: PUBLISH_CPT (путь к check_public_tree.py), PUBLISH_EXCLUDE, PUBLISH_VALUES (необязательно).
Значения секретов и найденные строки никуда не печатаются.
"""
from __future__ import annotations

import importlib.util
import os
import re

_spec = importlib.util.spec_from_file_location("cpt", os.environ["PUBLISH_CPT"])
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)  # type: ignore[union-attr]

EXCLUDE: list[str] = []
for _l in open(os.environ["PUBLISH_EXCLUDE"], encoding="utf-8"):
    _l = _l.strip()
    if _l and not _l.startswith("#"):
        EXCLUDE.append(_l)
VALUES: list[bytes] = C.load_values(os.environ.get("PUBLISH_VALUES") or None)

# замены по правилам check_public_tree: (название правила, регэксп всей «опасной» подстроки, замена)
SUBS = [
    ("путь рабочего места", re.compile(r"/home/user/|/workspace/"), "/srv/work/"),
    ("путь рабочего места", re.compile(r"\.secrets\b"), ".private"),
    ("ссылка на внутренний отчёт или передачу дел",
     re.compile(r"[\w./-]*(?:reports_0\d{3}|tasks_0\d{3}|HANDOVER|handover/|PLAN_0\d{3})[\w./-]*"), "<внутренний документ>"),
    ("внутренний жаргон процесса", re.compile(r"(?<![а-яё])(?:штаб|слиянщик)[а-яё]*", re.I), "команда"),
    ("закрытая ссылка Google Drive", re.compile(r"\S*drive\.google\.com/file\S*"), "<закрытая ссылка>"),
]
STATS = {"dropped": 0, "rewritten": 0, "messages": 0}


def excluded(path: str) -> bool:
    return any(path == e or (e.endswith("/") and path.startswith(e)) or path.startswith(e.rstrip("/") + "/") for e in EXCLUDE)


def _ip_sub(m: re.Match) -> str:
    return m.group(0) if C.IP_OK.match(m.group(1)) else "198.51.100.1"


def clean_text(text: str, path: str | None = None) -> str:
    allow = C.ALLOW.get(path, ()) if path else ()
    out = []
    for line in text.split("\n"):
        line = C.IPV4.sub(_ip_sub, line)
        for rule, rx in C.RULES:
            if rule in allow or not rx.search(line):
                continue
            for _ in range(5):  # «/home/user/workspace/…»: после первой замены снова встаёт «/workspace/»
                for r2, sub_rx, repl in SUBS:
                    if r2 == rule:
                        line = sub_rx.sub(repl, line)
                if not rx.search(line):
                    break
        out.append(line)
    return "\n".join(out)


def violates(path: str, data: bytes) -> bool:
    if any(v in data for v in VALUES):
        return True
    if path in C.IGNORE_SELF or C.SKIP.search(path):
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    allow = C.ALLOW.get(path, ())
    for line in text.splitlines():
        if any(not C.IP_OK.match(m.group(1)) for m in C.IPV4.finditer(line)):
            return True
        if any(rule not in allow and rx.search(line) for rule, rx in C.RULES):
            return True
    return False


def file_info(filename: bytes, mode: bytes, blob_id, value):
    path = filename.decode("utf-8", "replace")
    if excluded(path):
        STATS["dropped"] += 1
        return (None, mode, blob_id)
    if mode == b"160000":
        return (filename, mode, blob_id)
    data = value.get_contents_by_identifier(blob_id)
    if not violates(path, data):
        return (filename, mode, blob_id)
    for v in VALUES:
        data = data.replace(v, b"***")
    if not (path in C.IGNORE_SELF or C.SKIP.search(path)):
        try:
            data = clean_text(data.decode("utf-8"), path).encode("utf-8")
        except UnicodeDecodeError:
            pass
    STATS["rewritten"] += 1
    return (filename, mode, value.insert_file_with_contents(data))


def message(msg: bytes) -> bytes:
    for v in VALUES:
        msg = msg.replace(v, b"***")
    try:
        new = clean_text(msg.decode("utf-8")).encode("utf-8")
    except UnicodeDecodeError:
        return msg
    if new != msg:
        STATS["messages"] += 1
    return new
