"""common.docker.layer_cache_output — predict_output: кэш слоёв при повторной сборке образа.

Показан Dockerfile и список файлов контекста (с .dockerignore). Образ уже собран; затем изменены один-два
файла и сборка запущена снова. Вопрос: какие инструкции RUN и COPY выполнятся заново, а не возьмутся из
кэша. Правила кэша Docker: COPY/ADD инвалидируется, если изменилась контрольная сумма копируемых файлов
(файлы из .dockerignore в контекст не попадают); RUN кэшируется по тексту команды — само по себе время
(«apt-get update неделю назад») кэш не сбрасывает; с первой инвалидированной инструкции все последующие
выполняются заново. Один подтип; варьируются стек (pip/npm), набор файлов, место изменения:
файл из первого COPY (переустановка зависимостей), из второго/третьего COPY, файл из .dockerignore или
вовсе не копируемый (всё из кэша). Ключ проверяется исполнением модели кэша на Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.docker.layer_cache_output"

# (контекст, базовый образ, файл зависимостей, команда установки, каталог кода, запуск)
STACKS = [("сервис на Python", "python:3.12-slim", "requirements.txt",
           "RUN pip install --no-cache-dir -r requirements.txt", "src", 'CMD ["python", "-m", "src.main"]'),
          ("сервис на Node.js", "node:22-alpine", "package.json",
           "RUN npm ci --omit=dev", "lib", 'CMD ["node", "lib/server.js"]'),
          ("бот на Python", "python:3.12-slim", "requirements.txt",
           "RUN pip install -r requirements.txt", "bot", 'CMD ["python", "-m", "bot"]'),
          ("API на Node.js", "node:20-alpine", "package.json",
           "RUN npm install --production", "app", 'CMD ["node", "app/index.js"]')]
CONF_DIRS = ["config", "conf", "settings", "etc"]
CONF_FILES = ["app.yaml", "prod.toml", "logging.ini", "limits.json"]
IGNORED = [("tests/", "tests/test_api.py"), ("docs/", "docs/guide.md"), (".git/", ".git/HEAD"),
           ("*.md", "README.md"), ("notebooks/", "notebooks/explore.ipynb")]
APT = ["RUN apt-get update && apt-get install -y --no-install-recommends curl",
       "RUN apk add --no-cache curl", "RUN apt-get update && apt-get install -y git"]

MODEL = '''import fnmatch

DOCKERFILE = {dockerfile!r}
FILES = {files!r}
IGNORE = {ignore!r}
CHANGED = {changed!r}


def in_context(path):
    for pat in IGNORE:
        if pat.endswith("/") and path.startswith(pat):
            return False
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path.split("/")[-1], pat):
            return False
    return True


def copied(src, path):
    src = src.rstrip("/")
    if src == ".":
        return True
    return path == src or path.startswith(src + "/")


rebuilt, invalid = [], False
for i, line in enumerate(DOCKERFILE.splitlines(), 1):
    instr, _, rest = line.partition(" ")
    if instr == "COPY":
        src = rest.split()[0]
        touched = [p for p in CHANGED if in_context(p) and copied(src, p)]
        if touched:
            invalid = True  # контрольная сумма копируемых файлов изменилась
        if invalid:
            rebuilt.append(i)
    elif instr == "RUN":
        if invalid:  # RUN кэшируется по тексту команды; заново — только после инвалидации выше
            rebuilt.append(i)
print(",".join(map(str, rebuilt)) if rebuilt else "нет")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, base, dep_file, install, code_dir, cmd = rng.choice(STACKS)
    conf_dir, conf_file = rng.choice(CONF_DIRS), rng.choice(CONF_FILES)
    ign_pat, ign_file = rng.choice(IGNORED)
    code_files = [f"{code_dir}/{n}" for n in rng.sample(["main.py", "handlers.py", "models.py", "utils.py"], 2)] \
        if "python" in base else [f"{code_dir}/{n}" for n in rng.sample(["server.js", "routes.js", "db.js", "util.js"], 2)]
    files = [dep_file] + code_files + [f"{conf_dir}/{conf_file}", ign_file, ".dockerignore", "Dockerfile"]
    ignore = [ign_pat, "Dockerfile", ".dockerignore"]
    apt = rng.choice(APT[1:2] if "alpine" in base else [APT[0], APT[2]])
    use_all = rng.random() < 0.4  # последний COPY — всего контекста
    lines = [f"FROM {base}", "WORKDIR /app", apt, f"COPY {dep_file} .", install]
    if rng.random() < 0.5:
        lines.append(f"ENV APP_ENV={rng.choice(['prod', 'staging', 'production'])}")
    if use_all:
        lines.append("COPY . .")
    else:
        lines.append(f"COPY {code_dir}/ ./{code_dir}/")
        lines.append(f"COPY {conf_dir}/{conf_file} ./{conf_dir}/")
    if rng.random() < 0.5:
        lines.append(f"EXPOSE {rng.choice([8000, 8080, 3000, 5000])}")
    lines.append(cmd)
    dockerfile = "\n".join(lines) + "\n"
    # что изменилось: зависимости / код / конфиг / игнорируемый файл; иногда вдобавок игнорируемый файл
    kind = rng.choice(["deps", "code", "code", "conf", "ignored", "ignored"])
    changed = {"deps": [dep_file], "code": [rng.choice(code_files)], "conf": [f"{conf_dir}/{conf_file}"],
               "ignored": [ign_file]}[kind]
    extra_ignored = kind != "ignored" and rng.random() < 0.3
    if extra_ignored:
        changed = changed + [ign_file]
    changed = sorted(set(changed))
    # эталон — независимо от модели: первая инвалидированная COPY и всё RUN/COPY ниже
    def _first_copy(pred) -> int | None:
        return next((i for i, l in enumerate(lines, 1) if l.startswith("COPY ") and pred(l)), None)
    if kind == "deps":
        first = _first_copy(lambda l: dep_file in l)
    elif kind == "code":
        first = _first_copy(lambda l: l == "COPY . ." or f" {code_dir}/" in l)
    elif kind == "conf":
        first = _first_copy(lambda l: l == "COPY . ." or f" {conf_dir}/" in l)
    else:
        first = None
    rebuilt = [i for i, l in enumerate(lines, 1) if first is not None and i >= first
               and l.split(" ")[0] in ("RUN", "COPY")]
    out = ",".join(map(str, rebuilt)) if rebuilt else "нет"
    program = MODEL.format(dockerfile=dockerfile, files=files, ignore=ignore, changed=changed)
    files_txt = "\n".join(f"  {f}" for f in files if f not in (".dockerignore", "Dockerfile"))
    changed_txt = ", ".join(f"`{c}`" for c in changed)
    stem = (f"Docker, {ctx}. Dockerfile (строки пронумерованы по инструкциям) и файлы контекста сборки:\n\n"
            f"{files_txt}\n\n.dockerignore:\n  {ign_pat}\n\nОбраз собран командой `docker build .`; базовый образ "
            f"не менялся. Затем разработчик изменил {changed_txt} и запустил сборку снова. Какие инструкции "
            f"RUN и COPY будут выполнены заново, а не взяты из кэша слоёв? Запишите номера строк через запятую "
            f"по возрастанию (например `4,5`); если все слои взяты из кэша — напишите `нет`.")
    why = {"deps": "изменился файл зависимостей из первого COPY: его слой и все последующие (установка, "
                   "остальные COPY) собираются заново",
           "code": "изменён файл кода: COPY с ним и всё ниже — заново, а установка зависимостей выше остаётся "
                   "в кэше (файл зависимостей не менялся)",
           "conf": "изменён файл конфигурации: заново выполняется только COPY, в который он входит, и инструкции "
                   "ниже; слои выше — из кэша",
           "ignored": "изменённый файл исключён .dockerignore или не входит ни в один COPY — контрольные суммы "
                      "копируемых файлов те же, все слои из кэша; RUN apt-get/apk тоже кэшируется по тексту "
                      "команды, время его не сбрасывает"}[kind]
    if extra_ignored:
        why += "; второй изменённый файл исключён .dockerignore и на кэш не влияет"
    ak = AnswerKey(kind="output", value=out, explanation=f"Ответ `{out}`: {why}.")
    checks = [Check(name="cache_model", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=out, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=dockerfile, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Исполняется модель кэша слоёв Docker (COPY — по контрольной сумме "
                                           "файлов с учётом .dockerignore, RUN — по тексту команды, с первой "
                                           "инвалидации всё ниже заново); Dockerfile передаётся модели строкой.",
                         params={"kind": kind, "changed": changed, "use_all": use_all})
