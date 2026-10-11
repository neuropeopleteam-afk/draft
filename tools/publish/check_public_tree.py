#!/usr/bin/env python3
"""Проверка дерева репозитория перед публикацией: нет ли того, чего в открытом коде быть не должно.

    python tools/publish/check_public_tree.py [--repo .] [--values /путь/к/файлу_значений] [--rev HEAD]

Проверяется содержимое файлов, отслеживаемых git (`git ls-files` либо дерево коммита `--rev`):

* серверные и иные публичные IPv4-адреса (кроме явных тестовых и документационных);
* пути рабочего места (`/home/user/`, `/workspace/`, `.secrets`);
* ссылки на внутренние отчёты и файлы передачи дел (`reports_0910/…`, `HANDOVER…`, `tasks_0910…`);
* внутренний жаргон процесса («штаб», «слиянщик», «перевешено слиянщиком»);
* закрытые ссылки Google Drive;
* запрещённые имена файлов (`.env`, `*.pem`, `*.key`, `id_rsa*`, `HANDOVER*`, `TZ_*`) и файлы больше 20 МБ;
* значения секретов из файла `--values` (по одному в строке или JSON `{"v": …}`); значения не печатаются.

Печатаются путь, номер строки и название правила — но не само найденное значение. Код выхода: 0 — чисто, 1 — есть нарушения.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

IPV4 = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])")
# частные, служебные и документационные адреса и широко известные публичные резолверы (в тестах и примерах)
IP_OK = re.compile(
    r"^(127\.|0\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|255\.|203\.0\.113\.|198\.51\.100\.|192\.0\.2\.|"
    r"1\.1\.1\.1$|8\.8\.8\.8$|8\.8\.4\.4$|9\.9\.9\.9$|1\.2\.3\.4$|5\.5\.5\.5$|6\.6\.6\.6$)")
RULES = [
    ("путь рабочего места", re.compile(r"/home/user/|/workspace/|\.secrets\b")),
    ("ссылка на внутренний отчёт или передачу дел", re.compile(r"reports_0\d{3}|tasks_0\d{3}|HANDOVER|handover/|PLAN_0\d{3}")),
    ("внутренний жаргон процесса", re.compile(r"(?<![а-яё])штаб|слиянщик|перевешен[оа] слиянщик", re.I)),
    ("закрытая ссылка Google Drive", re.compile(r"drive\.google\.com/file")),
]
BAD_NAMES = re.compile(r"(^|/)(\.env|id_rsa[^/]*|HANDOVER[^/]*|TZ_[^/]*|[^/]+\.(pem|key|p12|pfx))$")
# ни вендорные, ни сгенерированные файлы не проверяем построчно
SKIP = re.compile(r"(^|/)(package-lock\.json|static/apidocs/|public/vendor/|.*\.(png|jpg|jpeg|gif|svg|ico|wasm|tflite|gz|pdf|docx|y4m|woff2?))$")
# Утилиты (Л13) читают экспертные разметки и отчёты вне репозитория: в README они перечислены как не запускаемые на чистом клоне.
# Пути к этим внешним входам оставлены намеренно; остальные правила для этих файлов действуют.
ALLOW = {
    "tools/must_have/evaluate.py": {"путь рабочего места", "ссылка на внутренний отчёт или передачу дел"},
    "tools/core_skill/evaluate.py": {"путь рабочего места", "ссылка на внутренний отчёт или передачу дел"},
    "tools/realdata/audit_expert_ranking.py": {"путь рабочего места", "ссылка на внутренний отчёт или передачу дел"},
}
IGNORE_SELF = {"tools/publish/check_public_tree.py", "tools/publish/scan_history_values.py", "tools/publish/test_publish_tools.py"}
MAX_BYTES = 20 * 1024 * 1024


def git(repo: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True).stdout


def load_values(path: str | None) -> list[bytes]:
    if not path:
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("{"):
            try:
                line = json.loads(line)["v"]
            except Exception:
                pass
        if len(line) >= 6:
            out.append(line.encode("utf-8"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--rev", default=None, help="проверять дерево коммита вместо рабочего каталога")
    ap.add_argument("--values", default=None)
    ap.add_argument("--max-lines", type=int, default=60)
    a = ap.parse_args()
    values = load_values(a.values)
    if a.rev:
        # одно `git cat-file --batch` на всё дерево вместо `git show` на каждый файл (на загруженной машине — в десятки раз быстрее)
        oid_of: dict[str, str] = {}
        for ent in git(a.repo, "ls-tree", "-r", "-z", a.rev).decode("utf-8", "replace").split("\0"):
            meta, _, path = ent.partition("\t")
            parts = meta.split()
            if path and len(parts) == 3 and parts[1] == "blob":
                oid_of[path] = parts[2]
        names = list(oid_of)
        batch = subprocess.Popen(["git", "-C", a.repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

        def read(n: str) -> bytes:
            assert batch.stdin and batch.stdout
            batch.stdin.write(oid_of[n].encode() + b"\n")
            batch.stdin.flush()
            header = batch.stdout.readline().split()
            if len(header) < 3:
                raise OSError(f"нет объекта для {n}")
            data = batch.stdout.read(int(header[2]))
            batch.stdout.read(1)
            return data
    else:
        names = [n for n in git(a.repo, "ls-files").decode().splitlines() if n]
        read = lambda n: open(f"{a.repo}/{n}", "rb").read()  # noqa: E731
    viol: list[str] = []
    counts: dict[str, int] = {}

    def add(rule: str, path: str, line: int | None = None) -> None:
        counts[rule] = counts.get(rule, 0) + 1
        viol.append(f"{rule}: {path}" + (f":{line}" if line else ""))

    for n in names:
        if n in IGNORE_SELF:
            continue
        if BAD_NAMES.search(n) and n not in ("infra/llm-local/llm-local.env",):
            add("запрещённое имя файла", n)
        try:
            data = read(n)
        except Exception:
            continue
        if len(data) > MAX_BYTES:
            add("файл больше 20 МБ", n)
        for v in values:
            if v in data:
                add("значение секрета из файла --values", n)
        if SKIP.search(n):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in IPV4.finditer(line):
                if not IP_OK.match(m.group(1)):
                    add("публичный IPv4-адрес", n, i)
            for rule, rx in RULES:
                if rx.search(line) and rule not in ALLOW.get(n, ()):
                    add(rule, n, i)
    for v in viol[: a.max_lines]:
        print(v)
    if len(viol) > a.max_lines:
        print(f"… и ещё {len(viol) - a.max_lines}")
    print(f"проверено файлов: {len(names)}; нарушений: {len(viol)}" + (f" ({', '.join(f'{k}: {c}' for k, c in sorted(counts.items()))})" if counts else ""))
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
