"""data_eng.etl.t21_new_rows_antijoin_output — predict_output (набор t21, порог Junior): отбор новых строк для
вставки через LEFT JOIN ... WHERE ключ правой таблицы IS NULL (антиджойн).

Инкрементальная загрузка: из промежуточной таблицы `staging` берутся строки, которых ещё нет в целевой таблице.
Соединение идёт либо по id, либо по натуральному ключу (email / sku / serial) — от этого зависит, что считается
«новым»: при соединении по id строка с изменённым значением не новая, при соединении по значению — новая, а строка
с новым id, но уже известным значением, — нет. Ключ — независимый отбор в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.etl.t21_new_rows_antijoin_output"

CTX = [("справочник клиентов", "customers", "email",
        ["anna@mail.ru", "boris@ya.ru", "vera@mail.ru", "gleb@inbox.ru", "dina@ya.ru", "egor@mail.ru", "ilya@bk.ru",
         "kira@ya.ru", "lev@mail.ru", "mila@inbox.ru"]),
       ("каталог товаров", "products", "sku",
        ["SKU-101", "SKU-117", "SKU-204", "SKU-233", "SKU-310", "SKU-342", "SKU-415", "SKU-478", "SKU-503",
         "SKU-561"]),
       ("реестр устройств", "devices", "serial",
        ["SN-7A1", "SN-7B4", "SN-8C2", "SN-8D9", "SN-9E3", "SN-9F6", "SN-A10", "SN-A27", "SN-B05", "SN-B38"]),
       ("справочник поставщиков", "suppliers", "inn",
        ["7701001", "7702013", "7703025", "7704037", "7705049", "7706051", "7707063", "7708075", "7709087",
         "7710099"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, col, pool = rng.choice(CTX)
    by_id = rng.random() < 0.5
    key = "id" if by_id else col
    for _ in range(500):
        vals = rng.sample(pool, len(pool))
        n_t = rng.randint(4, 5)
        target_ids = sorted(rng.sample(range(1, 30), n_t))
        target = [(target_ids[i], vals[i]) for i in range(n_t)]
        spare = vals[n_t:]
        staging = []
        t_same = rng.choice(target)
        staging.append(t_same)                                   # без изменений
        t_chg = rng.choice([t for t in target if t != t_same])
        staging.append((t_chg[0], spare.pop()))                  # тот же id, новое значение
        used_ids = set(target_ids)
        free_ids = [i for i in range(30, 60) if i not in used_ids]
        rng.shuffle(free_ids)
        t_val = rng.choice([t for t in target if t not in (t_same, t_chg)])
        staging.append((free_ids.pop(), t_val[1]))              # новый id, известное значение
        for _ in range(rng.randint(1, 2)):
            staging.append((free_ids.pop(), spare.pop()))        # полностью новая строка
        staging.sort()
        t_keys = {t[0] if by_id else t[1] for t in target}
        res = [s for s in staging if (s[0] if by_id else s[1]) not in t_keys]
        if 1 <= len(res) <= 4 and len(res) < len(staging):
            break
    else:
        raise RuntimeError("t21_new_rows_antijoin: не собрались данные")
    code = (f"SELECT s.id, s.{col}\n"
            f"FROM staging s\n"
            f"LEFT JOIN {table} t ON t.{key} = s.{key}\n"
            f"WHERE t.id IS NULL\n"
            f"ORDER BY s.id;")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {col} TEXT NOT NULL);\n"
             f"CREATE TABLE staging (id INTEGER PRIMARY KEY, {col} TEXT NOT NULL);\n"
             + sql_inserts(table, ["id", col], target) + "\n" + sql_inserts("staging", ["id", col], staging) + "\n")
    out = "\n".join(f"{i}|{v}" for i, v in res)
    if by_id:
        why = (f"соединение по id: строка {t_chg[0]} с изменённым {col} находит пару и не считается новой, а строка "
               f"с новым id и уже известным {col} — новая")
    else:
        why = (f"соединение по {col}: строка {t_chg[0]} с изменённым {col} пары не находит и попадает в результат, "
               f"а строка с новым id, но известным {col}, пару находит и отсекается")
    expl = (f"LEFT JOIN оставляет все строки staging; у строк без пары столбцы t.* равны NULL, и WHERE t.id IS NULL "
            f"оставляет только их. Здесь {why}. Результат: " + "; ".join(f"{i}|{v}" for i, v in res) + ".")
    stem = (f"Инкрементальная загрузка ({ctx}): запрос выбирает из `staging` строки для вставки в `{table}`.\n\n"
            f"{table}\n{text_table(['id', col], target)}\n\nstaging\n{text_table(['id', col], staging)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"join_key": key, "staging": len(staging), "target": n_t}, language="sql",
                          files={"setup.sql": setup})
