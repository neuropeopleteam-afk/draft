"""frontend.cart.t21_cart_sum_output — predict_output (набор t21, порог Стажёра): цикл с суммой по массиву объектов
корзины.

Корзина — массив объектов { price, qty }; цикл (for…of или классический for по индексу) накапливает сумму
price * qty и счётчик: в одних вариантах число штук (`count += qty`), в других — число позиций (`count++`).
Ловушки: умножение на количество внутри суммы, различие «штуки / позиции». Ключ — независимый подсчёт
в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.cart.t21_cart_sum_output"

CTX = [("корзина интернет-магазина", "cart", [190, 250, 350, 490, 590, 990, 1200]),
       ("заказ билетов", "tickets", [300, 450, 600, 800, 1100]),
       ("доставка еды", "order", [120, 180, 240, 320, 390, 450]),
       ("магазин курсов", "basket", [500, 900, 1500, 2000, 2500]),
       ("сувенирная лавка", "items", [60, 80, 150, 210, 270])]
TOTALS = ["total", "sum", "amount"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr, prices = rng.choice(CTX)
    m = rng.randint(3, 4)
    rows = []
    for _ in range(200):
        rows = [(rng.choice(prices), rng.randint(1, 4)) for _ in range(m)]
        if any(q > 1 for _p, q in rows):
            break
    tot = rng.choice(TOTALS)
    units = rng.random() < 0.6
    lit = ", ".join(f"{{ price: {p}, qty: {q} }}" for p, q in rows)
    if rng.random() < 0.5:
        loop = [f"for (const item of {arr}) {{", f"  {tot} += item.price * item.qty;",
                "  count += item.qty;" if units else "  count++;", "}"]
    else:
        loop = [f"for (let i = 0; i < {arr}.length; i++) {{", f"  {tot} += {arr}[i].price * {arr}[i].qty;",
                f"  count += {arr}[i].qty;" if units else "  count++;", "}"]
    code = "\n".join([f"const {arr} = [{lit}];", f"let {tot} = 0;", "let count = 0;"] + loop +
                     [f"console.log(count, {tot});"])
    s = sum(p * q for p, q in rows)
    c = sum(q for _p, q in rows) if units else len(rows)
    out = f"{c} {s}"
    parts = " + ".join(f"{p}·{q}" for p, q in rows)
    cnt_note = (f"count складывает количества: {' + '.join(str(q) for _p, q in rows)} = {c}" if units else
                f"count++ считает позиции (объекты массива), а не штуки: {c}")
    expl = (f"Цикл проходит все {m} объекта: {tot} = {parts} = {s}; {cnt_note}. "
            f"console.log печатает через пробел: «{out}».")
    stem = f"Интерфейс ({ctx}): программа считает итог заказа и счётчик для значка корзины."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"rows": rows, "units": units}, language="javascript")
