"""backend.queue.t21_queue_drain_while_output — predict_output (набор t21, порог Стажёра): цикл while со счётчиком.

Воркер разбирает очередь пачками по batch сообщений, пока в ней что-то есть: `while pending > 0: pending -= batch`.
Ловушки: последний проход забирает «неполную» пачку, и pending уходит в минус (никто не обрезает до нуля);
если число делится нацело — ровно 0. Ключ — независимый расчёт делением с округлением вверх в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.queue.t21_queue_drain_while_output"

CTX = [("очередь писем", "emails"), ("очередь вебхуков", "webhooks"), ("очередь миниатюр", "thumbnails"),
       ("очередь платежей на сверку", "reconcile"), ("очередь push-уведомлений", "push"),
       ("очередь экспорта отчётов", "exports")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, q = rng.choice(CTX)
    batch = rng.randint(3, 12)
    if rng.random() < 0.25:
        pending = batch * rng.randint(3, 7)
    else:
        pending = rng.randint(14, 90)
    counter = rng.choice(["rounds", "passes", "polls", "cycles"])
    left = rng.choice(["pending", "backlog", "left"])
    size = rng.choice(["batch", "chunk", "per_poll"])
    code = (f"{left} = {pending}\n"
            f"{size} = {batch}\n"
            f"{counter} = 0\n"
            f"while {left} > 0:\n"
            f"    {left} -= {size}\n"
            f"    {counter} += 1\n"
            f"print({counter}, {left})")
    rounds = -(-pending // batch)
    rest = pending - rounds * batch
    out = f"{rounds} {rest}"
    full = pending // batch
    if rest == 0:
        tail = f"{pending} делится на {batch} нацело: после {rounds}-го прохода {left} = 0, и цикл останавливается."
    else:
        tail = (f"после {full} полных пачек осталось {pending - full * batch}, нужен ещё один проход; "
                f"вычитание не обрезается до нуля: {pending - full * batch} − {batch} = {rest}.")
    expl = f"Каждый проход вычитает {batch}, пока {left} > 0: {tail} Вывод: «{out}»."
    stem = (f"Воркер разбирает «{ctx}» ({q}) пачками фиксированного размера, пока в очереди есть сообщения; "
            "программа считает проходы.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pending": pending, "batch": batch}, language="python")
