#!/usr/bin/env python3
"""Генерация THIRD_PARTY.md: сторонние компоненты, их версии и лицензии (pip и npm, вендорные файлы, образы, данные).

    python tools/publish/gen_third_party.py [--python-app PY] [--python-bank PY] [--check]

* pip — замыкание зависимостей (с транзитивными) от файлов требований, лицензии из метаданных установленных пакетов.
  `--python-app` — интерпретатор окружения бэкенда (по умолчанию тот, что запускает скрипт), `--python-bank` — окружения банка
  заданий (там же Django для проверки ключей); если не задан, банк берётся из окружения бэкенда, а недостающее помечается.
* npm — `frontend/package-lock.json` и `e2e/package-lock.json` (поле `license` каждого пакета, признак `dev`).
* вендорные файлы, шрифты, образы Docker, данные — таблицы ниже (`VENDORED`, `IMAGES`, `DATA`), правятся вручную.
* `--check` — не писать файл и не требовать окружений pip: убедиться, что каждый пин из файлов требований и каждый пакет из
  lock-файлов npm есть в THIRD_PARTY.md с той же версией (код выхода 1, если файл устарел); используется в CI.

Скрипт без сети: данные берутся из установленных пакетов и lock-файлов.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "THIRD_PARTY.md"

PIP_GROUPS = [
    ("Бэкенд (рантайм)", ["backend/requirements.txt"], "app"),
    ("Разработка и тесты бэкенда", ["backend/requirements-dev.txt"], "app"),
    ("Банк заданий (`backend/assessment_bank`, ставится отдельно для проверки ключей)", ["backend/assessment_bank/BANK_requirements.txt"], "bank"),
]

# лицензии, которые в метаданных не указаны или указаны длинным текстом (проверено по исходникам пакетов)
LICENSE_OVERRIDES = {
    "natasha": "MIT", "navec": "MIT", "slovnet": "MIT", "yargy": "MIT", "razdel": "MIT", "ipymarkup": "MIT",
    "pymorphy2": "MIT", "pymorphy2-dicts-ru": "MIT", "dawg-python": "MIT", "docopt": "MIT",
    "pywebpush": "MPL-2.0", "py-vapid": "MPL-2.0", "http-ece": "MIT",
    "psycopg": "LGPL-3.0-only", "psycopg-binary": "LGPL-3.0-only",
    "reportlab": "BSD-3-Clause", "uvicorn": "BSD-3-Clause", "numpy": "BSD-3-Clause", "scipy": "BSD-3-Clause",
    "python-dateutil": "Apache-2.0 / BSD-3-Clause", "packaging": "Apache-2.0 / BSD-2-Clause",
    "cryptography": "Apache-2.0 / BSD-3-Clause", "certifi": "MPL-2.0", "chardet": "LGPL-2.1-or-later",
    "pillow": "MIT-CMU", "pypdf": "BSD-3-Clause", "websockets": "BSD-3-Clause", "idna": "BSD-3-Clause",
    "sniffio": "MIT / Apache-2.0", "anyio": "MIT", "h11": "MIT", "httpcore": "BSD-3-Clause", "httpx": "BSD-3-Clause",
    "django": "BSD-3-Clause", "asgiref": "BSD-3-Clause", "sqlparse": "BSD-3-Clause",
}

CLASSIFIER_MAP = {
    "MIT License": "MIT", "BSD License": "BSD", "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "The Unlicense (Unlicense)": "Unlicense",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0", "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1-or-later",
    "Public Domain": "Public Domain", "Zlib/Libpng": "Zlib",
}

# Вендорные и встроенные в репозиторий файлы
VENDORED = [
    ("Swagger UI, пакет swagger-ui-dist 5.33.1 (`backend/app/static/apidocs/swagger-ui-*`), вендорен, чтобы документация API не зависела от внешних CDN", "Apache-2.0", "`backend/app/static/apidocs/LICENSE.swagger-ui`"),
    ("ReDoc 2.5.4 (`backend/app/static/apidocs/redoc.standalone.js`)", "MIT", "`backend/app/static/apidocs/LICENSE.redoc`"),
    ("MediaPipe Tasks Vision 1.1.0, wasm и js (`frontend/public/vendor/mediapipe/1.1.0/`) — детекция лица в тесте по согласию, работает в браузере, видео не отправляется", "Apache-2.0", "`frontend/public/vendor/mediapipe/1.1.0/LICENSE`"),
    ("Модель BlazeFace short range (`blaze_face_short_range.tflite`, там же)", "Apache-2.0 (модель Google MediaPipe)", "`frontend/public/vendor/mediapipe/1.1.0/LICENSE`"),
]

FONTS_ICONS = [
    ("Montserrat", "SIL Open Font License 1.1", "подключается как npm-пакет `@fontsource/montserrat`; файлы шрифтов в репозитории не лежат, попадают только в сборку `frontend/dist`"),
    ("DejaVu Sans", "Bitstream Vera License / Public Domain для правок DejaVu", "ставится в образ API пакетом ОС `fonts-dejavu-core` для кириллицы в PDF-профиле; в репозитории не хранится"),
    ("Иконки интерфейса и PWA (`frontend/public/icons/`, `favicon.svg`) и встроенные SVG-значки", "MIT (авторские, часть проекта)", "нарисованы в проекте; чужих наборов иконок (Font Awesome, Material, Lucide и т. п.) нет"),
]

IMAGES = [
    ("`python:3.12-slim`", "PSF-2.0 (Python); Debian — набор лицензий пакетов", "образ API (`backend/Dockerfile`)"),
    ("`node:20-alpine`", "MIT (Node.js); Alpine — набор лицензий пакетов", "только сборка фронтенда (`frontend/Dockerfile`)"),
    ("`nginx:1.27-alpine`", "BSD-2-Clause", "раздача фронтенда (`frontend/Dockerfile`)"),
    ("`postgres:16-alpine`", "PostgreSQL License", "база данных (`docker-compose.yml`)"),
    ("`quay.io/keycloak/keycloak:26.4.0`", "Apache-2.0", "демо «ФСП ID», профиль `fsp-id` (`keycloak/Dockerfile`)"),
    ("`ghcr.io/ggml-org/llama.cpp:server-b11515`", "MIT", "локальная открытая модель, профиль `llm-local` (по умолчанию выключен)"),
    ("Qwen3.5-9B (GGUF, `unsloth/Qwen3.5-9B-GGUF:Q4_K_M`)", "Apache-2.0 (по [карточке модели Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B); квантование GGUF — unsloth)", "скачивается с Hugging Face только при `make llm-local`, в репозитории нет"),
]

DATA = [
    ("Калькулятор зарплат Хабр Карьеры: агрегаты (перцентили по специализациям) на 05.10.2026", "`docs/data_habr_salary_raw_20261005.json`, `docs/SALARY_SOURCES.md`",
     "публичные агрегаты страницы калькулятора; источник и дата указаны; персональных данных нет"),
    ("50 публичных объявлений о вакансиях: дословные фрагменты, URL источника, дата сбора 07.10.2026, SHA-256", "`docs/realdata/vacancies_50.json`, тесты разбора потребности",
     "права на тексты принадлежат авторам объявлений; используются только как проверочный корпус разбора; контактов нет; по запросу правообладателя будут удалены"),
    ("Модельные кандидаты, работодатели, вакансии демо-стенда", "`backend/app/modules/demo/`, `backend/app/modules/jury/seed.py`",
     "синтетические, имена и почты вымышлены (`*@demo.invalid`); совпадения с реальными людьми случайны"),
    ("Фотография лица для проверки камеры в e2e (`e2e/fixtures/webcam_face.jpg`, `webcam_face.y4m`)", "`e2e/fixtures/`",
     "сгенерирована нейросетью, лицо несуществующего человека; используется только в автотесте"),
    ("Снимки экранов интерфейса в `docs/**/*.png`", "`docs/`", "собственные, сняты с демо-данными"),
    ("Задания банка (`backend/assessment_bank/families`)", "`backend/assessment_bank/`", "авторские, генерируются параметрически; лицензия — `BANK_LICENSE` (MIT)"),
]

COLLECTOR = r"""
import json, re, sys
from importlib import metadata
from packaging.requirements import Requirement
from packaging.markers import default_environment

