"""analyst.sql.t21_between_count_output — predict_output (набор t21, порог Стажёра): COUNT(*) и SUM по строкам,
отобранным WHERE с равенством и BETWEEN.

Небольшая таблица (заказы, сессии, звонки, заявки, доставки) и запрос `SELECT COUNT(*), SUM(x) ... WHERE cat = '…'
AND x BETWEEN lo AND hi`. Ловушки чтения: BETWEEN включает обе границы (в данных всегда есть значения ровно на
границах), строки другой категории в диапазоне не считаются. Ключ — независимый подсчёт в генераторе; проверка —
исполнение показанного запроса в песочнице sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_between_count_output"

# (таблица, сюжет, колонка категории, категории, числовая колонка, шаг сетки, мин, макс, как назвать сумму)
CTX = [
    ("orders", "Заказы интернет-магазина за день", "city", ["Казань", "Пермь", "Омск", "Тула"], "amount",
     100, 300, 6000, "total_amount"),
    ("sessions", "Сессии мобильного приложения за час", "platform", ["ios", "android", "web"], "minutes",
     1, 1, 40, "total_minutes"),
    ("calls", "Звонки в колл-центр за смену", "line", ["sales", "support", "billing"], "wait_sec",
     10, 10, 400, "total_wait"),
    ("applications", "Заявки на кредитную карту за утро", "region", ["Самара", "Тверь", "Уфа", "Курск"], "score",
     10, 350, 900, "total_score"),
    ("deliveries", "Доставки курьерской службы за вечер", "zone", ["north", "south", "center"], "minutes",
     5, 10, 120, "total_minutes"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, cat, cats, val, step, vmin, vmax, sum_alias = rng.choice(CTX)
    grid = list(range(vmin, vmax + 1, step))
    for _ in range(500):
        i_lo = rng.randrange(2, len(grid) // 2)
        i_hi = rng.randrange(i_lo + 3, len(grid) - 2)
        lo, hi = grid[i_lo], grid[i_hi]
        target = rng.choice(cats)
        others = [c for c in cats if c != target]
        n = rng.randint(7, 9)
        rows = []
        rid = rng.randint(1, 40)
        for _k in range(n):
            rid += rng.randint(1, 4)
            c = target if rng.random() < 0.6 else rng.choice(others)
            kind = rng.choice(["lo", "hi", "in", "in", "in", "below", "above"])
            if kind == "lo":
                v = lo
            elif kind == "hi":
                v = hi
            elif kind == "in":
                v = grid[rng.randint(i_lo + 1, i_hi - 1)]
            elif kind == "below":
                v = grid[rng.randint(0, i_lo - 1)]
            else:
                v = grid[rng.randint(i_hi + 1, len(grid) - 1)]
            rows.append((rid, c, v))
        sel = [r for r in rows if r[1] == target and lo <= r[2] <= hi]
        edge = [r for r in sel if r[2] in (lo, hi)]
        out_t = [r for r in rows if r[1] == target and not lo <= r[2] <= hi]
        in_o = [r for r in rows if r[1] != target and lo <= r[2] <= hi]
        inner = [r for r in sel if lo < r[2] < hi]
        if len(sel) >= 2 and edge and inner and out_t and in_o and len(sel) < len(rows) - 2:
            break
    else:
        raise RuntimeError("t21_between_count: не собрались данные")
    n_alias = rng.choice(["n", "cnt", "rows_cnt"])
    conds = [f"{cat} = '{target}'", f"{val} BETWEEN {lo} AND {hi}"]
    if rng.random() < 0.4:
        conds.reverse()
    code = (f"SELECT COUNT(*) AS {n_alias}, SUM({val}) AS {sum_alias}\n"
            f"FROM {T}\n"
            f"WHERE {conds[0]}\n"
            f"  AND {conds[1]};")
    cnt, total = len(sel), sum(r[2] for r in sel)
    out = f"{cnt}|{total}"
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {cat} TEXT NOT NULL, {val} INTEGER NOT NULL);\n"
             + sql_inserts(T, ["id", cat, val], rows) + "\n")
    stem = (f"{plot}: запрос считает строки с {cat} = '{target}', у которых {val} попадает в диапазон, "
            f"и их сумму.\n\n{T}\n{text_table(['id', cat, val], rows)}")
    ids = ", ".join(str(r[0]) for r in sel)
    edges = ", ".join(f"id {r[0]} ({val} = {r[2]})" for r in edge)
    expl = (f"Подходят строки {cat} = '{target}' с {val} от {lo} до {hi}: id {ids} — COUNT(*) = {cnt}, "
            f"сумма {val} = {total}. Ловушка: BETWEEN включает обе границы, поэтому строки ровно на границе "
            f"({edges}) тоже учитываются; строки другой категории в диапазоне не считаются. Ответ: «{out}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "lo": lo, "hi": hi, "target": target}, language="sql",
                          files={"setup.sql": setup})
