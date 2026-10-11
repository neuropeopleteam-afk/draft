"""devops.bash.redirect_order_output — predict_output: порядок перенаправлений stdout/stderr в bash.

Функция `step` печатает строку в stdout и строку в stderr; скрипт вызывает её 3–4 раза с разными перенаправлениями
и в конце печатает файл журнала. Правила (руководство bash, раздел REDIRECTION): перенаправления применяются слева
направо; `2>&1` копирует ТЕКУЩИЙ дескриптор 1, поэтому `> f 2>&1` отправляет оба потока в файл, а `2>&1 > f` —
stderr в терминал, stdout в файл; `>` обрезает файл, `>>` дописывает. В каждом варианте есть `2>&1 > f`
(ловушка). Терминал показывает оба потока. Ключ — независимая модель генератора; проверка — исполнение скрипта в
bash-песочнице (stderr скрипта сведён в stdout строкой `exec 2>&1` до показанного кода).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.bash.redirect_order_output"

CTX = [("миграция базы", "migrate.log"), ("сборка образа", "build.log"), ("резервное копирование", "backup.log"),
       ("проверка конфигурации", "check.log"), ("выкладка фронтенда", "deploy.log"), ("очистка кэша", "cache.log")]
STEPS = ["lint", "test", "pack", "push", "sync", "warm", "scan", "copy"]
FORMS = {
    "both_to_file": "{c} > {f} 2>&1",
    "err_to_tty": "{c} 2>&1 > {f}",
    "drop_err": "{c} 2> /dev/null",
    "drop_out": "{c} > /dev/null",
    "append_out": "{c} >> {f}",
}


def _model(seq, log):
    """(терминал, содержимое файла) по порядку вызовов."""
    tty, file_ = [], None
    for form, name in seq:
        o, e = f"ok {name}", f"warn {name}"
        if form == "both_to_file":
            file_ = [o, e]
        elif form == "err_to_tty":
            tty.append(e)
            file_ = [o]
        elif form == "drop_err":
            tty.append(o)
        elif form == "drop_out":
            tty.append(e)
        elif form == "append_out":
            tty.append(e)
            file_ = (file_ or []) + [o]
    return tty + (file_ or [])


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, log = rng.choice(CTX)
    for _ in range(500):
        n = rng.randint(3, 4)
        forms = ["err_to_tty"] + rng.sample([f for f in FORMS if f != "err_to_tty"], n - 1)
        rng.shuffle(forms)
        if forms[0] == "append_out":  # дописывание в несуществующий файл — допустимо, но неинформативно
            continue
        names = rng.sample(STEPS, n)
        seq = list(zip(forms, names))
        out = _model(seq, log)
        if any(f in ("both_to_file", "append_out") for f in forms):
            break
    lines = ['step() { echo "ok $1"; echo "warn $1" >&2; }']
    lines += [FORMS[f].format(c=f"step {nm}", f=log) for f, nm in seq]
    lines.append(f"cat {log}")
    code = "\n".join(lines)
    expected = "\n".join(out)
    stem = (f"Скрипт ({ctx}) запускают в терминале в пустом каталоге; терминал показывает и stdout, и stderr. Что "
            "увидит оператор? Ответ — строки вывода по порядку.")
    expl = ("Перенаправления применяются слева направо: в `> f 2>&1` stderr копирует уже перенаправленный в файл "
            "stdout, а в `2>&1 > f` — ещё терминальный, поэтому warn остаётся на экране. `>` обрезает файл, `>>` "
            "дописывает; /dev/null поглощает поток.")
    checks = [Check(name="stdout", runner="bash", program="exec 2>&1\n" + code, expect="stdout_equals",
                    expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="bash",
                         params={"forms": forms})
