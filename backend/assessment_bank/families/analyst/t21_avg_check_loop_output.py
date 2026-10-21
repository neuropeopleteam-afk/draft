"""analyst.python.t21_avg_check_loop_output — predict_output (набор t21, порог Стажёра): цикл с распаковкой
кортежа, if и два накопителя; средний чек через «/».

Список заказов `(статус, сумма)`; программа суммирует оплаченные заказы, считает их число и печатает сумму и средний
чек `total / count`. Ловушки чтения: в сумму идут только строки с нужным статусом, деление `/` всегда даёт float
(печатается с «.0» даже при целом результате). Средний чек подобран так, что печатается коротко и однозначно
(целое или половина). Ключ — независимый расчёт в генераторе; проверка — исполнение показанного кода в песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.python.t21_avg_check_loop_output"

# (сюжет, имя списка, статусы: [засчитываемый, прочие...], шаг суммы, диапазон)
CTX = [
    ("интернет-магазин: заказы за час", "orders", ["paid", "cancelled", "pending"], 50, (300, 3000)),
    ("доставка еды: заказы за вечер", "orders", ["delivered", "cancelled", "returned"], 10, (400, 2500)),
    ("онлайн-кинотеатр: покупки фильмов за день", "purchases", ["success", "failed", "refund"], 10, (100, 700)),
    ("сервис такси: поездки за смену", "rides", ["done", "cancelled"], 10, (200, 1500)),
    ("магазин курсов: оплаты за неделю", "payments", ["ok", "declined", "refund"], 100, (1000, 9000)),
]


def _fmt_float(x: float) -> str:
    return repr(float(x))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, var, statuses, step, (lo, hi) = rng.choice(CTX)
    good = statuses[0]
    for _ in range(500):
        n = rng.randint(5, 7)
        rows = []
        for _k in range(n):
            st = good if rng.random() < 0.6 else rng.choice(statuses[1:])
            rows.append((st, rng.randrange(lo, hi + 1, step)))
        paid = [a for s, a in rows if s == good]
        if not 2 <= len(paid) <= n - 2:
            continue
        total, cnt = sum(paid), len(paid)
        if (2 * total) % cnt:          # средний чек — целое или .5: печатается однозначно
            continue
        if total % cnt == 0 and rng.random() < 0.4:
            continue                   # чаще — дробный средний чек, но и целые встречаются
        break
    else:
        raise RuntimeError("t21_avg_check_loop: не собрались данные")
    avg = total / cnt
    lst = "[" + ", ".join(f'("{s}", {a})' for s, a in rows) + "]"
    item = rng.choice([("status", "amount"), ("st", "value"), ("state", "price")])
    code = (f"{var} = {lst}\n"
            "total = 0\n"
            "count = 0\n"
            f"for {item[0]}, {item[1]} in {var}:\n"
            f"    if {item[0]} == \"{good}\":\n"
            f"        total += {item[1]}\n"
            "        count += 1\n"
            "print(total, total / count)")
    out = f"{total} {_fmt_float(avg)}"
    stem = f"Аналитик считает выручку и средний чек ({plot}) по выгрузке из базы — список пар «статус, сумма»."
    expl = (f"В сумму идут только строки со статусом \"{good}\": " + " + ".join(str(a) for a in paid)
            + f" = {total}, их {cnt}. Деление «/» в Python всегда даёт float: {total} / {cnt} = {_fmt_float(avg)} "
              f"(с дробной частью, даже если делится нацело). Вывод: «{out}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "good": good}, language="python")