files = sys.argv[1:]
def canon(n): return re.sub(r"[-_.]+", "-", n).lower()

direct = []
for f in files:
    for line in open(f, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            direct.append(Requirement(line))
        except Exception:
            pass
dists = {canon(d.metadata["Name"]): d for d in metadata.distributions() if d.metadata["Name"]}
seen, missing, order = {}, [], []
stack = [(r.name, set(r.extras), True) for r in direct]
while stack:
    name, extras, is_direct = stack.pop()
    c = canon(name)
    d = dists.get(c)
    if d is None:
        missing.append(c); continue
    key = c
    if key in seen:
        seen[key]["extras"] |= extras
        continue
    seen[key] = {"d": d, "extras": set(extras), "direct": is_direct}
    for req in (d.requires or []):
        r = Requirement(req)
        env = dict(default_environment())
        ok = True
        if r.marker is not None:
            ok = False
            for ex in (extras or {""}):
                env["extra"] = ex
                if r.marker.evaluate(env):
                    ok = True; break
        if ok:
            stack.append((r.name, set(r.extras), False))
out = []
for c, v in sorted(seen.items()):
    d = v["d"]; m = d.metadata
    out.append({"name": m["Name"], "version": d.version, "direct": c in {canon(r.name) for r in direct},
                "license_expression": m.get("License-Expression"), "license": m.get("License"),
                "classifiers": [x for x in m.get_all("Classifier") or [] if x.startswith("License ::")]})
print(json.dumps({"packages": out, "missing": sorted(set(missing))}, ensure_ascii=False))
"""


def canon(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def license_of(p: dict) -> tuple[str, bool]:
    """(строка лицензии, найдено ли надёжно)"""
    name = canon(p["name"])
    if p.get("license_expression"):
        return p["license_expression"], True
    cls = [CLASSIFIER_MAP.get(c.split(" :: ")[-1], None) for c in p["classifiers"] if "OSI Approved" in c or "Public Domain" in c]
    cls = [c for c in cls if c]
    lic = (p.get("license") or "").strip()
    if name in LICENSE_OVERRIDES:
        return LICENSE_OVERRIDES[name], True
    if cls:
        return " / ".join(dict.fromkeys(cls)), True
    if lic and len(lic) <= 40 and "\n" not in lic and lic.upper() != "UNKNOWN":
        return lic, True
    return "не указана в метаданных (см. исходники пакета)", False


def collect_pip(python: str, files: list[str]) -> dict:
    cmd = [python, "-c", COLLECTOR, *[str(ROOT / f) for f in files]]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"сбор метаданных pip не удался ({python}): {res.stderr[-400:]}")
    return json.loads(res.stdout)


def md_table(rows: list[list[str]], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    return "\n".join(out)


def npm_rows(lock: Path) -> tuple[list[list[str]], list[list[str]], int]:
    d = json.loads(lock.read_text(encoding="utf-8"))
    prod, dev = [], []
    for path, v in sorted(d["packages"].items()):
        if not path:
            continue
        name = path.split("node_modules/")[-1]
        lic = v.get("license") or "не указана"
        if isinstance(lic, dict):
            lic = lic.get("type", "?")
        row = [f"`{name}`", v.get("version", "?"), str(lic)]
        (dev if v.get("dev") else prod).append(row)
    return prod, dev, len(prod) + len(dev)


def build(python_app: str, python_bank: str | None) -> tuple[str, list[str]]:
    warn: list[str] = []
    L: list[str] = []
    L += ["# Сторонние компоненты и лицензии", "",
          "Код проекта — MIT, см. [LICENSE](LICENSE). Ниже — всё стороннее, что используется проектом: библиотеки pip и npm (с транзитивными),",
          "вендорные файлы в репозитории, шрифты и значки, образы Docker, данные. Файл создаётся скриптом `tools/publish/gen_third_party.py`",
          "из установленных пакетов и `package-lock.json` (без сети); версии — как в файлах требований и lock-файлах.",
          "Лицензии указаны по метаданным пакетов; где метаданные пусты — по исходникам пакета (таблица `LICENSE_OVERRIDES` в скрипте).",
          "Копилефт: `psycopg` (LGPL-3.0) подключается как библиотека, без изменения кода; `pywebpush`/`py-vapid` и `certifi` — MPL-2.0 (файловый копилефт, правок нет).",
          ""]
    L += ["## Python (pip)", ""]
    for title, files, env in PIP_GROUPS:
        py = python_app if env == "app" or not python_bank else python_bank
        data = collect_pip(py, files)
        rows = []
        for p in data["packages"]:
            lic, ok = license_of(p)
            if not ok:
                warn.append(f"pip: лицензия {p['name']} {p['version']} не определена")
            rows.append([f"`{p['name']}`", p["version"], lic, "прямая" if p["direct"] else "транзитивная"])
        if data["missing"]:
            warn.append(f"pip ({title}): не установлены {', '.join(data['missing'][:8])} — версии не определены")
        L += [f"### {title}", "", f"Файлы требований: {', '.join(f'`{f}`' for f in files)}. Пакетов: {len(rows)}.", "",
              md_table(rows, ["Пакет", "Версия", "Лицензия", "Связь"]), ""]
        if data["missing"]:
            L += [f"Не установлены в окружении, где собирался файл: {', '.join('`' + m + '`' for m in data['missing'])}.", ""]
    L += ["## npm", ""]
    for title, lock in (("Фронтенд (`frontend/package-lock.json`)", "frontend/package-lock.json"), ("Сквозные тесты (`e2e/package-lock.json`)", "e2e/package-lock.json")):
        prod, dev, total = npm_rows(ROOT / lock)
        L += [f"### {title}", "", f"Всего пакетов: {total}; в сборку попадают {len(prod)} (остальные — инструменты разработки).", ""]
        if prod:
            L += ["**В сборке (production):**", "", md_table(prod, ["Пакет", "Версия", "Лицензия"]), ""]
        if dev:
            L += ["**Только разработка и сборка:**", "", md_table(dev, ["Пакет", "Версия", "Лицензия"]), ""]
    L += ["## Вендорные файлы в репозитории", "", md_table([list(r) for r in VENDORED], ["Что", "Лицензия", "Текст лицензии"]), ""]
    L += ["## Шрифты и значки", "", md_table([list(r) for r in FONTS_ICONS], ["Что", "Лицензия", "Как используется"]), ""]
    L += ["## Образы Docker и модели", "", md_table([list(r) for r in IMAGES], ["Что", "Лицензия", "Где используется"]), ""]
    L += ["## Данные и материалы", "", md_table([list(r) for r in DATA], ["Что", "Где", "Права и оговорки"]), ""]
    L += ["## Как обновить", "",
          "```bash",
          "# из окружения бэкенда (pip install -r backend/requirements.txt -r backend/requirements-dev.txt)",
          "python tools/publish/gen_third_party.py            # перезаписывает THIRD_PARTY.md",
          "python tools/publish/gen_third_party.py --check    # код выхода 1, если файл устарел",
          "```", ""]
    return "\n".join(L).rstrip() + "\n", warn


def check_existing() -> list[str]:
    """Пины requirements*.txt и пакеты lock-файлов должны присутствовать в THIRD_PARTY.md с теми же версиями."""
    if not OUT.exists():
        return ["THIRD_PARTY.md отсутствует"]
    text = OUT.read_text(encoding="utf-8")
    rows = set()
    for line in text.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            rows.add((canon(cells[0]), cells[1]))
    bad: list[str] = []
    for _t, files, _e in PIP_GROUPS:
        for f in files:
            for line in (ROOT / f).read_text(encoding="utf-8").splitlines():
                m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;#]+)", line.strip())
                if m and (canon(m.group(1)), m.group(2)) not in rows:
                    bad.append(f"pip: {m.group(1)}=={m.group(2)} ({f})")
    for lock in ("frontend/package-lock.json", "e2e/package-lock.json"):
        d = json.loads((ROOT / lock).read_text(encoding="utf-8"))
        for path, v in d["packages"].items():
            if path and (canon(path.split("node_modules/")[-1]), v.get("version", "?")) not in rows:
                bad.append(f"npm: {path.split('node_modules/')[-1]}@{v.get('version')} ({lock})")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-app", default=sys.executable)
    ap.add_argument("--python-bank", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        bad = check_existing()
        for b in bad[:30]:
            print("нет в THIRD_PARTY.md:", b, file=sys.stderr)
        if bad:
            print(f"THIRD_PARTY.md устарел ({len(bad)} позиций): python tools/publish/gen_third_party.py", file=sys.stderr)
            return 1
        print("THIRD_PARTY.md актуален")
        return 0
    text, warn = build(a.python_app, a.python_bank)
    for w in warn:
        print("ВНИМАНИЕ:", w, file=sys.stderr)
    OUT.write_text(text, encoding="utf-8")
    print(f"записано {OUT} ({len(text.splitlines())} строк); предупреждений: {len(warn)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
