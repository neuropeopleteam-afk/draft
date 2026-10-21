"""analyst.python.t21_dau_slices_output — predict_output (набор t21, порог Стажёра): индексы и срезы списка
дневных метрик.

Список DAU (или заказов, выручки) по дням и три print: элементы по положительному и отрицательному индексу, сумма
среза `[a:b]` (правая граница не входит), длина и первый элемент «последней недели» `[-7:]`. Ловушки чтения: счёт
индексов с нуля, `-1` — последний элемент, правая граница среза не включается. Ключ — независимый расчёт в
генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.python.t21_dau_slices_output"

# (сюжет, имя списка, диапазон значений, шаг)
CTX = [
    ("активные пользователи приложения по дням", "dau", (100, 400), 1),
    ("заказы магазина по дням", "orders", (20, 90), 1),
    ("регистрации на сайте по дням", "signups", (10, 60), 1),
    ("выручка кофейни по дням в тысячах рублей", "revenue", (30, 120), 1),
    ("обращения в поддержку по дням", "tickets", (5, 50), 1),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, var, (lo, hi), step = rng.choice(CTX)
    n = rng.randint(9, 12)
    vals = [rng.randrange(lo, hi + 1, step) for _ in range(n)]
    i = rng.randint(1, 3)
    j = rng.randint(2, 3)
    a = rng.randint(1, n - 5)
    b = a + rng.randint(2, 3)
    w = rng.choice([5, 7])
    last = f"{var}[-{w}:]"
    code = (f"{var} = {vals}\n"
            f"print({var}[{i}], {var}[-{j}])\n"
            f"print(sum({var}[{a}:{b}]))\n"
            f"tail = {last}\n"
            f"print(len(tail), tail[0])")
    tail = vals[-w:]
    l1 = f"{vals[i]} {vals[-j]}"
    l2 = f"{sum(vals[a:b])}"
    l3 = f"{len(tail)} {tail[0]}"
    out = "\n".join([l1, l2, l3])
    stem = f"Аналитик разбирает ряд «{plot}» — список значений за {n} дней подряд, от первого дня к последнему."
    expl = (f"Индексы с нуля: {var}[{i}] = {vals[i]}, {var}[-{j}] — {j}-й с конца = {vals[-j]}. "
            f"Срез [{a}:{b}] берёт индексы {a}…{b - 1} (правая граница не входит): "
            + " + ".join(str(x) for x in vals[a:b]) + f" = {l2}. "
            f"{last} — последние {w} значений, первое из них — {tail[0]} (индекс {n - w}). Вывод по строкам: "
            f"«{l1}», «{l2}», «{l3}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"vals": vals, "i": i, "j": j, "a": a, "b": b, "w": w}, language="python")
