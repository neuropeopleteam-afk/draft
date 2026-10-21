"""data_eng.sql.t21_running_sum_peers_output — predict_output (набор t21, порог Senior): накопительная сумма по
партиции окна с рамкой по умолчанию — строки с равной датой (peers) получают одинаковый итог.

Журнал загрузок по источникам; запрос считает накопительную сумму загруженных строк по каждому источнику
`SUM(...) OVER (PARTITION BY source ORDER BY load_date)` без явной рамки. Рамка по умолчанию —
`RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`: в неё входят все строки с той же датой, поэтому у двух загрузок
одного источника за один день итог одинаковый и сразу включает обе. Ловушки: построчное накопление (как при ROWS) и
забытый сброс суммы на границе партиции. Ключ — независимая модель в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_running_sum_peers_output"

CTX = [("загрузки заказов по каналам продаж", "order_loads", ["web", "app", "shop"]),
       ("приём событий по источникам", "event_loads", ["ios", "android", "web"]),
       ("импорт платежей по банкам-эквайерам", "payment_loads", ["acq_a", "acq_b", "acq_c"]),
       ("выгрузки логов по кластерам", "log_loads", ["msk1", "msk2", "spb1"]),
       ("загрузки остатков по складам", "stock_loads", ["north", "south", "east"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, src_pool = rng.choice(CTX)
    sources = rng.sample(src_pool, 2)
    base = dt.date(2026, rng.randint(1, 12), rng.randint(1, 25))
    for _ in range(500):
        rows = []
        for s in sources:
            k = rng.randint(3, 4)
            offs = sorted(rng.choice(range(4)) for _ in range(k))
            for o in offs:
                rows.append((s, (base + dt.timedelta(days=o)).isoformat(), rng.randrange(10, 100, 5)))
        ties = [s for s in sources
                if len({d for ss, d, _ in rows if ss == s}) < sum(1 for r in rows if r[0] == s)]
        if ties and len({d for _, d, _ in rows}) >= 3:
            break
    else:
        raise RuntimeError("t21_running_sum_peers: не собрались данные")
    rng.shuffle(rows)
    rows.sort(key=lambda r: r[1])  # id идут по дате, источники вперемешку
    data = [(i + 1, s, d, n) for i, (s, d, n) in enumerate(rows)]
    code = ("SELECT\n"
            "  id,\n"
            "  SUM(rows_loaded) OVER (\n"
            "    PARTITION BY source\n"
            "    ORDER BY load_date\n"
            "  ) AS running_total\n"
            f"FROM {table}\n"
            "ORDER BY id;")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, source TEXT NOT NULL, load_date TEXT NOT NULL, "
             "rows_loaded INTEGER NOT NULL);\n" + sql_inserts(table, ["id", "source", "load_date", "rows_loaded"], data)
             + "\n")
    res = []
    for i, s, d, _n in data:
        total = sum(n for _, ss, dd, n in data if ss == s and dd <= d)
        res.append((i, total))
    out = "\n".join(f"{i}|{t}" for i, t in res)
    tie_src = ties[0]
    tie_rows = [r for r in data if r[1] == tie_src]
    tie_date = next(d for d in sorted({r[2] for r in tie_rows}) if sum(1 for r in tie_rows if r[2] == d) > 1)
    tie_ids = [r[0] for r in tie_rows if r[2] == tie_date]
    tie_total = dict(res)[tie_ids[0]]
    expl = (f"Сумма считается отдельно для каждого источника ({sources[0]} и {sources[1]}). Явной рамки нет, поэтому "
            "действует RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW: в рамку входят все строки источника с датой "
            f"не позже текущей, включая строки с той же датой. Например, у {tie_src} за {tie_date} строки "
            f"{', '.join(str(i) for i in tie_ids)} получают один итог {tie_total}, а не построчное накопление. "
            "Итог: " + "; ".join(f"{i}|{t}" for i, t in res) + ".")
    stem = (f"Мониторинг загрузок ({ctx}): запрос считает накопительное число загруженных строк по каждому источнику."
            f"\n\n{table}\n{text_table(['id', 'source', 'load_date', 'rows_loaded'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"rows": len(data), "tie_source": tie_src}, language="sql",
                          files={"setup.sql": setup})
