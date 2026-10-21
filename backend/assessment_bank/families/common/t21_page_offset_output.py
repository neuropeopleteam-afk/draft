"""common.sql.t21_page_offset_output — predict_output (набор t21, порог Стажёр): страница выдачи
``ORDER BY key, name LIMIT size OFFSET (page - 1) * size`` при равных значениях ключа сортировки.

Таблица из 7–10 строк (товары, вакансии, статьи, курсы, отели) показана в порядке вставки. Запрос сортирует по
основному ключу (по варианту DESC или ASC) и вторым ключом name — он разводит равные значения, поэтому порядок
однозначен, — затем отбрасывает (page − 1) * size строк и берёт size. В данных всегда есть группа равных значений
основного ключа на границе страницы, а запрошенная страница по варианту полная или последняя неполная. Ловушки:
OFFSET считает пропускаемые строки от 0 (страница 2 начинается с size + 1-й строки), сортировка выполняется до
LIMIT, равные значения упорядочивает второй ключ, последняя страница короче size. Отличие от
backend.db.t21_sql_limit_offset_page_output и data_eng.sql.t21_export_page_output (один ключ без равных, OFFSET
числом): здесь два ключа сортировки с равными значениями на границе и OFFSET выражением от номера страницы. Ключ —
независимая сортировка в генераторе; проверка — исполнение показанного запроса в песочнице sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "common.sql.t21_page_offset_output"

# (таблица, сюжет, эндпоинт, имена, числовой ключ, значения ключа)
CTX = [("products", "каталог интернет-магазина", "GET /products",
        ["lamp", "sofa", "desk", "chair", "shelf", "mirror", "rug", "stool", "bench", "vase", "clock"],
        "price", [990, 1490, 1990, 2490, 2990, 3490]),
       ("vacancies", "поиск вакансий", "GET /vacancies",
        ["analyst", "backend", "designer", "devops", "frontend", "mobile", "qa", "support", "teamlead", "writer"],
        "salary", [90000, 120000, 150000, 180000, 210000]),
       ("articles", "блог компании", "GET /articles",
        ["asyncio", "celery", "docker", "grpc", "nginx", "pytest", "redis", "sqlite", "typing", "vite"],
        "likes", [12, 30, 45, 58, 73, 90]),
       ("courses", "каталог онлайн-курсов", "GET /courses",
        ["algebra", "biology", "chemistry", "design", "english", "finance", "history", "logic", "music", "python"],
        "rating", [41, 43, 45, 47, 49]),
       ("hotels", "бронирование отелей", "GET /hotels",
        ["atlas", "breeze", "cedar", "dune", "ember", "fjord", "grove", "harbor", "iris", "jade"],
        "reviews", [15, 40, 85, 120, 260, 310])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, ep, names, key, vals = rng.choice(CTX)
    desc = rng.random() < 0.6
    for _ in range(3000):
        n = rng.randint(7, 10)
        size = rng.randint(2, 4)
        page = rng.choice([2, 2, 3])
        off = (page - 1) * size
        if off >= n:
            continue
        nm = rng.sample(names, n)
        kv = [rng.choice(vals) for _ in range(n)]
        rows = list(zip(range(1, n + 1), nm, kv))
        # модель: сортировка по ключу (DESC/ASC), равные — по name по возрастанию (сравнение строк латиницы)
        order = sorted(rows, key=lambda r: ((-r[2] if desc else r[2]), r[1]))
        page_rows = order[off:off + size]
        # граница страницы проходит внутри группы равных значений (сверху или снизу)
        cut_top = off > 0 and order[off - 1][2] == order[off][2]
        end = off + len(page_rows)
        cut_bottom = end < n and order[end - 1][2] == order[end][2]
        if not (cut_top or cut_bottom):
            continue
        # равные значения в порядке вставки идут НЕ по алфавиту — иначе второй ключ не виден
        grp = [r for r in rows if r[2] == (order[off][2] if cut_top else order[end - 1][2])]
        if [r[1] for r in grp] == sorted(r[1] for r in grp):
            continue
        partial = len(page_rows) < size
        if rng.random() < 0.25 and not partial:
            continue                      # чаще встречается и последняя неполная страница
        break
    else:
        raise RuntimeError("t21_page_offset: не собрались данные")
    direction = " DESC" if desc else ""
    code = (f"SELECT name, {key}\n"
            f"FROM {T}\n"
            f"ORDER BY {key}{direction}, name\n"
            f"LIMIT {size} OFFSET ({page} - 1) * {size};")
    out = "\n".join(f"{r[1]}|{r[2]}" for r in page_rows)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, name TEXT NOT NULL, {key} INTEGER NOT NULL);\n"
             + sql_inserts(T, ["id", "name", key], rows) + "\n")
    stem = (f"Эндпоинт `{ep}?page={page}&size={size}` ({plot}) отдаёт одну страницу выдачи: в запрос подставлены "
            f"page и size.\n\n{T}\n{text_table(['id', 'name', key], rows)}")
    srt = ", ".join(f"{r[1]}({r[2]})" for r in order)
    tie_v = order[off][2] if cut_top else order[end - 1][2]
    expl = (f"Сначала сортировка: {key}{' по убыванию' if desc else ' по возрастанию'}, при равных {key} — name по "
            f"алфавиту: {srt}. OFFSET ({page} - 1) * {size} = {off} пропускает первые {off} строк, LIMIT {size} берёт "
            f"строки с {off + 1}-й" + (f" — осталось только {len(page_rows)}, страница последняя" if partial else "")
            + f": {', '.join(r[1] for r in page_rows)}. Граница страницы проходит внутри группы {key} = {tie_v}, "
            f"и какие из них попадут на страницу, решает второй ключ name. Ловушка — считать OFFSET {page * size} "
            f"или брать равные строки в порядке вставки.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": [list(r) for r in rows], "page": page, "size": size, "desc": desc},
                          language="sql", files={"setup.sql": setup})
