"""common.git.t21_status_short_output — predict_output (набор t21, порог Стажёр): коды ``git status --short``
после коммита, правок и git add части файлов.

Скрипт в новом репозитории создаёт файлы, коммитит часть, затем правит и добавляет в индекс по-разному и печатает
``git status --short | tr ' ' '_'`` (пробелы заменены на «_», чтобы столбцы XY были видны и ответ не терял
пробелы при сравнении). Коды: «??» — неотслеживаемый, « M» — изменён и не добавлен, «M » — изменён и добавлен,
«A » — новый и добавлен, «AM» — новый, добавлен и снова изменён; закоммиченный и нетронутый файл не печатается.
Порядок: изменения отслеживаемых файлов по имени, затем неотслеживаемые (имена в вариантах подобраны так, что
неотслеживаемые и по алфавиту идут последними). Ловушки: какой из столбцов X/Y занят, нетронутый файл не
показывается, AM после повторной правки. Ключ — независимая модель трёх состояний файла (HEAD, индекс, рабочая
копия) в генераторе; проверка — исполнение показанного скрипта раннером git в песочнице (служебные файлы песочницы
скрыты .gitignore из files — кандидат его не видит).
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import STEM_TAIL
from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.git.t21_status_short_output"

CTX = [("веб-сервис на Python", ["api.py", "app.py", "auth.py", "cache.py", "db.py", "jobs.py", "main.py",
                                 "models.py", "routes.py", "tasks.py", "utils.py", "views.py"]),
       ("сайт-визитка", ["about.html", "app.js", "contacts.html", "index.html", "main.css", "menu.js",
                         "reset.css", "robots.txt", "sitemap.xml", "theme.css"]),
       ("скрипты деплоя", ["backup.sh", "build.sh", "clean.sh", "deploy.sh", "env.conf", "hosts.ini",
                           "nginx.conf", "release.sh", "rollback.sh", "setup.sh"]),
       ("документация проекта", ["api.md", "changelog.md", "faq.md", "guide.md", "index.md", "install.md",
                                 "license.md", "readme.md", "roadmap.md", "usage.md"])]
GIT_IGNORE = ".bank*\n.gitignore\n"
KINDS = [" M", "M ", "A ", "AM", "??", "clean"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    for _ in range(3000):
        kinds = [rng.choice([" M", "M "]), rng.choice(["A ", "AM"]), "??"]
        extra = rng.choice([" M", "M ", "A ", "AM", "clean", "??", None])
        if extra:
            kinds.append(extra)
        if len(set(k for k in kinds if k != "clean")) < 3:
            continue
        names = rng.sample(pool, len(kinds))
        tracked = [n for n, k in zip(names, kinds) if k != "??"]
        untracked = [n for n, k in zip(names, kinds) if k == "??"]
        if max(tracked) >= min(untracked):
            continue                      # неотслеживаемые и по алфавиту идут последними
        break
    else:
        raise RuntimeError("t21_status_short: не собрались файлы")
    files = dict(zip(names, kinds))
    committed = sorted(n for n, k in files.items() if k in (" M", "M ", "clean"))
    created_new = [n for n, k in files.items() if k in ("A ", "AM")]
    touch_untracked = [n for n, k in files.items() if k == "??" and rng.random() < 0.5]
    first = committed + touch_untracked
    rng.shuffle(first)
    lines = [f"touch {' '.join(first)}", f"git add {' '.join(committed)} && git commit -q -m init"]
    ops = []
    for n, k in files.items():
        if k == " M":
            ops.append(f"echo fix >> {n}")
        elif k == "M ":
            ops.append(f"echo fix >> {n} && git add {n}")
        elif k == "A ":
            ops.append(f"echo new > {n} && git add {n}")
        elif k == "AM":
            ops.append(f"echo new > {n} && git add {n} && echo more >> {n}")
        elif k == "??" and n not in touch_untracked:
            ops.append(f"echo draft > {n}")
    rng.shuffle(ops)
    lines += ops
    lines.append("git status --short | tr ' ' '_'")
    code = "\n".join(lines)
    # модель: X — индекс против HEAD, Y — рабочая копия против индекса; затем неотслеживаемые
    status = []
    for n in sorted(files):
        k = files[n]
        if k in ("clean", "??"):
            continue
        status.append(k.replace(" ", "_") + "_" + n)
    status += [f"??_{n}" for n in sorted(untracked)]
    out = "\n".join(status)
    meaning = {" M": "изменён после коммита, но не добавлен — « M» (X пуст, Y = M)",
               "M ": "изменён и добавлен — «M » (X = M, Y пуст)",
               "A ": "новый и добавлен — «A »",
               "AM": "новый, добавлен и снова изменён — «AM»",
               "??": "не отслеживается — «??»",
               "clean": "закоммичен и не менялся — в выводе его нет"}
    expl = ("Формат --short: два столбца XY (X — индекс относительно коммита, Y — рабочая копия относительно "
            "индекса), пробел и имя; tr заменяет все пробелы на «_». "
            + "; ".join(f"{n}: {meaning[files[n]]}" for n in sorted(files))
            + ". Сначала идут изменения отслеживаемых файлов по имени, затем неотслеживаемые. Ловушка — перепутать "
              "столбцы « M» и «M » или ждать в выводе нетронутый закоммиченный файл.")
    stem = (f"Репозиторий «{ctx}»: скрипт выполняется в новом пустом репозитории (`git init -b main` уже сделан, "
            f"коммитов нет, автор настроен) и печатает краткий статус, заменяя пробелы на «_».\n\n"
            + STEM_TAIL["bash"])
    ak = AnswerKey(kind="output", value=out, explanation=expl)
    checks = [Check(name="stdout", runner="git", program=code, files={".gitignore": GIT_IGNORE},
                    expect="stdout_equals", expected_stdout=out, embeds_display_code=True)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="bash",
                         params={"files": files, "touch_untracked": touch_untracked})
