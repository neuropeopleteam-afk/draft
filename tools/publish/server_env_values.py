#!/usr/bin/env python3
"""Значения секретов с сервера для проверки истории перед публикацией: stdin → stdout (значения НЕ печатаются на экран).

Читает со стандартного ввода текст env-файлов сервера (только чтение; в репозиторий и в журналы они не попадают) и пишет на
стандартный вывод строки JSON {"v": значение, "src": источник} для `scan_history_values.py --values` и
`check_public_tree.py --values`. Источник — только имя файла и ключа, без значения. Отказывается работать, если вывод —
терминал (чтобы значения не оказались на экране или в журнале сессии): перенаправляйте в файл в оперативной памяти.

Формат входа — обычные env-файлы `KEY=VALUE`; перед каждым файлом строка-метка `##FILE <имя>`; файлы паролей (`*.pw`) —
одна строка со значением. Берутся значения ключей с SECRET, PASSWORD, TOKEN, _KEY, _PW, FOLDER_ID, ACCESS_KEY_ID,
VACANCY_ID в имени длиной от 6 символов; адреса (http/https), `*_FILE`, `*_URL`, `*PUBLIC_KEY`, `*_PORT` пропускаются.
К каждому значению добавляются варианты кодирования: URL, JSON, base64 пары `demo:<значение>` (заголовок Basic).

Шаг в чек-листе публикации (в памяти, без вывода; команды — в reports_0910/pubrepo_decisions.md):

    umask 077; VALS=$(mktemp -p /dev/shm)
    python3 reports_0910/pubrepo_tools/extract_secret_values.py "$VALS"          # значения из .secrets и файлов передачи
    ssh <сервер, только чтение> 'cd /opt/spectrek_fsp && for f in secrets/*.env app/.env secrets/*.pw; do echo "##FILE $f"; cat "$f"; done' \\
      | python3 tools/publish/server_env_values.py >> "$VALS"
    ops/publish_repo.sh --remote <адрес> --branch main --values "$VALS"          # dry-run, затем --execute
    shred -u "$VALS"
Код выхода: 0 — значения выданы, 2 — вывод в терминал или пустой вход.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import urllib.parse

KEY_RE = re.compile(r"SECRET|PASSWORD|TOKEN|_KEY|_PW|FOLDER_ID|ACCESS_KEY_ID|VACANCY_ID")
SKIP_KEY_SUFFIX = ("_FILE", "_URL", "PUBLIC_KEY", "_PORT")
MIN_LEN = 6


def parse(text: str) -> dict[str, str]:
    """{значение: источник} из текста env-файлов; значения не логируются."""
    out: dict[str, str] = {}
    cur = "?"
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("##FILE "):
            cur = line[7:].strip()
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if value.startswith(("http://", "https://")) or key.endswith(SKIP_KEY_SUFFIX):
                continue
            if KEY_RE.search(key) and len(value) >= MIN_LEN:
                out.setdefault(value, f"server:{cur}:{key}")
        elif cur.endswith(".pw") and len(line.strip()) >= MIN_LEN:
            out.setdefault(line.strip(), f"server:{cur}")
    return out


def with_variants(values: dict[str, str]) -> dict[str, str]:
    out = dict(values)
    for v, src in values.items():
        for var in (urllib.parse.quote(v, safe=""), json.dumps(v, ensure_ascii=False)[1:-1]):
            if var != v:
                out.setdefault(var, src + "+enc")
        out.setdefault(base64.b64encode(("demo:" + v).encode()).decode().rstrip("="), src + "+basic")
    return out


def main() -> int:
    if sys.stdout.isatty():
        print("вывод — терминал: перенаправьте в файл в памяти (>> \"$VALS\"), значения не печатаются", file=sys.stderr)
        return 2
    values = parse(sys.stdin.read())
    if not values:
        print("во входе нет значений секретов (ожидаются env-файлы с метками ##FILE)", file=sys.stderr)
        return 2
    for v, src in with_variants(values).items():
        sys.stdout.write(json.dumps({"v": v, "src": src}, ensure_ascii=False) + "\n")
    print(f"значений с вариантами кодирования: {len(with_variants(values))} (исходных {len(values)})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
