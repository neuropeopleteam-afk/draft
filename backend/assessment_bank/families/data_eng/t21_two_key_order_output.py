"""data_eng.sql.t21_two_key_order_output — predict_output (набор t21, порог Стажёра): ORDER BY по двум столбцам,
DESC относится только к своему столбцу.

Очередь задач загрузки: запрос выводит имена задач в порядке запуска — по приоритету и по времени ожидания.
Ловушка чтения: `ORDER BY priority, waited_min DESC` сортирует priority по возрастанию (DESC действует только на
waited_min), а в варианте `ORDER BY priority DESC, waited_min` — наоборот. Значения пар (priority, waited_min)
различны, поэтому порядок однозначен. Ключ — независимая сортировка в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_two_key_order_output"

CTX = [("ночное окно загрузок хранилища", "etl_queue"), ("очередь выгрузок для отчётов", "export_queue"),
       ("перезагрузка партиций после сбоя", "reload_queue"), ("синхронизация справочников", "sync_queue"),
       ("пересчёт витрин", "mart_queue")]
JOBS = ["orders_load", "users_sync", "clicks_load", "stock_load", "prices_sync", "payments_load", "geo_sync",
        "reviews_load", "sessions_load", "refunds_load", "promo_sync", "returns_load"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    desc_first = rng.random() < 0.4
    for _ in range(500):
        n = rng.randint(5, 7)
        names = rng.sample(JOBS, n)
        prios = [rng.randint(1, 3) for _ in range(n)]
        waits = rng.sample(range(2, 60), n)
        groups = {p: prios.count(p) for p in set(prios)}
        if len(groups) >= 2 and sum(1 for c in groups.values() if c >= 2) >= 2:
            break
    else:
        raise RuntimeError("t21_two_key_order: не собралась очередь")
    data = [(i + 1, names[i], prios[i], waits[i]) for i in range(n)]
    if desc_first:
        order = "priority DESC, waited_min"
        res = sorted(data, key=lambda r: (-r[2], r[3]))
    else:
        order = "priority, waited_min DESC"
        res = sorted(data, key=lambda r: (r[2], -r[3]))
    code = f"SELECT job\nFROM {table}\nORDER BY {order};"
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, job TEXT NOT NULL, priority INTEGER NOT NULL, "
             f"waited_min INTEGER NOT NULL);\n" + sql_inserts(table, ["id", "job", "priority", "waited_min"], data)
             + "\n")
    out = "\n".join(r[1] for r in res)
    if desc_first:
        rule = ("priority — по убыванию (DESC относится к нему), внутри одного приоритета waited_min — по возрастанию "
                "(направление по умолчанию ASC)")
    else:
        rule = ("priority — по возрастанию (у него нет DESC, по умолчанию ASC), внутри одного приоритета "
                "waited_min — по убыванию")
    expl = (f"Сортировка по двум ключам: {rule}. Получается: "
            + ", ".join(f"{r[1]} ({r[2]}, {r[3]})" for r in res) + ".")
    stem = (f"Планировщик ({ctx}) берёт задачи из таблицы `{table}`; запрос выводит имена задач в порядке "
            f"запуска.\n\n{table}\n{text_table(['id', 'job', 'priority', 'waited_min'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"order": order, "jobs": n}, language="sql", files={"setup.sql": setup})
