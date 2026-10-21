"""devops.mon.t21_asyncio_probe_order_output — predict_output (набор t21, порог Senior): порядок выполнения задач
asyncio — create_task, sleep(0), await задачи и gather.

Проверка готовности запускает пробы сервисов задачами; каждая проба делает несколько `await asyncio.sleep(0)`.
Правила цикла событий: create_task только ставит задачу в очередь (она начнётся, когда main уступит управление),
`sleep(0)` отдаёт ход и ставит корутину в конец очереди готовых, `await task` будит main, когда задача завершится
(main встаёт в конец очереди в этот момент), gather возвращает результаты в порядке аргументов. Ключ — независимая
модель планировщика (очередь FIFO на генераторах, без asyncio) в генераторе; проверка — исполнение показанного кода
в песочнице Python.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.mon.t21_asyncio_probe_order_output"

CTX = ["проверка готовности кластера биллинга", "предстартовая проверка каталога", "проверка зависимостей шлюза",
       "проверка перед выкладкой поиска", "проверка готовности личного кабинета", "проверка зависимостей CRM",
       "предстартовая проверка сервиса уведомлений"]
SERVICES = ["db", "cache", "queue", "auth", "s3", "dns", "smtp", "search", "vault", "kafka", "ldap", "redis"]
NAMES = [("probe", "hops", "tasks", "results", "first"), ("check", "steps", "jobs", "status", "early"),
         ("ping", "rounds", "pending", "answers", "one"), ("wait_ready", "polls", "running", "report", "got1")]


def _model(probes, k_sleep, await_j, rv="results", fv="first"):
    """Модель цикла событий: очередь готовых FIFO, sleep(0) — в конец очереди, ожидание — по завершению задачи."""
    out: list[str] = []
    ready: deque = deque()
    gens: dict = {}
    done: dict = {}
    waiters: dict = {}

    def task_gen(name, hops):
        out.append(f"start {name}")
        for _ in range(hops):
            yield ("sleep", None)
        out.append(f"ok {name}")
        return hops

    def main_gen():
        for i, (name, hops) in enumerate(probes):
            gens[i] = task_gen(name, hops)
            ready.append(i)
        out.append("scheduled")
        for _ in range(k_sleep):
            yield ("sleep", None)
        out.append("tick")
        if await_j is not None:
            if await_j not in done:
                yield ("wait", await_j)
            out.append(f"{fv} {done[await_j]}")
        while len(done) < len(probes):
            yield ("wait", next(i for i in range(len(probes)) if i not in done))
        out.append(f"{rv} [" + ", ".join(str(done[i]) for i in range(len(probes))) + "]")

    gens["main"] = main_gen()
    ready.append("main")
    while ready:
        ent = ready.popleft()
        try:
            cmd, arg = next(gens[ent])
        except StopIteration as stop:
            if ent != "main":
                done[ent] = stop.value
                for w in waiters.pop(ent, []):
                    ready.append(w)
            continue
        if cmd == "sleep":
            ready.append(ent)
        else:
            waiters.setdefault(arg, []).append(ent)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn, hv, tv, rv, fv = rng.choice(NAMES)
    for _ in range(300):
        n = rng.randint(3, 4)
        names = rng.sample(SERVICES, n)
        hops = [rng.randint(0, 3) for _ in range(n)]
        use_await = rng.random() < 0.5
        k_sleep = rng.randint(0, 1) if use_await else rng.randint(0, 2)
        await_j = rng.randrange(n) if use_await else None
        if len(set(hops)) < 2 or (await_j is not None and hops[await_j] == 0 and k_sleep == 0):
            continue
        probes = list(zip(names, hops))
        out_lines = _model(probes, k_sleep, await_j, rv, fv)
        break
    else:
        raise RuntimeError("t21_asyncio_probe_order: не подобраны пробы")
    pairs = ", ".join(f'("{nm}", {h})' for nm, h in probes)
    lines = ["import asyncio",
             "",
             f"async def {fn}(name, {hv}):",
             '    print("start", name)',
             f"    for _ in range({hv}):",
             "        await asyncio.sleep(0)",
             '    print("ok", name)',
             f"    return {hv}",
             "",
             "async def main():",
             f"    {tv} = [asyncio.create_task({fn}(n, h)) for n, h in [{pairs}]]",
             '    print("scheduled")']
    lines += ["    await asyncio.sleep(0)"] * k_sleep
    lines.append('    print("tick")')
    if await_j is not None:
        lines += [f"    {fv} = await {tv}[{await_j}]", f'    print("{fv}", {fv})']
    lines += [f"    {rv} = await asyncio.gather(*{tv})",
              f'    print("{rv}", {rv})',
              "",
              "asyncio.run(main())"]
    code = "\n".join(lines)
    out = "\n".join(out_lines)
    expl = ("create_task только ставит пробы в очередь — первой печатается «scheduled». Затем "
            + (f"main {k_sleep} раз уступает ход через sleep(0)" if k_sleep else "main не уступает ход до «tick»")
            + "; пробы идут по очереди готовых: каждая sleep(0) ставит пробу в конец очереди. "
            + (f"`await {tv}[{await_j}]` будит main, когда задача {probes[await_j][0]} завершится (main встаёт в "
               "конец очереди). " if await_j is not None else "")
            + "gather ждёт всех и возвращает результаты в порядке задач. Вывод по строкам: "
            + " / ".join(f"«{x}»" for x in out_lines) + ".")
    stem = f"Скрипт ({ctx}) запускает пробы сервисов параллельно задачами asyncio."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"probes": probes, "k_sleep": k_sleep, "await_j": await_j}, language="python")
