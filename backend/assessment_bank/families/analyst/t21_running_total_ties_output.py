"""analyst.sql.t21_running_total_ties_output — predict_output (набор t21, порог Senior): накопительная сумма с
рамкой окна по умолчанию (RANGE) и с явной рамкой ROWS при равных датах.

Таблица (платежи, заказы, пожертвования, начисления бонусов) — несколько строк в один день, id не обязательно
идут в порядке дат. Запрос считает две накопительные суммы: `OVER (ORDER BY day)` — рамка по умолчанию RANGE …
CURRENT ROW, она включает все строки с той же датой (одинаковая сумма у всей «ничьей»), и `OVER (ORDER BY day, id
ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` — построчно. Вывод — по id. Ключ — независимый расчёт в
генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_running_total_ties_output"

# (таблица, сюжет, числовая колонка, сетка, алиасы)
CTX = [
    ("payments", "Платежи подписчиков за первые дни месяца", "amount", list(range(100, 1001, 50)),
     ("total_default", "total_rows")),
    ("orders", "Заказы магазина за начало недели", "revenue", list(range(200, 3001, 100)),
     ("cum_default", "cum_rows")),
    ("donations", "Пожертвования в фонд за несколько дней", "amount", list(range(50, 801, 50)),
     ("running_a", "running_b")),
    ("bonuses", "Начисления бонусных баллов клиентам", "points", list(range(10, 301, 10)),
     ("acc_default", "acc_rows")),
]
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-09", "2026-10", "2026-11"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, num, grid, (a1, a2) = rng.choice(CTX)
    month = rng.choice(MONTHS)
    for _ in range(500):
        n = rng.randint(5, 6)
        n_days = rng.randint(3, 4)
        d0 = rng.randint(1, 20)
        days = sorted(rng.sample(range(d0, d0 + 7), n_days))
        day_of = [rng.choice(days) for _ in range(n)]
        if len(set(day_of)) < 3:
            continue
        cnt = {d: day_of.count(d) for d in set(day_of)}
        if max(cnt.values()) < 2:
            continue
        if rng.random() < 0.5:
            day_of.sort()
        ids = list(range(1, n + 1))
        rows = [(i, f"{month}-{d:02d}", rng.choice(grid)) for i, d in zip(ids, day_of)]
        break
    else:
        raise RuntimeError("t21_running_total_ties: не собрались данные")
    order = sorted(rows, key=lambda r: (r[1], r[0]))
    rows_sum, acc = {}, 0
    for r in order:
        acc += r[2]
        rows_sum[r[0]] = acc
    range_sum = {r[0]: sum(x[2] for x in rows if x[1] <= r[1]) for r in rows}
    code = (f"SELECT id,\n"
            f"       SUM({num}) OVER w_default AS {a1},\n"
            f"       SUM({num}) OVER w_rows AS {a2}\n"
            f"FROM {T}\n"
            f"WINDOW w_default AS (ORDER BY day),\n"
            f"       w_rows AS (ORDER BY day, id\n"
            f"                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)\n"
            f"ORDER BY id;")
    out = "\n".join(f"{r[0]}|{range_sum[r[0]]}|{rows_sum[r[0]]}" for r in rows)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, day TEXT NOT NULL, {num} INTEGER NOT NULL);\n"
             + sql_inserts(T, ["id", "day", num], rows) + "\n")
    stem = (f"{plot}: запрос считает накопительную сумму {num} двумя способами.\n\n"
            f"{T}\n{text_table(['id', 'day', num], rows)}")
    ties = sorted({r[1] for r in rows if sum(1 for x in rows if x[1] == r[1]) > 1})
    tie_txt = "; ".join(f"{d}: id " + ", ".join(str(r[0]) for r in order if r[1] == d) for d in ties)
    expl = (f"В {a1} окно задано только ORDER BY day — рамка по умолчанию RANGE BETWEEN UNBOUNDED PRECEDING AND "
            f"CURRENT ROW: в неё входят все строки с той же датой, поэтому у строк одного дня сумма одинаковая — до "
            f"конца дня ({tie_txt}). В {a2} рамка ROWS идёт построчно в порядке (day, id): "
            + ", ".join(f"id {r[0]} → {rows_sum[r[0]]}" for r in order)
            + ". Вывод по id: " + "; ".join(out.splitlines()) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows}, language="sql", files={"setup.sql": setup})
