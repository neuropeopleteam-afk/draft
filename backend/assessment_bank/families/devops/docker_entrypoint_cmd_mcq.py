"""devops.docker.entrypoint_cmd_mcq — mcq_concept: какой процесс запустит `docker run` при ENTRYPOINT/CMD.

Правила (документация Dockerfile reference, «Understand how CMD and ENTRYPOINT interact»): exec-форма
ENTRYPOINT + CMD → аргументы CMD дописываются к ENTRYPOINT; аргументы `docker run образ А…` заменяют CMD
целиком; shell-форма ENTRYPOINT запускается как `/bin/sh -c "…"`, CMD и аргументы run игнорируются; без
ENTRYPOINT аргументы run заменяют CMD полностью; `--entrypoint X` заменяет ENTRYPOINT и сбрасывает CMD
образа. Подтип один: аргументы переданы в `docker run`. Дистракторы — фиксированный порядок типовых
ошибок: аргументы дописаны после CMD, аргументы проигнорированы, аргументы заменили ENTRYPOINT, CMD образа
сохранён при --entrypoint. Ключ — исполнение модели правил в песочнице Python над показанными строками.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import program

FAMILY_ID = "devops.docker.entrypoint_cmd_mcq"

APPS = [("python:3.12-slim", ["python", "app.py"], ["--port", "8000"], ["--port", "9000"], "API на Flask"),
        ("node:20-alpine", ["node", "server.js"], ["--env", "prod"], ["--env", "stage"], "сервер на Node.js"),
        ("eclipse-temurin:21-jre", ["java", "-jar", "app.jar"], ["--spring.profiles.active=prod"],
         ["--spring.profiles.active=test"], "сервис на Spring"),
        ("python:3.12-slim", ["celery", "-A", "tasks", "worker"], ["--concurrency", "4"], ["--concurrency", "1"],
         "воркер Celery"),
        ("golang:1.22", ["/app/bin/indexer"], ["--batch", "500"], ["--batch", "50"], "индексатор")]
SHAPES = ["exec_exec", "shell_entry", "cmd_only", "override_entry"]

MODEL = '''
import json, shlex

def instr(name):
    for line in DOCKERFILE.splitlines():
        if line.startswith(name + " "):
            arg = line[len(name) + 1:].strip()
            return json.loads(arg) if arg.startswith("[") else ["/bin/sh", "-c", arg]
    return None

entry, cmd = instr("ENTRYPOINT"), instr("CMD")
words = shlex.split(RUN)[2:]
if words[0] == "--entrypoint":
    entry, cmd, words = [words[1]], None, words[2:]
args = words[1:]                      # после имени образа
if entry and entry[:2] == ["/bin/sh", "-c"]:
    argv = entry                      # shell-форма: CMD и аргументы не передаются
elif entry:
    argv = entry + (args if args else (cmd or []))
else:
    argv = args if args else cmd
print(json.dumps(argv, ensure_ascii=False))
'''


def _fmt(argv):
    return json.dumps(argv, ensure_ascii=False)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    base, entry, cmd, args, what = rng.choice(APPS)
    shape = rng.choice(SHAPES)
    img = f"registry.local/{what.split()[-1].lower().strip('.')}:{rng.randint(1, 9)}.{rng.randint(0, 20)}"
    lines = [f"FROM {base}", "WORKDIR /app", "COPY . ."]
    run_args = list(args)
    if shape == "exec_exec":
        lines += [f"ENTRYPOINT {_fmt(entry)}", f"CMD {_fmt(cmd)}"]
        run = f"docker run {img} {' '.join(run_args)}"
        right = entry + run_args
        wrong = [entry + cmd + run_args, entry + cmd, run_args]
    elif shape == "shell_entry":
        lines += [f"ENTRYPOINT {' '.join(entry)}", f"CMD {_fmt(cmd)}"]
        run = f"docker run {img} {' '.join(run_args)}"
        sh = ["/bin/sh", "-c", " ".join(entry)]
        right = sh
        wrong = [entry + run_args, sh[:2] + [" ".join(entry + run_args)], entry + cmd]
    elif shape == "cmd_only":
        full = entry + cmd
        lines += [f"CMD {_fmt(full)}"]
        run = f"docker run {img} {' '.join(run_args)}"
        right = run_args
        wrong = [full + run_args, full, entry + run_args]
    else:
        lines += [f"ENTRYPOINT {_fmt(entry)}", f"CMD {_fmt(cmd)}"]
        run_args = ["-c", "env | sort"]
        run = f"docker run --entrypoint sh {img} -c 'env | sort'"
        right = ["sh", "-c", "env | sort"]
        wrong = [["sh", "-c", "env | sort"] + cmd, entry + ["sh", "-c", "env | sort"], ["sh"] + cmd]
    code = "\n".join(lines)
    correct = _fmt(right)
    wtexts = []
    for w in wrong:
        t = _fmt(w)
        if t != correct and t not in wtexts:
            wtexts.append(t)
    assert len(wtexts) == 3, (shape, wtexts)
    opts, key = make_options(rng, (correct, None), [(t, None) for t in wtexts])
    stem = (f"Образ «{what}» собран по Dockerfile ниже. Контейнер запускают командой `{run}`. Какой процесс "
            "(argv) будет запущен в контейнере?")
    expl = {"exec_exec": "Аргументы docker run заменяют CMD и дописываются к exec-форме ENTRYPOINT.",
            "shell_entry": "Shell-форма ENTRYPOINT запускается через /bin/sh -c; CMD и аргументы docker run ей не "
                           "передаются.",
            "cmd_only": "Без ENTRYPOINT аргументы docker run полностью заменяют CMD.",
            "override_entry": "--entrypoint заменяет ENTRYPOINT и сбрасывает CMD образа; аргументы после образа "
                              "передаются новой точке входа."}[shape] + f" Итог: {correct}."
    prog = program(MODEL, DOCKERFILE=code, RUN=run)
    checks = [Check(name="docker_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=correct)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=what,
                         verification="execution", checks=checks, language="dockerfile",
                         display_code_note="Исполняется модель правил ENTRYPOINT/CMD над показанными строками",
                         params={"shape": shape})
