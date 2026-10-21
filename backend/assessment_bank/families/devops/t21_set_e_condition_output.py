"""devops.ci.t21_set_e_condition_output — predict_output (набор t21, порог Senior): `set -e` не действует внутри
функции, вызванной в условии `if`, в списке `||` / `&&`.

Шаг CI в подоболочке со `set -e` вызывает функцию этапа три раза: в условии `if`, в списке `||` или `&&` и обычной
командой. Правило bash: если функция исполняется там, где -e игнорируется (условие if, не последняя команда списка
&& / ||), команды её тела не прерывают выполнение — тело идёт до конца, статус функции — статус последней команды.
При обычном вызове упавшая команда сразу завершает подоболочку с её кодом. Ключ — независимая модель в генераторе;
проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.ci.t21_set_e_condition_output"

CTX = ["сборка биллинга", "пайплайн каталога", "сборка платёжного шлюза", "пайплайн поиска",
       "сборка личного кабинета", "пайплайн CRM", "сборка сервиса уведомлений"]
STAGES = ["lint", "test", "build", "scan", "pack", "push", "migrate", "smoke"]
FAILS = [("false", 1, ""), ('[ -f "$1.lock" ]', 1, "файлов `*.lock` в рабочем каталоге нет"),
         ("grep -q READY status.txt 2>/dev/null", 2, "файла `status.txt` в рабочем каталоге нет"),
         ('test -d "dist/$1"', 1, "каталога `dist/` в рабочем каталоге нет")]
FN = ["stage", "step", "run_stage", "job"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn = rng.choice(FN)
    fail_cmd, fail_rc, env_note = rng.choice(FAILS)
    tail = rng.random() < 0.7          # есть ли echo после упавшей команды (тогда статус функции 0)
    s1, s2, s3 = rng.sample(STAGES, 3)
    ctx2 = rng.choice(["or", "and"])
    plain_last = rng.random() < 0.7    # обычный вызов последним или вторым (тогда третий не исполняется)
    body = [f"  {fn}() {{", '    echo "begin $1"', f"    {fail_cmd}"] + (['    echo "end $1"'] if tail else []) + ["  }"]
    st = 0 if tail else fail_rc
    if_line = f'  if {fn} {s1}; then echo "{s1} ok"; else echo "{s1} failed"; fi'
    if_out = [f"begin {s1}"] + ([f"end {s1}"] if tail else []) + [f"{s1} ok" if st == 0 else f"{s1} failed"]
    if ctx2 == "or":
        l2 = f'  {fn} {s2} || echo "{s2} failed"'
        o2 = [f"begin {s2}"] + ([f"end {s2}"] if tail else []) + ([] if st == 0 else [f"{s2} failed"])
    else:
        l2 = f'  {fn} {s2} && echo "{s2} ok"'
        o2 = [f"begin {s2}"] + ([f"end {s2}"] if tail else []) + ([f"{s2} ok"] if st == 0 else [])
    plain = f"  {fn} {s3}"
    plain_out = [f"begin {s3}"]
    if plain_last:
        calls = [if_line, l2, plain, f'  echo "{s3} done"']
        outs = if_out + o2 + plain_out
    else:
        calls = [if_line, plain, l2, f'  echo "all done"']
        outs = if_out + plain_out
    lines = ["(", "  set -e"] + body + calls + [")", 'echo "status=$?"']
    outs = outs + [f"status={fail_rc}"]
    code = "\n".join(lines)
    out = "\n".join(outs)
    where = (f"В условии if и в списке {'||' if ctx2 == 'or' else '&&'}" if plain_last
             else "В условии if")
    expl = (f"{where} функция исполняется с выключенным -e: "
            f"«{fail_cmd}» возвращает {fail_rc}, но тело идёт дальше"
            + (", статус функции — статус последнего echo, то есть 0" if tail
               else f", а так как это последняя команда, функция возвращает {fail_rc}")
            + f". Обычный вызов «{fn} {s3}» под -e: та же команда сразу завершает подоболочку с кодом {fail_rc}"
            + ("" if plain_last else f", до списка с «{fn} {s2}» и последнего echo дело не доходит")
            + f". Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = (f"Шаг CI ({ctx}) запускает этапы функцией в подоболочке со `set -e`"
            + (f"; {env_note}." if env_note else "."))
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"fail": fail_cmd, "tail": tail, "ctx2": ctx2, "plain_last": plain_last},
                          language="bash")
