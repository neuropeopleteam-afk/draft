"""data_eng.sql.t21_export_page_output — predict_output (набор t21, порог Стажёра): постраничная выгрузка
ORDER BY id LIMIT k OFFSET m.

Выгрузка таблицы страницами: запрос возвращает одну страницу. Таблица показана в порядке вставки (не по id), id идут
с пропусками. Ловушки чтения: OFFSET пропускает m строк после сортировки (а не «id больше m»), LIMIT — число строк;
последняя страница может быть неполной. Ключ — независимый отбор в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_export_page_output"

CTX = [("выгрузка клиентов в CRM-витрину", "customers", "city",
        ["Казань", "Пермь", "Омск", "Тула", "Сочи", "Уфа", "Тверь", "Псков", "Курск"]),
       ("перенос справочника складов", "warehouses", "region",
        ["север", "юг", "центр", "урал", "сибирь", "запад", "восток"]),
       ("выгрузка товаров для поиска", "products", "category",
        ["обувь", "книги", "игрушки", "посуда", "спорт", "сад", "техника", "одежда"]),
       ("перенос устройств в хранилище", "devices", "platform",
        ["android", "ios", "web", "tv", "watch", "desktop"]),
       ("выгрузка поставщиков", "suppliers", "country_code", ["RU", "KZ", "BY", "AM", "UZ", "KG", "TJ"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, col, values = rng.choice(CTX)
    n = rng.randint(7, 9)
    ids = sorted(rng.sample(range(3, 40), n))
    limit = rng.randint(2, 4)
    partial = rng.random() < 0.3
    if partial:
        offset = n - rng.randint(1, limit - 1)
    else:
        offset = rng.randint(2, n - limit)
    data = [(i, rng.choice(values)) for i in ids]
    shown = data[:]
    rng.shuffle(shown)
    code = f"SELECT id, {col}\nFROM {table}\nORDER BY id\nLIMIT {limit} OFFSET {offset};"
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {col} TEXT NOT NULL);\n"
             + sql_inserts(table, ["id", col], shown) + "\n")
    page = data[offset:offset + limit]
    out = "\n".join(f"{i}|{v}" for i, v in page)
    tail = (f"; после пропуска осталось {len(page)} {plural(len(page), 'строка', 'строки', 'строк')} — страница "
            "неполная" if len(page) < limit else "")
    expl = (f"Сначала ORDER BY id: {', '.join(str(i) for i in ids)}. OFFSET {offset} пропускает первые {offset} "
            f"{plural(offset, 'строку', 'строки', 'строк')} (это не условие id > {offset}), LIMIT {limit} берёт "
            f"следующие{tail}: "
            f"{', '.join(str(i) for i, _ in page)}.")
    stem = (f"Задача «{ctx}» переносит таблицу `{table}` страницами; запрос возвращает одну страницу. Строки "
            f"показаны в порядке вставки.\n\n{table}\n{text_table(['id', col], shown)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"limit": limit, "offset": offset, "rows": n, "partial": len(page) < limit},
                          language="sql", files={"setup.sql": setup})
