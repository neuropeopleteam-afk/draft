"""common.linux.relative_path_output — predict_output: относительный путь с `..` и `.` от заданного каталога.

Лёгкое семейство у порога Junior (грейд «Стажёр»): дано дерево каталогов проекта, стартовый каталог и
относительный путь из 2–3 сегментов-переходов (`..`, `./x`, `../..`); `realpath -m` печатает результат
(каталоги в песочнице не создаются — путь нормализуется символически). Единственная ловушка — `..`
поднимает на уровень от текущего места, а не от корня проекта. Исполняется bash; ключ — независимая
нормализация пути в генераторе.
"""
from __future__ import annotations

import posixpath

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.linux.relative_path_output"

TREES = [("деплой", "/srv/app", ["releases/v1", "releases/v2", "shared/logs", "shared/config", "current"]),
         ("проект", "/home/dev/project", ["src/api", "src/web", "tests/unit", "tests/e2e", "docs"]),
         ("данные", "/data/warehouse", ["raw/2026", "raw/2025", "clean/daily", "clean/monthly", "tmp"]),
         ("сборка", "/opt/build", ["out/linux", "out/mac", "cache/pip", "cache/npm", "scripts"]),
         ("сайт", "/var/www/site", ["static/css", "static/js", "templates/mail", "templates/pages", "media"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, root, dirs = rng.choice(TREES)
    dirs = list(dirs)
    rng.shuffle(dirs)
    sub = [d for d in dirs if "/" in d]
    start = rng.choice(sub)
    while True:
        cwd = posixpath.join(root, start)
        steps = []
        n_steps = rng.randint(2, 3)
        ok = True
        for i in range(n_steps):
            if i == n_steps - 1 and rng.random() < 0.5:  # последний шаг иногда только вверх
                rel = rng.choice(["..", "../..", "../."])
            else:
                target = rng.choice(dirs)
                rel = posixpath.relpath(posixpath.join(root, target), cwd)
                if rel == ".":
                    rel = "./"
                elif rng.random() < 0.4 and not rel.startswith(".."):
                    rel = "./" + rel
            steps.append(f"cd {rel}")
            cwd = posixpath.normpath(posixpath.join(cwd, rel))
            if not (cwd == root or cwd.startswith(root + "/")):
                ok = False  # выше корня проекта — такой вариант не берём
                break
        if ok and cwd != posixpath.join(root, start) and any(".." in st for st in steps):
            break
    expected = cwd
    rel_chain = "/".join(st[3:] for st in steps)
    base_var = rng.choice(["BASE", "START", "CWD0", "DIR"])
    code = f'{base_var}={posixpath.join(root, start)}\nrealpath -m "${base_var}/{rel_chain}"\n'
    stem = (f"Bash ({ctx}). Дерево каталогов проекта `{root}`: {', '.join(sorted(dirs))}. "
            f"`realpath -m` печатает нормализованный абсолютный путь (каталоги могут не существовать). "
            f"Что напечатает скрипт? Запишите абсолютный путь без завершающего слэша.")
    why = (f"Начало — `{posixpath.join(root, start)}`. Сегменты разбираются слева направо: `..` поднимает на один "
           f"уровень от текущего места, `.` ничего не меняет, имя — спуск в подкаталог. Последовательно: " +
           " → ".join(_trace(posixpath.join(root, start), steps)) + ".")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    checks = [Check(name="pwd", runner="bash", program=code, expect="stdout_equals", expected_stdout=expected)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"steps": steps, "start": start})


def _trace(cwd: str, steps: list[str]) -> list[str]:
    out = []
    for s in steps:
        cwd = posixpath.normpath(posixpath.join(cwd, s[3:]))
        out.append(f"`{cwd}`")
    return out
