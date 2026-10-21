"""data_eng.sql.t21_recursive_gaps_output — predict_output (набор t21, порог Senior): рекурсивный CTE строит
календарь дней, LEFT JOIN ... IS NULL находит дни без загрузки (пропущенные партиции для дозагрузки).

Рекурсия `SELECT date(d, '+1 day') FROM days WHERE d < 'конец'` (или `<=`) останавливается по условию на ПРЕДЫДУЩЕМ
дне: при `<` последний построенный день — сама граница, при `<=` — следующий за ней. Ловушки: где кончается
календарь, загрузки вне календаря не влияют, несколько загрузок за день не дают дублей в ответе (строки с парой
отбрасываются). Ключ — независимая модель календаря в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_recursive_gaps_output"

CTX = [("дневные партиции заказов", "order_loads"), ("выгрузки кликов", "click_loads"),
       ("снимки остатков склада", "stock_loads"), ("логи платёжного шлюза", "payment_loads"),
       ("события приложения", "event_loads")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    op = rng.choice(["<", "<="])
    for _ in range(500):
        start = dt.date(2026, rng.randint(1, 12), rng.randint(1, 26))
        span = rng.randint(4, 6)                       # конец = start + span
        end = start + dt.timedelta(days=span)
        last = end if op == "<" else end + dt.timedelta(days=1)
        cal = [start + dt.timedelta(days=i) for i in range((last - start).days + 1)]
        window = [start + dt.timedelta(days=i) for i in range(-1, span + 3)]
        loaded = [d for d in window if rng.random() < 0.6]
        if not loaded:
            continue
        loads = []
        for d in loaded:
            for _ in range(rng.choice([1, 1, 2])):
                loads.append(d)
        missing = [d for d in cal if d not in loaded]
        # граница должна влиять на ответ: последний день календаря не загружен
        if 2 <= len(missing) <= 4 and last not in loaded and len(loads) >= 4:
            break
    else:
        raise RuntimeError("t21_recursive_gaps: не собрались данные")
    data = [(i + 1, d.isoformat(), rng.randrange(100, 5000, 10)) for i, d in enumerate(loads)]
    code = ("WITH RECURSIVE days(d) AS (\n"
            f"  SELECT '{start.isoformat()}'\n"
            "  UNION ALL\n"
            "  SELECT date(d, '+1 day')\n"
            "  FROM days\n"
            f"  WHERE d {op} '{end.isoformat()}'\n"
            ")\n"
            "SELECT days.d\n"
            "FROM days\n"
            f"LEFT JOIN {table} l ON l.load_date = days.d\n"
            "WHERE l.id IS NULL\n"
            "ORDER BY days.d;")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, load_date TEXT NOT NULL, rows_loaded INTEGER NOT NULL);\n"
             + sql_inserts(table, ["id", "load_date", "rows_loaded"], data) + "\n")
    out = "\n".join(d.isoformat() for d in missing)
    outside = [d for d in loaded if d not in cal]
    if op == "<":
        edge = (f"условие проверяется у предыдущего дня: из {(end - dt.timedelta(days=1)).isoformat()} "
                f"({(end - dt.timedelta(days=1)).isoformat()} < {end.isoformat()}) строится {end.isoformat()}, а на "
                f"{end.isoformat()} рекурсия останавливается — календарь {start.isoformat()} … {end.isoformat()}")
    else:
        edge = (f"при `<=` из самой границы {end.isoformat()} строится ещё и {last.isoformat()} — календарь "
                f"{start.isoformat()} … {last.isoformat()}")
    miss_txt = ", ".join(d.isoformat() for d in missing)
    expl = (f"Рекурсия: {edge}. LEFT JOIN оставляет дни без загрузки с l.id = NULL: {miss_txt}"
            + (f"; загрузки за {', '.join(d.isoformat() for d in sorted(outside))} вне календаря на ответ не влияют"
               if outside else "") + ".")
    stem = (f"Перед дозагрузкой ({ctx}) инженер данных ищет дни без загрузки: запрос строит календарь рекурсивным "
            "CTE и "
            f"сравнивает его с журналом.\n\n{table}\n{text_table(['id', 'load_date', 'rows_loaded'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"op": op, "span": span, "loads": len(data)}, language="sql",
                          files={"setup.sql": setup})
