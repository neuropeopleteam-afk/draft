"""analyst.python.t21_unit_profit_priority_output — predict_output (набор t21, порог Стажёра): приоритет
арифметических операций в формулах юнит-экономики.

Несколько целых входных величин (цена, себестоимость, число продаж, расходы) и две формулы прибыли: одна записана
без скобок (умножение выполняется раньше вычитания — получается совсем другое, часто отрицательное число), вторая —
со скобками. Ключ — независимый расчёт в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.python.t21_unit_profit_priority_output"

# (сюжет, имена: цена, себестоимость, количество, постоянные расходы), диапазоны
CTX = [
    ("партия товара в интернет-магазине", ("price", "cost", "qty", "ads"), (800, 3000, 50), (200, 600), (10, 60),
     (1000, 9000, 500)),
    ("подписка онлайн-сервиса за месяц", ("tariff", "support", "users", "infra"), (300, 900, 10), (50, 200),
     (40, 200), (2000, 20000, 1000)),
    ("кофейня за день", ("cup_price", "cup_cost", "cups", "rent"), (150, 400, 10), (40, 120), (60, 250),
     (3000, 12000, 500)),
    ("курс онлайн-школы за поток", ("fee", "lesson_cost", "students", "promo"), (5000, 20000, 1000), (1000, 4000),
     (10, 40), (20000, 90000, 5000)),
    ("служба доставки за смену", ("delivery_fee", "courier_pay", "orders", "fuel"), (150, 400, 10), (60, 200),
     (20, 80), (500, 3000, 100)),
]

TEMPLATES = ["minus_mul", "paren_minus"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, (P, C, Q, F), (p0, p1, ps), (c0, c1), (q0, q1), (f0, f1, fs) = rng.choice(CTX)
    t = rng.choice(TEMPLATES)
    p = rng.randrange(p0, p1 + 1, ps)
    c = rng.randrange(c0, min(c1, p - ps) + 1, 10)
    q = rng.randint(q0, q1)
    f = rng.randrange(f0, f1 + 1, fs)
    if t == "minus_mul":
        e1, v1 = f"{P} - {C} * {Q} - {F}", p - c * q - f
        e2, v2 = f"({P} - {C}) * {Q} - {F}", (p - c) * q - f
        trap = (f"в «{e1}» сначала умножение: {C} * {Q} = {c * q}, затем вычитания слева направо: "
                f"{p} - {c * q} - {f} = {v1}; в «{e2}» сначала скобка {p} - {c} = {p - c}, потом умножение на {q} "
                f"и вычитание {f}: {v2}")
    else:
        e1, v1 = f"{P} * {Q} - {C} * {Q} - {F}", p * q - c * q - f
        e2, v2 = f"{P} * {Q} - ({C} * {Q} - {F})", p * q - (c * q - f)
        trap = (f"в «{e1}» оба произведения считаются раньше вычитаний: {p * q} - {c * q} - {f} = {v1}; в «{e2}» "
                f"скобка {c * q} - {f} = {c * q - f} вычитается целиком, то есть {F} фактически прибавляется: {v2}")
    pair = [(e1, v1), (e2, v2)]
    if rng.random() < 0.5:
        pair.reverse()
    (e1, v1), (e2, v2) = pair
    names = rng.choice([("profit", "margin"), ("result_a", "result_b"), ("v1", "v2")])
    code = (f"{P} = {p}\n{C} = {c}\n{Q} = {q}\n{F} = {f}\n"
            f"{names[0]} = {e1}\n"
            f"{names[1]} = {e2}\n"
            f"print({names[0]}, {names[1]})")
    out = f"{v1} {v2}"
    stem = (f"Аналитик проверяет две формулы прибыли из старого отчёта ({plot}); программа считает обе по одним и "
            f"тем же входным числам.")
    expl = (f"Приоритет: * выполняется раньше + и −, операции одного приоритета — слева направо, скобки — первыми. "
            f"Здесь {trap}. Вывод: «{out}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"template": t, "p": p, "c": c, "q": q, "f": f}, language="python")
