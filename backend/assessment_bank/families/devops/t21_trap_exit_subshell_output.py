"""devops.bash.t21_trap_exit_subshell_output — predict_output (набор t21, порог Senior): `trap ... EXIT` в
подоболочке и в основном скрипте bash.

Функция выкладки работает в подоболочке `( ... )` со своей ловушкой EXIT (снять блокировку); одна из целей
завершается `exit N`. Правила: ловушка EXIT подоболочки срабатывает при выходе из НЕЁ (и при `exit`, и при обычном
завершении), код возврата подоболочки — аргумент exit или статус последней команды; ловушки основного скрипта
подоболочка не исполняет, ловушка EXIT основного скрипта срабатывает один раз в самом конце; повторный `trap` на
EXIT заменяет прежний. Ключ — независимая модель в генераторе; проверка — исполнение показанного скрипта в bash.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_trap_exit_subshell_output"

CTX = ["выкладка интернет-магазина", "обновление биллинга", "релиз платёжного шлюза", "выкладка поиска",
       "обновление личного кабинета", "релиз CRM", "выкладка сервиса уведомлений"]
TARGETS = ["api", "db", "web", "cache", "queue", "auth", "cron"]
FN = ["deploy", "roll", "ship", "release"]
LOCK = [("unlock", "lock"), ("release", "lease"), ("drop", "flag")]
MAIN = [("main: cleanup", "main: report"), ("cleanup tmp", "send report"), ("remove workdir", "notify chat")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn = rng.choice(FN)
    un, _ = rng.choice(LOCK)
    m1, m2 = rng.choice(MAIN)
    n = rng.randint(2, 3)
    targets = rng.sample(TARGETS, n)
    bad = rng.choice(targets[:-1]) if rng.random() < 0.7 else rng.choice(targets)
    code_rc = rng.randint(2, 7)
    replace = rng.random() < 0.5
    replace_after = rng.randint(1, n - 1) if replace else None
    lines = [f"trap 'echo \"{m1}\"' EXIT",
             f"{fn}() {{",
             "  (",
             f"    trap 'echo \"{un} $1\"' EXIT",
             f'    echo "start $1"',
             f'    if [ "$1" = "{bad}" ]; then exit {code_rc}; fi',
             f'    echo "done $1"',
             "  )",
             f'  echo "rc[$1]=$?"',
             "}"]
    out = []
    for i, t in enumerate(targets, start=1):
        lines.append(f"{fn} {t}")
        out.append(f"start {t}")
        if t == bad:
            out += [f"{un} {t}", f"rc[{t}]={code_rc}"]
        else:
            out += [f"done {t}", f"{un} {t}", f"rc[{t}]=0"]
        if replace and i == replace_after:
            lines.append(f"trap 'echo \"{m2}\"' EXIT")
    lines.append('echo "finish"')
    out.append("finish")
    final = m2 if replace else m1
    out.append(final)
    code = "\n".join(lines)
    ans = "\n".join(out)
    expl = (f"Каждый вызов {fn} запускает подоболочку со своей ловушкой EXIT: «{un} <цель>» печатается при выходе из "
            f"неё — и после exit {code_rc} у цели {bad} (код подоболочки {code_rc}, «done {bad}» не печатается), "
            f"и при обычном завершении (код 0). Подоболочка не исполняет ловушку основного скрипта, поэтому после "
            f"каждой цели «{m1}» не появляется; ловушка EXIT основного скрипта срабатывает один раз — после "
            f"«finish». " + (f"Повторный trap на EXIT заменил первый, поэтому в конце «{m2}», а не «{m1}». "
                            if replace else "")
            + "Вывод по строкам: " + " / ".join(f"«{x}»" for x in out) + ".")
    stem = (f"Скрипт ({ctx}) выкладывает компоненты по очереди; каждая выкладка держит блокировку в своей "
            f"подоболочке.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=ans, explanation=expl, context=ctx,
                          params={"targets": targets, "bad": bad, "rc": code_rc, "replace": replace},
                          language="bash")
