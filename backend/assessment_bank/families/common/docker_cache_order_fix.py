"""common.docker.cache_order_fix — choose_fix: порядок COPY и установки зависимостей в Dockerfile.

Dockerfile копирует весь контекст (`COPY . .`) и только потом ставит зависимости: любое изменение кода
инвалидирует слой COPY, а с ним и долгую установку. Нужно выбрать исправление. Состав вариантов фиксирован:
  * верный — сначала COPY файла зависимостей, установка, затем COPY остального кода;
  * install_before_copy — установка до любого COPY: файла зависимостей в образе ещё нет, сборка падает;
  * req_then_all_then_run — файл зависимостей скопирован первым, но `COPY . .` всё равно стоит до RUN:
    при изменении кода установка выполняется заново;
  * dockerignore_only — Dockerfile без изменений, добавлен .dockerignore (.git, кэш): контекст меньше,
    но изменённый файл кода всё так же инвалидирует `COPY . .` и установку.
Проверка исполнением модели сборки на Python: сборка, затем изменение файла кода и повторная сборка;
верный вариант собирается и берёт установку из кэша, остальные падают или ставят зависимости заново.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.docker.cache_order_fix"

# (контекст, базовый образ, файл зависимостей, доп. файл зависимостей или None, установка, файл кода, запуск)
STACKS = [("API на Python", "python:3.12-slim", "requirements.txt", None,
           "RUN pip install --no-cache-dir -r requirements.txt", "app.py", 'CMD ["python", "app.py"]'),
          ("воркер на Python", "python:3.11-slim", "requirements.txt", None,
           "RUN pip install -r requirements.txt", "worker.py", 'CMD ["python", "worker.py"]'),
          ("сервис на Node.js", "node:22-alpine", "package.json", "package-lock.json",
           "RUN npm ci --omit=dev", "server.js", 'CMD ["node", "server.js"]'),
          ("фронтенд на Node.js", "node:20-alpine", "package.json", "package-lock.json",
           "RUN npm ci", "index.js", 'CMD ["node", "index.js"]')]
INSTALL_MIN = [3, 4, 5, 6, 8]

MODEL = '''DOCKERFILE = {dockerfile!r}
IGNORE = {ignore!r}
DEP_FILES = {dep_files!r}
CODE_FILE = {code_file!r}
FILES = DEP_FILES + [CODE_FILE, "README.md", ".git/HEAD"]


def in_context(path):
    return not any(path == p or path.startswith(p.rstrip("/") + "/") for p in IGNORE)


def build(changed, cache):
    """Сборка: возвращает (успех, выполнялась ли установка заново). cache — множество ключей слоёв."""
    image, invalid, ran_install = set(), False, False
    for i, line in enumerate(DOCKERFILE.splitlines(), 1):
        instr, _, rest = line.partition(" ")
        if instr == "COPY":
            srcs = rest.split()[:-1]
            got = [p for p in FILES if in_context(p) and ("." in srcs or p in srcs)]
            if "." not in srcs and len(got) < len(srcs):
                return False, ran_install  # нет такого файла в контексте
            if any(p in changed for p in got):
                invalid = True
            image.update(got)
            key = (i, line, tuple(sorted(got)))
        elif instr == "RUN":
            if not all(d in image for d in DEP_FILES):
                return False, ran_install  # файла зависимостей в образе ещё нет
            key = (i, line)
        else:
            continue
        if invalid or key not in cache:
            invalid = True
            cache.add(key)
            if instr == "RUN":
                ran_install = True
    return True, ran_install


cache = set()
ok1, _ = build(set(), cache)
ok2, reinstalled = build({{CODE_FILE}}, cache)
print("RESULT: PASS" if ok1 and ok2 and not reinstalled else "RESULT: FAIL")
'''


def _dockerfile(base, dep_files, install, code_file, cmd, order, extra_env, expose, workdir):
    deps = " ".join(dep_files)
    copy_deps = f"COPY {deps} ./" if len(dep_files) > 1 else f"COPY {dep_files[0]} ."
    head = [f"FROM {base}", f"WORKDIR {workdir}"]
    if extra_env:
        head.append(extra_env)
    body = {"buggy": ["COPY . .", install],
            "correct": [copy_deps, install, "COPY . ."],
            "install_before_copy": [install, "COPY . ."],
            "req_then_all_then_run": [copy_deps, "COPY . .", install]}[order]
    tail = ([expose] if expose else []) + [cmd]
    return "\n".join(head + body + tail) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, base, dep, lock, install, code_file, cmd = rng.choice(STACKS)
    dep_files = [dep] + ([lock] if lock else [])
    minutes = rng.choice(INSTALL_MIN)
    extra_env = rng.choice([None, "ENV PYTHONUNBUFFERED=1" if "python" in base else "ENV NODE_ENV=production"])
    expose = rng.choice([None, f"EXPOSE {rng.choice([8000, 8080, 3000])}"])
    workdir = rng.choice(["/app", "/srv/app", "/usr/src/app", "/opt/service"])
    mk = lambda order: _dockerfile(base, dep_files, install, code_file, cmd, order, extra_env, expose, workdir)
    buggy = mk("buggy")
    srcs = {"correct": mk("correct"), "install_before_copy": mk("install_before_copy"),
            "req_then_all_then_run": mk("req_then_all_then_run"), "dockerignore_only": buggy}
    ignores = {n: [] for n in srcs}
    ignores["dockerignore_only"] = [".git/", "__pycache__/" if "python" in base else "node_modules/"]
    labels = {"correct": f"Сначала COPY {' и '.join(dep_files)}, затем установка, затем COPY . .",
              "install_before_copy": "Установка зависимостей до любого COPY, затем COPY . .",
              "req_then_all_then_run": f"COPY {' и '.join(dep_files)}, затем COPY . ., затем установка",
              "dockerignore_only": "Dockerfile без изменений, добавить .dockerignore"}
    show = {n: s for n, s in srcs.items()}
    show["dockerignore_only"] = ("# .dockerignore\n" + "\n".join(ignores["dockerignore_only"]) +
                                 "\n\n# Dockerfile — без изменений\n" + buggy)
    names = ["correct", "install_before_copy", "req_then_all_then_run", "dockerignore_only"]
    opts, key = make_options(rng, (labels["correct"], show["correct"]),
                             [(labels[n], show[n]) for n in names[1:]])
    by_text = {o.text: o.id for o in opts}
    checks = [Check(name="original_fails", runner="python", expect="fail", embeds_display_code=False,
                    program=MODEL.format(dockerfile=buggy, ignore=[], dep_files=dep_files, code_file=code_file))]
    for n in names:
        checks.append(Check(name=f"option:{by_text[labels[n]]}", runner="python", embeds_display_code=False,
                            expect="pass" if n == "correct" else "fail",
                            program=MODEL.format(dockerfile=srcs[n], ignore=ignores[n], dep_files=dep_files,
                                                 code_file=code_file)))
    stem = (f"Docker, {ctx}. Установка зависимостей (`{install.split(' ', 1)[1]}`) занимает около {minutes} мин, и "
            f"она выполняется заново при каждой сборке, даже если изменился только `{code_file}`. Базовый образ и "
            f"файл зависимостей не менялись. Какой вариант Dockerfile устраняет проблему: при изменении кода слой "
            f"установки берётся из кэша, а сборка проходит успешно?")
    why = (f"Кэш слоёв инвалидируется с первой инструкции, чьи входные данные изменились, и далее до конца. "
           f"Поэтому файл зависимостей копируется отдельно и первым, установка идёт сразу за ним, а код — "
           f"последним: изменение `{code_file}` сбрасывает только `COPY . .`. Установка до любого COPY падает "
           f"(файла зависимостей в образе нет); `COPY . .` до RUN всё равно инвалидирует установку; "
           f".dockerignore уменьшает контекст, но изменённый файл кода в нём остаётся.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="deps_after_full_copy",
                         display_code_note="Исполняется модель сборки Docker (кэш COPY по содержимому файлов, RUN по "
                                           "тексту команды и предыдущим слоям); Dockerfile передаётся строкой.",
                         params={"install_minutes": minutes})
