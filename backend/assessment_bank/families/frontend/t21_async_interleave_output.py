"""frontend.async.t21_async_interleave_output — predict_output (набор t21, порог Senior): чередование нескольких
async-функций с await в цикле, then на их промисах и таймер.

Два-три «загрузчика» интерфейса запускаются без await; каждый в цикле печатает шаг и делает `await` (значение или
уже выполненный промис — продолжение через одну микрозадачу). На промис одного загрузчика повешен `.then`, в части
вариантов в начале стоит `setTimeout(…, 0)`, синхронный console.log стоит между вызовами или после них. Ловушки:
async-функция выполняется синхронно до первого await; продолжения чередуются по очереди микрозадач (по одному шагу
каждой функции за «тик»); `.then` на результате срабатывает через тик после завершения функции; таймер — после
всех микрозадач. Ключ — модель очереди микрозадач в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.async.t21_async_interleave_output"

CTX = [("загрузка дашборда", "load", ["cards", "chart", "feed"]),
       ("синхронизация офлайн-данных", "syncPart", ["drafts", "photos", "likes"]),
       ("прогрев кэша", "warm", ["menu", "user", "promo"]),
       ("отрисовка виджетов", "paint", ["header", "table", "footer"])]
AWAITS = ["await null;", "await Promise.resolve();", "await 0;"]


def _simulate(calls, then_on, timer, sync_pos):
    """calls: [(name, steps)]; then_on: имя загрузчика с .then; sync_pos: индекс, ПЕРЕД которым console.log."""
    out, q = [], deque()

    def run(name, steps, i):
        # продолжение после await (или старт при i == 1): печать шагов до следующего await
        if i <= steps:
            out.append(f"{name} {i}")
            q.append(lambda: run(name, steps, i + 1))
            return
        out.append(f"{name} done")
        if name == then_on:
            q.append(lambda: out.append(f"{name} ready"))

    for idx, (name, steps) in enumerate(calls):
        if sync_pos == idx:
            out.append("main")
        run(name, steps, 1)
    if sync_pos == len(calls):
        out.append("main")
    while q:
        q.popleft()()
    if timer:
        out.append("timer")
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, pool = rng.choice(CTX)
    aw = rng.choice(AWAITS)
    for _ in range(200):
        k = rng.choice([2, 2, 3])
        names = rng.sample(pool, k)
        steps = [rng.randint(1, 3) for _ in range(k)]
        if len(set(steps)) == 1 and rng.random() < 0.7:
            continue
        calls = list(zip(names, steps))
        then_on = rng.choice(names)
        timer = rng.random() < 0.5
        sync_pos = rng.randint(1, k)
        out = _simulate(calls, then_on, timer, sync_pos)
        if not 7 <= len(out) <= 10:
            continue
        break
    else:
        raise RuntimeError("t21_async_interleave: не собран вариант")
    code_lines = []
    if timer:
        code_lines.append("setTimeout(() => console.log(\"timer\"), 0);")
    code_lines += [f"async function {fn}(name, steps) {{",
                   "  for (let i = 1; i <= steps; i++) {",
                   "    console.log(name, i);",
                   f"    {aw}",
                   "  }",
                   "  console.log(name, \"done\");",
                   "}"]
    for idx, (name, st) in enumerate(calls):
        if sync_pos == idx:
            code_lines.append("console.log(\"main\");")
        if name == then_on:
            code_lines.append(f"{fn}(\"{name}\", {st}).then(() => console.log(\"{name}\", \"ready\"));")
        else:
            code_lines.append(f"{fn}(\"{name}\", {st});")
    if sync_pos == len(calls):
        code_lines.append("console.log(\"main\");")
    code = "\n".join(code_lines)
    out_s = "\n".join(out)
    first = [f"{n} 1" for n, _s in calls]
    expl = (f"Каждый вызов {fn}() выполняется синхронно до первого await и печатает первый шаг "
            f"({', '.join(first)}); «main» печатается в своём месте синхронного кода. {aw[:-1]} ставит продолжение "
            f"в очередь микрозадач, поэтому дальше функции идут по очереди — по одному шагу за тик в порядке "
            f"постановки, а функция, у которой шаги кончились, печатает «done». Колбэк .then на промисе {then_on} "
            f"встаёт в конец очереди в момент «{then_on} done» — после уже поставленных шагов других вызовов"
            + (", таймер — только после всех микрозадач" if timer else "")
            + ". Порядок: " + " → ".join(out) + ".")
    stem = (f"Интерфейс ({ctx}): несколько асинхронных задач запускаются одновременно, без await, и печатают "
            f"свои шаги.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out_s, explanation=expl, context=ctx,
                          params={"calls": calls, "then_on": then_on, "timer": timer, "sync_pos": sync_pos,
                                  "await": aw}, language="javascript")
