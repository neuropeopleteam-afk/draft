"""common.sql.count_nulls_output — predict_output: COUNT(*), COUNT(столбец) и COUNT(DISTINCT столбец) при NULL.

Лёгкое семейство у порога Junior (грейд «Стажёр»): одна таблица из 5–7 строк, часть значений NULL,
запрос возвращает одну строку с тремя счётчиками. Ловушка одна: COUNT(столбец) и COUNT(DISTINCT ...) не
считают NULL, COUNT(*) считает все строки. Исполняется SQLite; ключ — независимый подсчёт по данным.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.count_nulls_output"

# (контекст, таблица, столбец с NULL, значения, вторая колонка)
CONTEXTS = [("сотрудники", "employees", "manager_id", [1, 2, 3], "name", ["Анна", "Борис", "Вера", "Глеб", "Дарья", "Егор", "Жанна"]),
            ("заказы", "orders", "coupon", ["SALE10", "VIP", "NEW"], "customer", ["ivanov", "petrova", "sidorov", "orlova", "kim", "lee", "popov"]),
            ("книги", "books", "isbn", ["978-1", "978-2", "978-3"], "title", ["Дюна", "Солярис", "Гиперион", "Нейромант", "Основание", "Контакт", "Пикник"]),
            ("тикеты", "tickets", "assignee", ["alice", "bob", "carol"], "subject", ["вход", "оплата", "отчёт", "печать", "почта", "доступ", "экспорт"]),
            ("датчики", "sensors", "room", ["A1", "B2", "C3"], "code", ["S-01", "S-02", "S-03", "S-04", "S-05", "S-06", "S-07"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, col, values, col2, names = rng.choice(CONTEXTS)
    n = rng.randint(5, 7)
    while True:
        vals = [rng.choice(values + [None, None]) for _ in range(n)]
        n_null = sum(v is None for v in vals)
        n_non = n - n_null
        n_dist = len({v for v in vals if v is not None})
        if 1 <= n_null <= n - 2 and n_dist < n_non:  # есть NULL, есть повторы — все три числа различаются
            break
    rows = [(i + 1, names[i], vals[i]) for i in range(n)]
    typ = "INTEGER" if isinstance(values[0], int) else "TEXT"
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {col2} TEXT NOT NULL, {col} {typ});\n"
             + sql_inserts(table, ["id", col2, col], rows) + "\n")
    alias = rng.choice([("total", "with_value", "distinct_values"), ("n_rows", "n_filled", "n_unique"),
                        ("c_all", "c_col", "c_dist")])
    query = (f"SELECT COUNT(*) AS {alias[0]},\n       COUNT({col}) AS {alias[1]},\n"
             f"       COUNT(DISTINCT {col}) AS {alias[2]}\nFROM {table};")
    out = f"{n}|{n_non}|{n_dist}"
    stem = (f"SQL ({ctx}). Таблица `{table}`:\n\n{text_table(['id', col2, col], rows)}\n\n"
            f"Что вернёт запрос? Запишите значения через «|», как `7|5|3`.")
    why = (f"COUNT(*) считает все строки — {n}. COUNT({col}) пропускает NULL — остаётся {n_non}. "
           f"COUNT(DISTINCT {col}) считает различные значения без NULL — {n_dist}.")
    ak = AnswerKey(kind="output", value=out, explanation=why)
    checks = [Check(name="stdout", runner="sqlite", program=query, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=query, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"n": n, "nulls": n_null, "distinct": n_dist})
