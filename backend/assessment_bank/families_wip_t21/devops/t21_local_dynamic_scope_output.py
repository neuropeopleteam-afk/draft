"""devops.bash.t21_local_dynamic_scope_output — predict_output (набор t21, порог Middle): `local` и динамическая
область видимости переменных функций bash.

Счётчик повторов меняет вспомогательная функция `bump`, её вызывает функция задачи и основной скрипт. Правила
bash: функция видит переменные ВЫЗЫВАЮЩЕЙ функции (динамическая область), поэтому `bump`, вызванная из функции с
`local retries`, меняет её локальную копию, а не глобальную; без `local` присваивание в функции меняет глобальную
переменную; `local retries=$((retries + 1))` внутри bump читает значение вызывающего, но пишет в собственную копию,
которая пропадает при выходе. Ключ — независимая модель областей видимости в генераторе; проверка — исполнение
показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_local_dynamic_scope_output"

CTX = ["воркер очереди писем", "синхронизатор каталога", "клиент платёжного шлюза", "индексатор поиска",
       "агент выкладки", "сборщик метрик", "экспортёр CRM"]
NAMES = [("retries", "bump", "job"), ("attempts", "inc", "task"), ("failures", "count_fail", "sync"),
         ("errors", "note_error", "deploy")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    var, bump, job = rng.choice(NAMES)
    g0 = rng.randint(0, 3)
    l0 = rng.randint(5, 20)
    step = rng.choice([1, 1, 2, 3])
    job_local = rng.random() < 0.7
    bump_local = rng.random() < 0.3
    k_in = rng.randint(1, 3)
    k_out = rng.randint(1, 2)
    if bump_local:
        bump_line = f'{bump}() {{ local {var}=$(({var} + {step})); echo "{bump}: ${var}"; }}'
    else:
        bump_line = f"{bump}() {{ {var}=$(({var} + {step})); }}"
    lines = [f"{var}={g0}", bump_line, f"{job}() {{",
             f"  local {var}={l0}" if job_local else f"  {var}={l0}"]
    lines += [f"  {bump}"] * k_in
    lines += [f'  echo "{job}: ${var}"', "}", job]
    lines += [bump] * k_out
    lines.append(f'echo "main: ${var}"')
    # модель: стек областей видимости (глобальная + локальная функции job)
    outs: list[str] = []
    glob = g0
    job_val = None
    # вызов job
    if job_local:
        job_val = l0
    else:
        glob = l0
    for _ in range(k_in):
        cur = job_val if job_local else glob
        if bump_local:
            outs.append(f"{bump}: {cur + step}")
        else:
            if job_local:
                job_val = cur + step
            else:
                glob = cur + step
    outs.append(f"{job}: {job_val if job_local else glob}")
    for _ in range(k_out):
        if bump_local:
            outs.append(f"{bump}: {glob + step}")
        else:
            glob += step
    outs.append(f"main: {glob}")
    code = "\n".join(lines)
    out = "\n".join(outs)
    if bump_local:
        how_bump = (f"{bump} объявляет local {var}: читает значение вызывающего, печатает его +{step}, но копия "
                    f"исчезает при выходе — ни {job}, ни глобальная переменная не меняются")
    else:
        how_bump = (f"{bump} присваивает {var} без local — меняется ближайшая видимая переменная: "
                    + (f"внутри {job} это её local-копия" if job_local else "глобальная"))
    how_job = (f"{job} объявляет local {var}={l0}, глобальная остаётся {g0}" if job_local
               else f"{job} присваивает {var}={l0} без local — это глобальная переменная")
    expl = (f"{how_job}; {how_bump}. Вызовов {bump} внутри {job}: {k_in}, после — {k_out}. Вывод по строкам: "
            + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = f"Скрипт ({ctx}) считает неудачные попытки вспомогательной функцией."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"job_local": job_local, "bump_local": bump_local, "k_in": k_in, "k_out": k_out},
                          language="bash")
