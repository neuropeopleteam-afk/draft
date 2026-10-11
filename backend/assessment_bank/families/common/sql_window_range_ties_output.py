"""common.sql.window_range_ties_output — predict_output: накопительный итог окна при равных значениях ORDER BY.

Порог Middle/Senior. `SUM(...) OVER (ORDER BY day)` без явной рамки — рамка RANGE BETWEEN UNBOUNDED PRECEDING AND
CURRENT ROW: строки с тем же `day` (peers) входят в итог друг друга, и у них одинаковый накопленный итог и счётчик.
Распространённое ожидание — «итог растёт на каждой строке». В данных 1–2 группы равных дат. Один механизм.
Ключ — независимая модель в генераторе (сумма по строкам с day ≤ текущего), сверяется с SQLite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.window_range_ties_output"

CONTEXTS = [("платежи клиента", "payments", "amount"), ("поступления на склад", "receipts", "qty"),
            ("заказы магазина", "orders", "total"), ("часы по задачам", "timesheet", "hours"),
            ("продажи по дням", "sales", "revenue"), ("пополнения кошелька", "topups", "amount")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, col = rng.choice(CONTEXTS)
    n = rng.randint(5, 6)
    while True:
        days = sorted(rng.choice([1, 2, 3, 4, 5, 6, 7]) for _ in range(n))
        groups = {d: days.count(d) for d in days}
        ties = sum(1 for c in groups.values() if c > 1)
        if 1 <= ties <= 2 and max(groups.values()) <= 3:
            break
    amounts = [rng.randint(1, 20) * rng.choice([5, 10]) for _ in range(n)]
    ids = list(range(1, n + 1))
    order = ids[:]
    rng.shuffle(order)
    rows = [(i, f"2026-10-0{days[k]}", amounts[k]) for k, i in enumerate(order)]
    rows.sort()
    run_alias, cnt_alias = rng.choice([("running", "n_so_far"), ("cum_total", "cum_rows"), ("acc", "k")])
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, day TEXT NOT NULL, {col} INTEGER NOT NULL);\n"
             + sql_inserts(table, ["id", "day", col], rows) + "\n")
    query = (f"SELECT id,\n       SUM({col}) OVER (ORDER BY day) AS {run_alias},\n"
             f"       COUNT(*) OVER (ORDER BY day) AS {cnt_alias}\nFROM {table}\nORDER BY id;")
    out_lines = []
    for i, d, a in rows:
        s = sum(a2 for _, d2, a2 in rows if d2 <= d)
        c = sum(1 for _, d2, _ in rows if d2 <= d)
        out_lines.append(f"{i}|{s}|{c}")
    out = "\n".join(out_lines)
    stem = (f"SQL ({ctx}). Таблица `{table}`:\n\n{text_table(['id', 'day', col], rows)}\n\n"
            f"Что вернёт запрос (SQLite)? Запишите строки результата, значения через «|», например `1|50|1`.")
    why = ("У окна с ORDER BY без явной рамки рамка по умолчанию — RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW: "
           "в неё входят все строки с тем же значением `day` (равные по сортировке). Поэтому у строк одной даты "
           "одинаковые накопленная сумма и счётчик — сумма всех строк до этой даты включительно. Чтобы итог рос по "
           "строкам, нужна рамка ROWS и однозначный порядок (`ORDER BY day, id`).")
    ak = AnswerKey(kind="output", value=out, explanation=why)
    checks = [Check(name="stdout", runner="sqlite", program=query, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=query, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"days": days, "ties": ties})
