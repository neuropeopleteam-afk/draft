"""backend.db.t21_sql_rolling_rows_output — predict_output (набор t21, порог Senior): скользящая сумма
`SUM(...) OVER (PARTITION BY ... ORDER BY ... ROWS BETWEEN k PRECEDING AND CURRENT ROW)` и фильтр по ней (SQLite).

Ограничитель нагрузки: по каждому клиенту считается сумма «единиц» за последние k + 1 вызовов, в отчёт попадают
вызовы, где сумма превысила лимит. Ловушки: рамка ROWS считает строки, а не минуты; окно начинается заново в каждой
партиции (у первых вызовов клиента в рамке меньше строк); фильтр по оконной функции — только во внешнем запросе.
Данные подобраны так, что ответ отличается и от расчёта без PARTITION BY, и от накопительной суммы без рамки.
Ключ — независимая модель (скользящее окно по спискам) в генераторе; проверка — исполнение запроса в SQLite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "backend.db.t21_sql_rolling_rows_output"

CTX = [("публичное API", ["key_a", "key_b", "key_c", "key_d", "key_e"]),
       ("шлюз оплаты", ["shop1", "shop2", "shop3", "shop4", "shop5"]),
       ("сервис геокодирования", ["taxi", "food", "post", "maps", "rent"])]


def _windows(rows, k, partition: bool, bounded: bool):
    """{id: сумма} для рамки последних k+1 строк (или с начала, если bounded=False)."""
    res = {}
    groups = {}
    for r in sorted(rows, key=lambda r: (r[2], r[0])):
        g = r[1] if partition else "*"
        groups.setdefault(g, []).append(r)
    for g, lst in groups.items():
        for i, r in enumerate(lst):
            lo = max(0, i - k) if bounded else 0
            res[r[0]] = sum(x[3] for x in lst[lo:i + 1])
    return res


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, clients_pool = rng.choice(CTX)
    k = rng.choice([1, 2, 2])
    alias = f"last{k + 1}"
    for _ in range(500):
        clients = rng.sample(clients_pool, rng.choice([2, 3]))
        n = rng.randint(8, 9)
        ts_all = sorted(rng.sample(range(1, 60), n))
        rows = []
        for i, ts in enumerate(ts_all):
            rows.append((i + 1, rng.choice(clients), ts, rng.randint(1, 9)))
        if any(sum(1 for r in rows if r[1] == c) < 2 for c in clients):
            continue
        limit = rng.randint(8, 16)
        good = _windows(rows, k, True, True)
        hits = [r for r in rows if good[r[0]] > limit]
        no_part = _windows(rows, k, False, True)
        unbounded = _windows(rows, k, True, False)
        hit_ids = {r[0] for r in hits}
        if (2 <= len(hits) <= 4 and hit_ids != {i for i, v in no_part.items() if v > limit}
                and hit_ids != {i for i, v in unbounded.items() if v > limit}):
            break
    else:
        raise RuntimeError("t21_sql_rolling: не собраны данные")
    query = ("SELECT client, ts, " + alias + "\nFROM (\n"
             "  SELECT client, ts,\n"
             f"         SUM(units) OVER (PARTITION BY client ORDER BY ts\n"
             f"                          ROWS BETWEEN {k} PRECEDING AND CURRENT ROW) AS {alias}\n"
             "  FROM calls\n)\n"
             f"WHERE {alias} > {limit}\nORDER BY client, ts;")
    cols = ["id", "client", "ts", "units"]
    setup = ("CREATE TABLE calls (id INTEGER PRIMARY KEY, client TEXT NOT NULL, ts INTEGER NOT NULL, "
             "units INTEGER NOT NULL);\n" + sql_inserts("calls", cols, rows) + "\n")
    res = sorted(hits, key=lambda r: (r[1], r[2]))
    out = "\n".join(f"{r[1]}|{r[2]}|{good[r[0]]}" for r in res)
    per_client = []
    for c in sorted(clients):
        lst = sorted([r for r in rows if r[1] == c], key=lambda r: r[2])
        per_client.append(f"{c}: " + ", ".join(f"ts {r[2]} → {good[r[0]]}" for r in lst))
    prev = "предыдущая строка" if k == 1 else "предыдущие строки"
    expl = (f"Рамка ROWS BETWEEN {k} PRECEDING AND CURRENT ROW — текущая строка и {k} {prev} того же клиента "
            f"(строки, а не минуты); в каждой партиции окно начинается заново. Скользящие суммы: "
            + "; ".join(per_client) + f". Больше {limit}: "
            + ", ".join(f"{r[1]}|{r[2]}|{good[r[0]]}" for r in res) + ".")
    stem = (f"«{ctx}»: ограничитель нагрузки считает по каждому клиенту сумму единиц за последние {k + 1} "
            f"вызова и ищет превышения лимита. Таблица `calls` (ts — минута от начала часа):\n\ncalls\n"
            f"{text_table(cols, rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=query, out=out, explanation=expl, context=ctx,
                          params={"k": k, "limit": limit}, language="sql", files={"setup.sql": setup})
