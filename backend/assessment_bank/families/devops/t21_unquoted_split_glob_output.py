"""devops.bash.t21_unquoted_split_glob_output — predict_output (набор t21, порог Middle): кавычки, разбиение на
слова и подстановка шаблонов при раскрытии переменных в bash.

Скрипт очистки берёт из переменных окружения шаблон файлов и строку флагов. Без кавычек `$VAR` проходит разбиение
на слова и подстановку имён файлов: `for f in $KEEP` с `KEEP="*.log"` перебирает подходящие файлы каталога
(по алфавиту), а `"$KEEP"` остаётся одним словом `*.log`; кавычки ВНУТРИ значения переменной — обычные символы,
поэтому `set -- $FLAGS` режет `'nightly run'` на `'nightly` и `run'`. Состав каталога дан в условии. Ключ —
независимая модель раскрытия в генераторе; проверка — исполнение показанного скрипта в bash с теми же файлами.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.bash.t21_unquoted_split_glob_output"

CTX = ["очистка логов биллинга", "уборка артефактов каталога", "очистка журналов шлюза", "уборка логов поиска",
       "очистка выгрузок личного кабинета", "уборка журналов CRM", "очистка логов рассылок"]
PATTERNS = [("*.log", ["api.log", "db.log", "jobs.log", "mail.log", "web.log"], ["api.txt", "notes.md", "db.gz"]),
            ("*.gz", ["api.gz", "cron.gz", "db.gz", "web.gz"], ["api.log", "readme", "run.sh"]),
            ("app-*", ["app-1", "app-2", "app-old", "app-tmp"], ["apps", "backup-1", "cfg"]),
            ("*.tmp", ["a.tmp", "build.tmp", "core.tmp", "x.tmp"], ["a.txt", "tmp", "build.log"])]
FLAG_SETS = [("-n {n} --label '{a} {b}'", ["-n", "{n}", "--label", "'{a}", "{b}'"]),
             ("--keep {n} --note '{a} {b}' -v", ["--keep", "{n}", "--note", "'{a}", "{b}'", "-v"]),
             ("--days={n} --tag '{a} {b}'", ["--days={n}", "--tag", "'{a}", "{b}'"])]
WORDS = [("nightly", "run"), ("blue", "green"), ("hot", "fix"), ("dry", "mode"), ("week", "end")]
VARS = [("KEEP", "FLAGS"), ("PATTERN", "OPTS"), ("MASK", "ARGS")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    pat, good, bad = rng.choice(PATTERNS)
    kv, fv = rng.choice(VARS)
    present = sorted(rng.sample(good, rng.randint(2, 3)) + rng.sample(bad, rng.randint(1, 2)))
    matched = sorted(f for f in present if fnmatchcase(f, pat))
    tpl, words_tpl = rng.choice(FLAG_SETS)
    a, b = rng.choice(WORDS)
    n = rng.randint(2, 14)
    flags = tpl.format(n=n, a=a, b=b)
    words = [w.format(n=n, a=a, b=b) for w in words_tpl]
    lab1, lab2 = rng.choice([("keep", "literal"), ("rm", "as-is"), ("drop", "quoted")])
    lines = [f'{kv}="{pat}"',
             f'{fv}="{flags}"',
             f'for f in ${kv}; do echo "{lab1} $f"; done',
             f'for f in "${kv}"; do echo "{lab2} $f"; done',
             f"set -- ${fv}",
             'echo "args=$#"',
             "printf '[%s]' \"$@\"; echo"]
    code = "\n".join(lines)
    outs = [f"{lab1} {f}" for f in matched] + [f"{lab2} {pat}", f"args={len(words)}", "".join(f"[{w}]" for w in words)]
    out = "\n".join(outs)
    expl = (f"Без кавычек ${kv} проходит подстановку имён файлов: «{pat}» раскрывается в подходящие файлы каталога по "
            f"алфавиту — {', '.join(matched)}. В кавычках \"${kv}\" — одно слово «{pat}» без подстановки. Кавычки "
            f"внутри значения ${fv} — обычные символы, разбиение идёт по пробелам: {len(words)} "
            f"{plural(len(words), 'слово', 'слова', 'слов')} — "
            + " ".join(f"[{w}]" for w in words) + " (printf повторяет формат для каждого аргумента, echo в конце "
            "переводит строку). Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = (f"Скрипт ({ctx}) берёт шаблон файлов и флаги из переменных. В текущем каталоге лежат файлы: "
            + ", ".join(f"`{f}`" for f in present) + " — и больше ничего.")
    files = {f: "x\n" for f in present}
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pattern": pat, "present": present, "flags": flags}, language="bash", files=files)
