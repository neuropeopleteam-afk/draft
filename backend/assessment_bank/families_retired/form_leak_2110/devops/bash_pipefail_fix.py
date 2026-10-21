"""devops.bash.pipefail_fix — choose_fix: `set -e` не останавливает скрипт, если падает не последняя команда конвейера.

Скрипт шага CI пишет вывод команды в журнал через `| tee файл`. Статус конвейера — статус последней команды
(tee), поэтому падение первой команды не останавливает скрипт и шаг CI «зелёный». Верное исправление —
`set -o pipefail` (вместе с `set -e`). Дистракторы — фиксированный состав из трёх почти верных:
`|| exit 1` после конвейера (проверяет статус tee), ловушка `trap 'exit 1' ERR` (ERR тоже смотрит на статус
конвейера), выход по `${PIPESTATUS[0]}` сразу после конвейера (ловит сбой, но ломает успешный путь).
Проверка — исполнение каждого варианта в bash на двух сценариях: команда падает (скрипт должен завершиться
с ненулевым кодом и не печатать сообщение об успехе) и команда успешна (код 0, сообщение и журнал есть).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.bash.pipefail_fix"

# (контекст, функция, что делает, файл журнала, сообщение об успехе, команда после)
CTX = [("ночная сборка отчётов", "build_report", "отчёт", "report.log", "отчёт готов", "gzip -k report.log"),
       ("выгрузка метрик", "export_metrics", "метрики", "export.log", "метрики выгружены", "wc -l < export.log"),
       ("резервная копия БД", "dump_db", "дамп", "dump.log", "дамп создан", "tail -n 1 dump.log"),
       ("рендер манифестов", "render_manifests", "манифесты", "render.log", "манифесты готовы",
        "grep -c часть render.log"),
       ("миграции схемы", "run_migrations", "миграции", "migrate.log", "миграции применены", "tail -n 2 migrate.log"),
       ("сборка документации", "build_docs", "страницы", "docs.log", "документация собрана", "wc -l docs.log"),
       ("синхронизация каталога", "sync_catalog", "товары", "sync.log", "каталог синхронизирован", "head -n 1 sync.log"),
       ("проверка лицензий", "scan_licenses", "пакеты", "licenses.log", "лицензии проверены",
        "sort licenses.log | uniq | wc -l")]
PREAMBLE = ["export TZ=UTC", "umask 022", 'cd "$(dirname "$0")"', "mkdir -p artifacts", "export LC_ALL=C.UTF-8"]
ERRORS = ["нет доступа к источнику", "таймаут соединения", "диск переполнен", "неверный токен"]

HARNESS = '''FAIL_MODE=1 bash step.sh > out_fail.txt 2>&1; s1=$?
rm -f {log}
FAIL_MODE=0 bash step.sh > out_ok.txt 2>&1; s2=$?
if [ "$s1" -ne 0 ] && ! grep -qF '{msg}' out_fail.txt && [ "$s2" -eq 0 ] && grep -qF '{msg}' out_ok.txt \\
   && [ -s {log} ]; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL s1=$s1 s2=$s2"
fi
'''


def _script(fn, what, log, msg, after, n_items, fix, pre, err):
    head = "set -eo pipefail" if fix == "pipefail" else "set -e"
    body = [
        "#!/usr/bin/env bash",
        head,
    ] + pre + [
        "",
        f"{fn}() {{",
        f"  for i in $(seq 1 {n_items}); do echo \"{what}: часть $i\"; done",
        f'  if [ "$FAIL_MODE" = "1" ]; then echo "ошибка: {err}" >&2; return 1; fi',
        "}",
        "",
    ]
    pipe = f"{fn} | tee {log}"
    if fix == "or_exit":
        pipe += " || exit 1"
    if fix == "trap":
        body.insert(2, "trap 'exit 1' ERR")
    body.append(pipe)
    if fix == "pipestatus":
        body.append('exit "${PIPESTATUS[0]}"')
    body += [after, f'echo "{msg}"']
    return "\n".join(body) + "\n"


FIXES = {
    "pipefail": ("Вторую строку заменить на `set -eo pipefail`", "set -eo pipefail"),
    "or_exit": ("Дописать `|| exit 1` в конец строки с конвейером", "{pipe} || exit 1"),
    "trap": ("После `set -e` добавить строку `trap 'exit 1' ERR`", "trap 'exit 1' ERR"),
    "pipestatus": ("Сразу после конвейера добавить `exit \"${PIPESTATUS[0]}\"`", 'exit "${PIPESTATUS[0]}"'),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, what, log, msg, after = rng.choice(CTX)
    n_items = rng.randint(2, 6)
    pre = rng.sample(PREAMBLE, rng.randint(0, 2))
    err = rng.choice(ERRORS)
    code = _script(fn, what, log, msg, after, n_items, None, pre, err)
    pipe = f"{fn} | tee {log}"
    harness = HARNESS.format(log=log, msg=msg)
    texts = {k: (t, c.replace("{pipe}", pipe)) for k, (t, c) in FIXES.items()}
    opts, key = make_options(rng, texts["pipefail"], [texts[k] for k in ("or_exit", "trap", "pipestatus")])
    by_text = {v: k for k, v in texts.items()}
    checks = []
    for o in opts:
        kind = by_text[(o.text, o.code)]
        checks.append(Check(name=f"option:{o.id}", runner="bash", program=harness,
                            files={"step.sh": _script(fn, what, log, msg, after, n_items, kind, pre, err)},
                            expect="pass" if o.id == key else "fail", embeds_display_code=False))
    checks.append(Check(name="original_fails", runner="bash", program=harness,
                        files={"step.sh": code}, expect="fail", embeds_display_code=False))
    stem = (f"Шаг CI «{ctx}» запускает скрипт ниже. Когда `{fn}` падает (сообщение об ошибке в stderr, код 1), "
            f"шаг всё равно «зелёный»: в журнале CI есть «{msg}». Нужно, чтобы при сбое `{fn}` скрипт завершался с "
            f"ненулевым кодом и не печатал «{msg}», а при успехе работал как раньше (вывод — в `{log}` и на экран). "
            "Какое исправление верное?")
    expl = ("Статус конвейера — статус последней команды (tee), поэтому set -e и ERR не срабатывают. "
            "set -o pipefail делает статусом конвейера ненулевой статус любой его команды. `|| exit 1` и trap ERR "
            "смотрят тот же статус tee; exit по PIPESTATUS завершает скрипт и при успехе — сообщение не печатается.")
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"n_items": n_items})
