"""devops.bash.t21_pipe_subshell_counter_output — predict_output (набор t21, порог Senior): `cmd | while read`
выполняется в подоболочке — счётчик после цикла не меняется.

Скрипт разбирает журнал запросов `access.log` двумя циклами `while read`: один читает из конвейера
(`cat access.log | while ...`), другой — перенаправлением (`done < access.log` или `done < <(cat access.log)`).
В bash каждая часть конвейера (без `shopt -s lastpipe`) исполняется в подоболочке: echo внутри цикла печатает
растущий счётчик, но после цикла переменная родительской оболочки прежняя (0). Цикл с перенаправлением или
подстановкой процесса работает в текущей оболочке, его счётчик сохраняется. Ключ — независимая модель в генераторе;
проверка — исполнение показанного скрипта в bash-песочнице с тем же журналом.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_pipe_subshell_counter_output"

CTX = ["API заказов", "платёжный шлюз", "поиск по каталогу", "личный кабинет", "сервис уведомлений",
       "API склада", "CRM"]
PATHS = ["/api/orders", "/api/cart", "/health", "/api/pay", "/login", "/api/search", "/api/stock", "/metrics",
         "/api/users", "/export"]
CODES = [200, 200, 200, 201, 204, 304, 404, 500, 502, 503]


def _metric(kind: str, thr: int):
    """(имя переменной, метка, условие bash, функция модели по (code, ms))."""
    if kind == "slow":
        return "slow", "slow", f'[ "$ms" -gt {thr} ]', lambda c, m: m > thr
    if kind == "errors":
        return "errors", "error", '[ "$code" -ge 500 ]', lambda c, m: c >= 500
    return "missing", "404", '[ "$code" -eq 404 ]', lambda c, m: c == 404


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    thr = rng.choice([200, 250, 300, 400, 500])
    for _ in range(500):
        n = rng.randint(5, 7)
        rows = [(rng.choice(PATHS), rng.choice(CODES), rng.randint(15, 900)) for _ in range(n)]
        kinds = rng.sample(["slow", "errors", "missing"], 2)
        m1, m2 = _metric(kinds[0], thr), _metric(kinds[1], thr)
        c1 = sum(1 for _, c, m in rows if m1[3](c, m))
        c2 = sum(1 for _, c, m in rows if m2[3](c, m))
        if 1 <= c1 <= 3 and c2 >= 1 and len({p for p, _, _ in rows}) == n:
            break
    else:
        raise RuntimeError("t21_pipe_subshell: не подобран журнал")
    pipe_first = rng.random() < 0.5
    pipe_src = rng.choice(["cat access.log |", "grep -v '^#' access.log |"])
    redir = rng.choice(["done < access.log", "done < <(cat access.log)"])
    v1, lab1, cond1, f1 = m1
    v2, _lab2, cond2, f2 = m2
    pipe_loop = [f"{v1}=0",
                 f"{pipe_src} while read -r path code ms; do",
                 f"  if {cond1}; then",
                 f"    {v1}=$(({v1} + 1))",
                 f'    echo "{lab1} $path ${v1}"',
                 "  fi",
                 "done",
                 f'echo "{v1}=${v1}"']
    redir_loop = [f"{v2}=0",
                  "while read -r path code ms; do",
                  f"  if {cond2}; then {v2}=$(({v2} + 1)); fi",
                  redir,
                  f'echo "{v2}=${v2}"']
    code = "\n".join(pipe_loop + redir_loop if pipe_first else redir_loop + pipe_loop)
    inner, k = [], 0
    for p, c, m in rows:
        if f1(c, m):
            k += 1
            inner.append(f"{lab1} {p} {k}")
    pipe_out = inner + [f"{v1}=0"]
    redir_out = [f"{v2}={c2}"]
    out_lines = pipe_out + redir_out if pipe_first else redir_out + pipe_out
    out = "\n".join(out_lines)
    log = "\n".join(f"{p} {c} {m}" for p, c, m in rows) + "\n"
    expl = (f"Цикл после «{pipe_src}» — часть конвейера и исполняется в подоболочке: внутри echo печатает растущий "
            f"счётчик ({', '.join(inner)}), но после цикла в основной оболочке {v1} по-прежнему 0. Цикл "
            f"«while … {redir}» идёт в текущей оболочке, поэтому {v2}={c2} сохраняется. Вывод по строкам: "
            + " / ".join(f"«{x}»" for x in out_lines) + ".")
    shown_log = "\n".join(f"    {p} {c} {m}" for p, c, m in rows)
    stem = (f"Скрипт разбирает журнал запросов ({ctx}). Файл `access.log` (путь, код ответа, время в мс):\n\n"
            f"{shown_log}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"kinds": kinds, "pipe_first": pipe_first, "redir": redir},
                          language="bash", files={"access.log": log})
