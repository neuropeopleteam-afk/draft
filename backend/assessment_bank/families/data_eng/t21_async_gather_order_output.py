"""data_eng.etl.t21_async_gather_order_output — predict_output (набор t21, порог Senior): параллельная загрузка
партиций в asyncio — create_task, gather и await asyncio.sleep(0).

Каждая корутина `load` уступает управление `waits` раз (sleep(0)), затем дописывает имя в журнал. Отдельная задача
создаётся create_task ДО gather, но начинает выполняться только когда main уступит управление; все задачи идут по
кругу в порядке создания. Ловушки: журнал — порядок завершения (меньше уступок — раньше, при равенстве — порядок
создания), а результат gather — в порядке аргументов; «gather» в журнале появляется после завершения всех её задач,
отдельная задача может закончиться раньше или позже. Ключ — независимая модель планировщика в генераторе (без
исполнения кода); проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.etl.t21_async_gather_order_output"

CTX = ["параллельная загрузка дневных партиций", "одновременная выгрузка таблиц в хранилище",
       "обновление витрин после ночной загрузки", "перенос справочников из нескольких источников",
       "догрузка пропущенных часов событий"]
NAMES = ["orders", "users", "clicks", "stock", "prices", "refunds", "sessions", "reviews"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    for _ in range(500):
        k = rng.randint(2, 3)
        names = rng.sample(NAMES, k + 1)
        first_name, g_names = names[0], names[1:]
        g_waits = [rng.randint(0, 3) for _ in range(k)]
        mx = max(g_waits)
        f_waits = rng.choice([rng.randint(0, mx + 1), rng.randint(mx + 3, mx + 4)])
        if len(set(g_waits)) >= 2 or k == 2:
            break
    # модель: все задачи стартуют в первой итерации цикла событий в порядке создания (first, затем аргументы gather);
    # задача с w уступками завершается в итерации w + 1; main продолжает после gather в итерации max(w) + 3
    tasks = [(f_waits + 1, 0, first_name)] + [(w + 1, i + 1, n) for i, (w, n) in enumerate(zip(g_waits, g_names))]
    g_resume = mx + 3
    events = sorted(tasks)
    log = []
    gather_done = False
    for it, _idx, n in events:
        if not gather_done and it >= g_resume:
            log.append("gather")
            gather_done = True
        log.append(n)
    if not gather_done:
        log.append("gather")
    assert f_waits + 1 != g_resume
    args = ", ".join(f'load("{n}", {w})' for n, w in zip(g_names, g_waits))
    code = ("import asyncio\n"
            "done = []\n"
            "async def load(name, waits):\n"
            "    for _ in range(waits):\n"
            "        await asyncio.sleep(0)\n"
            "    done.append(name)\n"
            "    return waits\n"
            "async def main():\n"
            f"    first = asyncio.create_task(load(\"{first_name}\", {f_waits}))\n"
            f"    sizes = await asyncio.gather({args})\n"
            "    done.append(\"gather\")\n"
            "    await first\n"
            "    print(*done)\n"
            "    print(*sizes)\n"
            "asyncio.run(main())")
    out = " ".join(log) + "\n" + " ".join(str(w) for w in g_waits)
    order_txt = ", ".join(f"{n} ({it - 1})" for it, _, n in events)
    expl = (f"create_task не запускает задачу сразу: {first_name} стартует вместе с задачами gather, когда main "
            f"уступает управление на await. Каждый sleep(0) — один круг по готовым задачам в порядке создания, поэтому "
            f"задачи завершаются по числу уступок (при равенстве — в порядке создания): {order_txt}. «gather» "
            f"дописывается только после завершения всех её задач"
            + (f", а {first_name} к этому моменту уже готова" if f_waits <= mx + 1 else
               f", а {first_name} ещё работает и дописывается после") +
            f". gather возвращает результаты в порядке аргументов: {' '.join(str(w) for w in g_waits)}.")
    stem = (f"Задача «{ctx}» запускает загрузки конкурентно в asyncio; программа печатает журнал завершения и "
            "результаты.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"first_waits": f_waits, "gather_waits": g_waits}, language="python")
