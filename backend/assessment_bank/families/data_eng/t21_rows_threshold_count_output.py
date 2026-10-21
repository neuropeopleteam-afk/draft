"""data_eng.sql.t21_rows_threshold_count_output — predict_output (набор t21, порог Стажёра): COUNT(*) и SUM
с фильтром WHERE по статусу (`<>`) и порогу числа строк (`>=` или `>`).

Журнал ночных загрузок: запрос считает загрузки без статуса failed, в которых строк не меньше (или больше) порога,
и сумму их строк. Ловушки чтения: строка, равная порогу, попадает при `>=` и не попадает при `>`; `<> 'failed'`
оставляет и статус partial. Ключ — независимый подсчёт в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_rows_threshold_count_output"

CTX = [("выгрузка заказов из учётной системы", "order_loads"), ("загрузка кликов с сайта", "click_loads"),
       ("импорт справочника товаров", "catalog_loads"), ("перенос платежей в хранилище", "payment_loads"),
       ("загрузка логов приложений", "log_loads"), ("импорт остатков склада", "stock_loads")]
SOURCES = ["crm", "web", "app", "billing", "erp", "partners", "stores", "ads", "mobile", "kiosk"]
STATUSES = ["ok", "ok", "ok", "partial", "failed", "failed"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    op = rng.choice([">=", ">"])
    for _ in range(500):
        thr = rng.randrange(400, 1300, 100)
        n = rng.randint(7, 9)
        data = []
        for i in range(n):
            st = rng.choice(STATUSES)
            cnt = rng.randrange(100, 2050, 50)
            data.append((i + 1, rng.choice(SOURCES), st, cnt))
        # граница: хотя бы одна загрузка без ошибки ровно на пороге
        j = rng.randrange(n)
        data[j] = (data[j][0], data[j][1], rng.choice(["ok", "partial"]), thr)
        passes = (lambda c: c >= thr) if op == ">=" else (lambda c: c > thr)
        sel = [r for r in data if r[2] != "failed" and passes(r[3])]
        failed_big = [r for r in data if r[2] == "failed" and r[3] >= thr]
        partial_in = [r for r in sel if r[2] == "partial"]
        small = [r for r in data if r[2] != "failed" and r[3] < thr]
        if sel and failed_big and partial_in and small and len(sel) <= n - 3:
            break
    else:
        raise RuntimeError("t21_rows_threshold_count: не собрались данные")
    code = (f"SELECT COUNT(*), SUM(rows_loaded)\n"
            f"FROM {table}\n"
            f"WHERE status <> 'failed'\n"
            f"  AND rows_loaded {op} {thr};")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, source TEXT, status TEXT, rows_loaded INTEGER);\n"
             + sql_inserts(table, ["id", "source", "status", "rows_loaded"], data) + "\n")
    total = sum(r[3] for r in sel)
    out = f"{len(sel)}|{total}"
    ids = ", ".join(str(r[0]) for r in sel)
    edge = [r for r in data if r[3] == thr and r[2] != "failed"]
    edge_txt = (f"строка на пороге {thr} (id {', '.join(str(r[0]) for r in edge)}) "
                + ("попадает: условие `>=` включает границу" if op == ">=" else
                   "не попадает: условие `>` строгое"))
    expl = (f"Подходят строки с id {ids}: статус не failed (partial тоже проходит `<> 'failed'`) и rows_loaded {op} "
            f"{thr}; {edge_txt}. COUNT(*) = {len(sel)}, SUM = {total}, ответ «{out}».")
    stem = (f"Инженер данных проверяет журнал ночных загрузок ({ctx}): запрос считает подходящие загрузки и сумму "
            f"загруженных строк.\n\n{table}\n{text_table(['id', 'source', 'status', 'rows_loaded'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"op": op, "threshold": thr, "rows": n}, language="sql",
                          files={"setup.sql": setup})
