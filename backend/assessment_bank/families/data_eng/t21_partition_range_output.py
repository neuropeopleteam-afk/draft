"""data_eng.sql.t21_partition_range_output — predict_output (набор t21, порог Стажёра): выбор дневных партиций
по диапазону дат в WHERE и обратная сортировка ORDER BY ... DESC.

Таблица дневных партиций (дата в формате ГГГГ-ММ-ДД — строки сравниваются как даты). Запрос берёт партиции для
перезагрузки по диапазону с границами `>=`/`>` и `<`/`<=` и выводит их от новой к старой. Ловушки чтения: какая
граница включена, а какая нет, и порядок DESC. Ключ — независимый отбор в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_partition_range_output"

CTX = [("события мобильного приложения", "app_events_daily"), ("заказы интернет-магазина", "orders_daily"),
       ("клики по рекламе", "ad_clicks_daily"), ("показания датчиков склада", "sensor_daily"),
       ("логи платёжного шлюза", "payments_log_daily"), ("просмотры каталога", "catalog_views_daily")]
LOWER = {">=": lambda d, a: d >= a, ">": lambda d, a: d > a}
UPPER = {"<": lambda d, b: d < b, "<=": lambda d, b: d <= b}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    start = dt.date(2026, rng.randint(1, 12), rng.randint(1, 20))
    n = rng.randint(7, 9)
    days = [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]
    counts = [rng.randrange(1000, 9000, 10) for _ in range(n)]
    data = list(zip(days, counts))
    lo_op, hi_op = rng.choice([(">=", "<"), (">=", "<"), (">", "<="), (">=", "<=")])
    for _ in range(200):
        i = rng.randint(1, n - 4)
        j = rng.randint(i + 2, min(n - 1, i + 4))
        sel = [r for r in data if LOWER[lo_op](r[0], days[i]) and UPPER[hi_op](r[0], days[j])]
        if 2 <= len(sel) <= 4:
            break
    else:
        raise RuntimeError("t21_partition_range: не собрался диапазон")
    code = (f"SELECT dt, row_count\n"
            f"FROM {table}\n"
            f"WHERE dt {lo_op} '{days[i]}' AND dt {hi_op} '{days[j]}'\n"
            f"ORDER BY dt DESC;")
    setup = (f"CREATE TABLE {table} (dt TEXT PRIMARY KEY, row_count INTEGER NOT NULL);\n"
             + sql_inserts(table, ["dt", "row_count"], data) + "\n")
    res = sorted(sel, key=lambda r: r[0], reverse=True)
    out = "\n".join(f"{d}|{c}" for d, c in res)
    lo_txt = "включена (>=)" if lo_op == ">=" else "не включена (>)"
    hi_txt = "включена (<=)" if hi_op == "<=" else "не включена (<)"
    expl = (f"Нижняя граница {days[i]} {lo_txt}, верхняя {days[j]} {hi_txt}: подходят партиции "
            f"{', '.join(d for d, _ in sel)}. ORDER BY dt DESC выводит их от новой к старой: "
            f"{', '.join(d for d, _ in res)}.")
    stem = (f"Перед перезагрузкой партиций ({ctx}) инженер данных выбирает дни из таблицы `{table}` по диапазону "
            f"дат.\n\n{table}\n{text_table(['dt', 'row_count'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"ops": [lo_op, hi_op], "days": n, "selected": len(sel)}, language="sql",
                          files={"setup.sql": setup})
