"""backend.queue.t21_consumer_continue_break_output — predict_output (набор t21, порог Junior): цикл с continue
и break и enumerate со стартом 1.

Потребитель разбирает пачку сообщений: слишком большие (размер > limit) пропускает через continue, на
повреждённом сообщении (размер < 0) останавливается через break, остальные суммирует. Ловушки (две конструкции
вместе): enumerate(..., 1) нумерует с единицы, и после break переменная цикла сохраняет номер повреждённого
сообщения; сообщения после break не обрабатываются; пропущенные continue не входят в сумму. Ключ — независимая модель в генераторе; проверка —
исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.queue.t21_consumer_continue_break_output"

CTX = [("очередь заказов", "orders"), ("очередь вебхуков", "webhooks"), ("очередь событий аналитики", "events"),
       ("очередь писем", "emails"), ("очередь синхронизации остатков", "stock")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, q = rng.choice(CTX)
    limit = rng.choice([20, 25, 30, 40, 50])
    for _ in range(300):
        n = rng.randint(6, 8)
        sizes = []
        for _ in range(n):
            r = rng.random()
            if r < 0.15:
                sizes.append(-1)
            elif r < 0.35:
                sizes.append(rng.randint(limit + 1, limit + 40))
            else:
                sizes.append(rng.randint(1, limit))
        poison = [i for i, s in enumerate(sizes) if s < 0]
        if not poison or not 3 <= poison[0] <= n - 2:
            continue
        p = poison[0]
        big_before = [s for s in sizes[:p] if s > limit]
        ok_before = [s for s in sizes[:p] if 0 < s <= limit]
        ok_after = [s for s in sizes[p + 1:] if 0 < s <= limit]
        if big_before and len(ok_before) >= 2 and ok_after:
            break
    else:
        raise RuntimeError("t21_consumer: не собрана пачка")
    var = rng.choice(["batch", "messages", "inbox"])
    code = (f"{var} = {sizes}\n"
            "total = 0\n"
            f"for i, size in enumerate({var}, 1):\n"
            f"    if size > {limit}:\n"
            "        continue\n"
            "    if size < 0:\n"
            "        break\n"
            "    total += size\n"
            "print(total, i)")
    i_end = p + 1
    total = sum(ok_before)
    out = f"{total} {i_end}"
    expl = (f"До первого отрицательного размера ({p + 1}-е сообщение) просуммированы только размеры не больше {limit}: "
            f"{' + '.join(str(s) for s in ok_before)} = {total}; "
            f"{', '.join(str(s) for s in big_before)} пропущены через continue. break срабатывает на {i_end}-м сообщении: "
            f"enumerate(..., 1) считает с единицы, и после break переменная цикла i сохраняет значение {i_end}; "
            f"сообщения после break не обрабатываются. Вывод: «{out}».")
    stem = (f"Потребитель «{ctx}» ({q}) разбирает пачку сообщений по размерам в КБ: слишком большие пропускает "
            "(их разберёт отдельный обработчик), на повреждённом сообщении (отрицательный размер) останавливается.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"sizes": sizes, "limit": limit}, language="python")
