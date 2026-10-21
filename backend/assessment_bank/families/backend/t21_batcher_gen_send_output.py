"""backend.queue.t21_batcher_gen_send_output — predict_output (набор t21, порог Senior): генератор-накопитель —
next, send и return (StopIteration.value).

Накопитель пачек для отправки в очередь: генератор принимает элементы через send, отдаёт текущий размер пачки,
при заполнении печатает flush и начинает новую пачку, а по send(None) возвращает остаток через return.
Ловушки: первый next() доходит до первого yield и отдаёт 0; send возвращает значение СЛЕДУЮЩЕГО yield (после
flush — 0); flush печатается раньше, чем print напечатает результат send; остаток приходит в StopIteration.value.
Ключ — независимая модель накопителя в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.queue.t21_batcher_gen_send_output"

CTX = [("отправка событий аналитики", "events"), ("запись логов в хранилище", "logs"),
       ("рассылка уведомлений", "notifications"), ("выгрузка заказов в учётную систему", "orders"),
       ("индексация документов", "documents")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, what = rng.choice(CTX)
    limit = rng.randint(2, 3)
    for _ in range(100):
        n = rng.randint(limit + 2, limit * 2 + 1)
        if n % limit:
            break
    items = rng.sample(range(10, 99), n)
    gname = rng.choice(["batcher", "collector", "buffer"])
    var = rng.choice(["g", "acc", "b"])
    code = (f"def {gname}(limit):\n"
            "    batch = []\n"
            "    while True:\n"
            "        item = yield len(batch)\n"
            "        if item is None:\n"
            "            return batch\n"
            "        batch.append(item)\n"
            "        if len(batch) == limit:\n"
            '            print("flush", batch)\n'
            "            batch = []\n"
            f"{var} = {gname}({limit})\n"
            f"print(next({var}))\n"
            f"for x in {items}:\n"
            f"    print({var}.send(x))\n"
            "try:\n"
            f"    {var}.send(None)\n"
            "except StopIteration as e:\n"
            '    print("left", e.value)')
    lines = ["0"]
    batch: list[int] = []
    flushes = 0
    for x in items:
        batch.append(x)
        if len(batch) == limit:
            lines.append("flush [" + ", ".join(str(v) for v in batch) + "]")
            batch = []
            flushes += 1
        lines.append(str(len(batch)))
    left = "[" + ", ".join(str(v) for v in batch) + "]"
    lines.append(f"left {left}")
    out = "\n".join(lines)
    expl = (f"next() доходит до первого yield и печатает 0. Каждый send кладёт элемент и возвращает значение "
            f"следующего yield — размер пачки; на {limit}-м элементе сначала печатается flush (внутри генератора), "
            f"пачка обнуляется, и send возвращает 0. Всего flush: {flushes}. send(None) выполняет return — остаток "
            f"{left} приходит в StopIteration.value.")
    stem = (f"Сервис «{ctx}» ({what}) копит элементы пачками перед отправкой в очередь; накопитель написан как "
            "генератор.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"limit": limit, "items": items}, language="python")
