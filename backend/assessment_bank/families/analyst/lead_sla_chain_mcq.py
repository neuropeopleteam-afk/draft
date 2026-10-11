"""analyst.lead.sla_chain_mcq — mcq_concept (Lead): какое одно изменение дешевле всего обеспечит целевую доступность операции.

Операция вызывает синхронно цепочку сервисов (доступность — произведение) и асинхронно, через очередь, сервис
уведомлений (на доступность операции не влияет). Четыре изменения с ценой в месяц: второй экземпляр склада в другой
зоне (1 − (1 − a)²), второй платёжный провайдер с переключением (1 − (1 − a)²), резерв товара асинхронно после
оформления (склад уходит из синхронной цепочки), платный тариф шлюза с SLA 99,99 %. Отказы независимы. Ответ —
самое дешёвое изменение из обеспечивающих цель.

Варианты ответа — всегда те же четыре изменения (форма вариантов ключ не выдаёт); верное изменение по seed
распределено поровну. Ловушки, заложенные в числа: асинхронный сервис уведомлений, умноженный в цепочку, делает
верное изменение «недостаточным»; есть более дешёвое, но недостаточное изменение и более сильное, но дорогое. Ключ
проверяется исполнением: программа считает доступность для каждого изменения.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import computed_mcq, ru_num
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.lead.sla_chain_mcq"

CONTEXTS = [("интернет-магазин", "оформление заказа"), ("сервис доставки еды", "оформление заказа"),
            ("аптечная сеть", "заказ с самовывозом"), ("магазин электроники", "оформление покупки в кредит"),
            ("маркетплейс", "покупка в один клик"), ("сервис билетов", "покупка билета"),
            ("сеть кинотеатров", "бронирование мест"), ("магазин стройматериалов", "заказ с доставкой")]

IMPROVEMENTS = {
    "stock_replica": "второй экземпляр сервиса склада в другой зоне",
    "second_psp": "второй платёжный провайдер с автоматическим переключением",
    "async_reserve": "резерв товара асинхронно, после оформления (через очередь)",
    "gateway_tier": "тариф API-шлюза с SLA 99,99 %",
}
ORDER = ["stock_replica", "second_psp", "async_reserve", "gateway_tier"]

PROGRAM = '''A = {a!r}          # доступность, доли: шлюз, заказы, платежи, склад, уведомления (асинхронно)
COST = {cost!r}    # цена изменения в месяц, тыс. руб.
TARGET = {target!r}
NAMES = {names!r}


def chain(a):   # синхронная цепочка; уведомления — через очередь, в произведение не входят
    return a["gw"] * a["orders"] * a["psp"] * a["stock"]


def after(change):
    a = dict(A)
    if change == "stock_replica":
        a["stock"] = 1 - (1 - a["stock"]) ** 2
    elif change == "second_psp":
        a["psp"] = 1 - (1 - a["psp"]) ** 2
    elif change == "async_reserve":
        a["stock"] = 1.0
    elif change == "gateway_tier":
        a["gw"] = 0.9999
    return chain(a)


ok = [c for c in COST if after(c) >= TARGET]
print(NAMES[min(ok, key=lambda c: COST[c])])
'''


def _chain(a, with_async=False):
    v = a["gw"] * a["orders"] * a["psp"] * a["stock"]
    return v * a["notify"] if with_async else v


def _after(a, change, with_async=False):
    b = dict(a)
    if change == "stock_replica":
        b["stock"] = 1 - (1 - b["stock"]) ** 2
    elif change == "second_psp":
        b["psp"] = 1 - (1 - b["psp"]) ** 2
    elif change == "async_reserve":
        b["stock"] = 1.0
    elif change == "gateway_tier":
        b["gw"] = 0.9999
    return _chain(b, with_async)


def _p(x: float) -> str:
    return ru_num(round(100 * x, 3)) + " %"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, op = rng.choice(CONTEXTS)
    want = ORDER[seed % 4]
    for _ in range(20000):
        a = {"gw": rng.choice([0.995, 0.996, 0.997, 0.998]), "orders": rng.choice([0.9995, 0.999, 0.9985]),
             "psp": rng.choice([0.995, 0.996, 0.997, 0.998]), "stock": rng.choice([0.995, 0.996, 0.997, 0.998]),
             "notify": rng.choice([0.99, 0.993, 0.995])}
        target = rng.choice([0.993, 0.994, 0.995, 0.996, 0.997])
        if _chain(a) >= target:
            continue
        res = {c: _after(a, c) for c in ORDER}
        ok = [c for c in ORDER if res[c] >= target]
        strongest = max(ORDER, key=lambda c: res[c])
        bad = [c for c in ORDER if c not in ok]
        if want not in ok or want == strongest or not bad or min(abs(res[c] - target) for c in ORDER) < 2e-4:
            continue
        # ловушка: если умножить асинхронные уведомления, верное изменение кажется недостаточным
        if _after(a, want, True) >= target:
            continue
        # цены: дешевле верного — только недостаточные изменения (от одного до всех), остальные — дороже
        vals = sorted(rng.sample([60, 90, 120, 150, 180, 240, 300], 4))
        r = rng.randint(1, len(bad))
        cheaper = rng.sample(bad, r)
        dearer = [c for c in ORDER if c != want and c not in cheaper]
        rng.shuffle(cheaper)
        rng.shuffle(dearer)
        cost = dict(zip(cheaper + [want] + dearer, vals))
        good = min(ok, key=lambda c: cost[c])
        cheapest = min(ORDER, key=lambda c: cost[c])
        assert good == want and cheapest != good
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось построить вариант")
    rows = ["сервис | вызов | доступность (SLA)"]
    rows += [f"API-шлюз | синхронно | {_p(a['gw'])}", f"сервис заказов | синхронно | {_p(a['orders'])}",
             f"платёжный провайдер (внешний) | синхронно | {_p(a['psp'])}",
             f"сервис склада (резерв товара) | синхронно | {_p(a['stock'])}",
             f"сервис уведомлений | асинхронно, через очередь | {_p(a['notify'])}"]
    rows.append("изменение | цена в месяц")
    rows += [f"{IMPROVEMENTS[c]} | {cost[c]} тыс. руб." for c in ORDER]
    code = "\n".join(rows)
    stem = (f"{ctx.capitalize()}: операция «{op}» должна быть доступна не менее {_p(target)} времени (требование "
            f"бизнеса к нефункциональным характеристикам). Сервисы, которые вызывает операция, и их доступность — в "
            f"таблице; отказы сервисов независимы, переключение между экземплярами и провайдерами мгновенное, "
            f"бизнес согласен на асинхронный резерв товара. Какое одно изменение — самое дешёвое из тех, что "
            f"обеспечивают требование?")
    parts = "; ".join(f"{IMPROVEMENTS[c]} — {_p(res[c])} ({cost[c]} тыс. руб.)" for c in ORDER)
    why = (f"Доступность синхронной цепочки — произведение доступностей шлюза, заказов, платежей и склада: "
           f"{_p(_chain(a))} < {_p(target)}. Уведомления идут через очередь — их отказ не мешает операции, в "
           f"произведение они не входят (если их умножить, получится {_p(_chain(a, True))}, и верное изменение "
           f"покажется недостаточным: {_p(_after(a, good, True))}). После изменения: {parts}. Требованию отвечают: "
           f"{', '.join(IMPROVEMENTS[c] for c in ORDER if c in ok)}; самое дешёвое из них — "
           f"«{IMPROVEMENTS[good]}». Самое дешёвое вообще («{IMPROVEMENTS[cheapest]}») "
           f"{'не обеспечивает требование' if cheapest not in ok else 'обеспечивает его, но не самое дешёвое из подходящих'}"
           f", самое сильное («{IMPROVEMENTS[strongest]}») — дороже нужного. Для Lead: нефункциональное требование "
           f"переводится в бюджет доступности по цепочке, и выбирается достаточное, а не максимальное решение.")
    program = PROGRAM.format(a=a, cost=cost, target=target, names=IMPROVEMENTS)
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=IMPROVEMENTS[good],
                        distractors=[IMPROVEMENTS[c] for c in ORDER if c != good], program=program, why=why,
                        context=ctx, code=code, language="text", max_ratio=2.0,
                        note="Программа считает доступность синхронной цепочки после каждого изменения по тем же "
                             "числам и выбирает самое дешёвое из достаточных.",
                        params={"target": target, "good": good})
