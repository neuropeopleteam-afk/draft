"""backend.async.t21_gather_sleep0_order_output — predict_output (набор t21, порог Senior): asyncio — create_task,
await asyncio.sleep(0) и порядок результатов gather.

Обработчик запроса параллельно ходит в несколько сервисов: две задачи созданы create_task заранее, третья корутина
передана в gather напрямую. Каждая «загрузка» печатает шаг и отдаёт управление через sleep(0). Ловушки: задачи
не начинают работу до первого await в main; sleep(0) ставит задачу в конец очереди готовых — шаги идут по кругу
в порядке постановки; корутина из gather становится задачей позже уже созданных; gather возвращает результаты
в порядке аргументов, а не завершения. Ключ — независимая модель очереди готовых задач (FIFO) в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.async.t21_gather_sleep0_order_output"

CTX = [("страница заказа", ["user", "cart", "stock", "price", "promo"]),
       ("профиль клиента", ["account", "bonus", "orders", "avatar", "limits"]),
       ("карточка товара", ["item", "reviews", "stock", "price", "seller"]),
       ("отчёт для поддержки", ["ticket", "chat", "billing", "device", "geo"])]


def _simulate(pre: list[str], late: str, steps: dict[str, int], main_sleep: bool) -> list[str]:
    """Очередь готовых задач: каждый ход задачи — печать шага и постановка в конец (sleep(0)) либо завершение."""
    out: list[str] = []
    pos = {n: 0 for n in steps}
    queue = list(pre)  # create_task ставит задачу в очередь сразу

    def turn(name: str) -> None:
        i = pos[name]
        if i < steps[name]:
            out.append(f"{name} {i}")
            pos[name] = i + 1
            queue.append(name)
        # иначе — завершение задачи (return), в очередь не возвращается

    if main_sleep:
        queue.append("<main>")
        while queue[0] != "<main>":
            turn(queue.pop(0))
        queue.pop(0)
    out.append("main")
    queue.append(late)  # gather оборачивает корутину в задачу в момент вызова
    while queue:
        turn(queue.pop(0))
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    a, b, c = rng.sample(pool, 3)
    steps = {a: rng.randint(1, 3), b: rng.randint(1, 3), c: rng.randint(1, 2)}
    if len(set(steps.values())) == 1:
        steps[b] = 3 if steps[b] != 3 else 1
    main_sleep = rng.random() < 0.4
    args = ["t1", "t2", f'fetch("{c}", {steps[c]})']
    rng.shuffle(args)
    if args == ["t1", "t2", f'fetch("{c}", {steps[c]})']:
        args = [args[1], args[0], args[2]]
    lines = ["import asyncio",
             "async def fetch(name, steps):",
             "    for i in range(steps):",
             "        print(name, i)",
             "        await asyncio.sleep(0)",
             "    return name.upper()",
             "async def main():",
             f'    t1 = asyncio.create_task(fetch("{a}", {steps[a]}))',
             f'    t2 = asyncio.create_task(fetch("{b}", {steps[b]}))']
    if main_sleep:
        lines.append("    await asyncio.sleep(0)")
    lines += ['    print("main")',
              f"    res = await asyncio.gather({', '.join(args)})",
              "    print(*res)",
              "asyncio.run(main())"]
    code = "\n".join(lines)
    printed = _simulate([a, b], c, steps, main_sleep)
    name_of = {"t1": a, "t2": b}
    res = [name_of.get(x, c).upper() for x in args]
    out = "\n".join(printed + [" ".join(res)])
    expl = ("create_task только ставит задачи в очередь готовых: до первого await в main они не выполняются"
            + (" — здесь main сам уступает управление через sleep(0), и каждая задача успевает сделать по шагу до "
               "«main»" if main_sleep else ", поэтому «main» печатается первым")
            + f". Корутина {c} становится задачей только внутри gather — после {a} и {b}. Дальше sleep(0) каждый раз "
              "ставит задачу в конец очереди, шаги идут по кругу: " + ", ".join(printed)
            + f". gather возвращает результаты в порядке аргументов, а не завершения: {' '.join(res)}.")
    stem = (f"Сервис собирает данные для экрана «{ctx}»: обработчик параллельно запрашивает несколько внутренних "
            "сервисов через asyncio.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"steps": steps, "args": args, "main_sleep": main_sleep}, language="python")
