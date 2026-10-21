"""backend.db.t21_sql_limit_offset_page_output — predict_output (набор t21, порог Стажёра): страница выдачи
через ORDER BY + LIMIT / OFFSET (SQLite).

Эндпоинт списка отдаёт вторую или третью страницу: `ORDER BY <поле> DESC|ASC LIMIT size OFFSET (page − 1) · size`.
Ловушки: OFFSET пропускает строки уже после сортировки, а не по id; направление сортировки; последняя страница
может быть неполной. Значения поля сортировки различны — порядок однозначен. Ключ — независимая модель (сортировка
и срез списка в генераторе); проверка — исполнение запроса в SQLite на данных из условия.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural, sql_inserts, text_table

FAMILY_ID = "backend.db.t21_sql_limit_offset_page_output"

# (контекст, таблица, колонка имени, колонка сортировки, имена, диапазон значений, шаг, эндпоинт)
CTX = [("каталог магазина", "products", "name", "price",
        ["кофе", "чай", "сахар", "мёд", "какао", "сироп", "печенье", "вафли", "джем", "орехи"], (90, 990), 10,
        "/products"),
       ("лента статей", "articles", "title", "views",
        ["postgres", "redis", "nginx", "python", "linux", "sqlite", "grpc", "celery", "pytest", "asyncio"],
        (100, 5000), 7, "/articles"),
       ("список заказов", "orders", "number", "amount",
        ["A-101", "A-102", "A-103", "A-104", "A-105", "A-106", "A-107", "A-108", "A-109", "A-110"], (300, 9000), 25,
        "/orders"),
       ("мониторинг серверов", "servers", "host", "cpu",
        ["web-1", "web-2", "web-3", "db-1", "db-2", "cache-1", "cache-2", "queue-1", "auth-1", "auth-2"], (5, 99), 1,
        "/servers")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, name_col, sort_col, names, (lo, hi), step, endpoint = rng.choice(CTX)
    n = rng.randint(7, 9)
    picked = rng.sample(names, n)
    values = rng.sample(range(lo, hi + 1, step), n)
    rows = [(i + 1, picked[i], values[i]) for i in range(n)]
    size = rng.randint(2, 4)
    max_page = (n + size - 1) // size
    page = rng.randint(2, max(2, max_page))
    offset = (page - 1) * size
    desc = rng.random() < 0.6
    direction = "DESC" if desc else "ASC"
    query = (f"SELECT {name_col}, {sort_col}\nFROM {table}\nORDER BY {sort_col} {direction}\n"
             f"LIMIT {size} OFFSET {offset};")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {name_col} TEXT NOT NULL, {sort_col} INTEGER NOT NULL);\n"
             + sql_inserts(table, ["id", name_col, sort_col], rows) + "\n")
    ordered = sorted(rows, key=lambda r: r[2], reverse=desc)
    page_rows = ordered[offset:offset + size]
    out = "\n".join(f"{r[1]}|{r[2]}" for r in page_rows)
    expl = (f"Сначала сортировка по {sort_col} {'по убыванию' if desc else 'по возрастанию'}: "
            + ", ".join(f"{r[1]} ({r[2]})" for r in ordered)
            + f". OFFSET {offset} пропускает первые {offset} {plural(offset, 'строку', 'строки', 'строк')} уже отсортированного списка, LIMIT {size} берёт "
              f"следующие {size}" + (f" — осталось только {len(page_rows)}" if len(page_rows) < size else "")
            + ": " + ", ".join(r[1] for r in page_rows) + ".")
    stem = (f"Сервис «{ctx}»: эндпоинт `GET {endpoint}?page={page}&size={size}` выполняет запрос к таблице "
            f"`{table}`:\n\n{table}\n{text_table(['id', name_col, sort_col], rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=query, out=out, explanation=expl, context=ctx,
                          params={"size": size, "page": page, "desc": desc}, language="sql",
                          files={"setup.sql": setup})
