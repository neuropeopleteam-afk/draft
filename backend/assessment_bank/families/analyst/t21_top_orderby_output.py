"""analyst.sql.t21_top_orderby_output — predict_output (набор t21, порог Стажёра): ORDER BY по убыванию с
вторым ключом и LIMIT.

Таблица (менеджеры, магазины, авторы, курьеры, товары) и запрос `ORDER BY metric DESC, name LIMIT k`. На границе
k всегда стоит ничья по метрике, и в таблице первым записан тот, кто по имени идёт позже: DESC относится только к
первому ключу, ничью решает имя по возрастанию, а не порядок строк. Ключ — независимая сортировка в генераторе;
проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_top_orderby_output"

PEOPLE = ["Анна", "Борис", "Вера", "Глеб", "Дина", "Егор", "Жанна", "Зоя", "Илья", "Кира", "Лиза", "Марк", "Нина",
          "Олег", "Павел", "Роман", "Света", "Тимур", "Ульяна"]
CITIES = ["Казань", "Пермь", "Омск", "Тула", "Сочи", "Уфа", "Тверь", "Курск", "Липецк", "Самара", "Иркутск"]
SKUS = ["A-101", "A-117", "B-220", "B-204", "C-310", "C-333", "D-415", "E-502", "F-618", "K-707"]

# (таблица, сюжет, колонка имени, имена, метрика, сетка значений)
CTX = [
    ("sales", "Сделки менеджеров отдела продаж за месяц", "manager", PEOPLE, "deals", list(range(3, 41))),
    ("stores", "Выручка магазинов сети за неделю (тыс. руб.)", "store", CITIES, "revenue", list(range(100, 901, 10))),
    ("articles", "Просмотры статей блога за квартал по авторам", "author", PEOPLE, "views",
     list(range(200, 5001, 50))),
    ("couriers", "Доставки курьеров за смену", "courier", PEOPLE, "deliveries", list(range(5, 41))),
    ("products", "Заказы товаров витрины за день", "sku", SKUS, "orders", list(range(1, 61))),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, name, pool, metric, grid = rng.choice(CTX)
    n = rng.randint(6, 8)
    k = rng.randint(2, min(4, n - 2))
    for _ in range(500):
        names = rng.sample(pool, n)
        a, b = sorted(rng.sample(names, 2))            # a < b по имени, у обоих одинаковая метрика
        rest = [x for x in names if x not in (a, b)]
        it = rng.randrange(len(grid) // 3, 2 * len(grid) // 3)
        v_tie = grid[it]
        hi_vals = rng.sample(grid[it + 1:], k - 1)
        lo_vals = rng.sample(grid[:it], n - k - 1)
        vals = dict(zip(rest, hi_vals + lo_vals))
        vals[a] = vals[b] = v_tie
        order = rng.sample(names, n)
        if order.index(b) < order.index(a):
            break
    else:
        raise RuntimeError("t21_top_orderby: не собрались данные")
    rows = [(x, vals[x]) for x in order]
    top = sorted(rows, key=lambda r: (-r[1], r[0]))[:k]
    asc = rng.choice(["", " ASC"])
    code = f"SELECT {name}, {metric}\nFROM {T}\nORDER BY {metric} DESC, {name}{asc}\nLIMIT {k};"
    out = "\n".join(f"{x}|{v}" for x, v in top)
    setup = (f"CREATE TABLE {T} ({name} TEXT PRIMARY KEY, {metric} INTEGER NOT NULL);\n"
             + sql_inserts(T, [name, metric], rows) + "\n")
    stem = (f"{plot}: для отчёта выбирают первые строки рейтинга по {metric}.\n\n"
            f"{T}\n{text_table([name, metric], rows)}")
    expl = (f"Сортировка по {metric} по убыванию; DESC относится только к {metric}, второй ключ {name} — по "
            f"возрастанию. На {k}-м месте ничья {a} и {b} ({metric} = {v_tie}): выше идёт {a} (раньше по {name}), "
            f"хотя в таблице строка {b} стоит выше. LIMIT {k} отрезает остальных. Ответ: "
            + "; ".join(f"{x}|{v}" for x, v in top) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "k": k}, language="sql", files={"setup.sql": setup})
