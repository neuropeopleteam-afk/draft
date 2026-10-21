"""backend.db.t21_sql_between_latency_output — predict_output (набор t21, порог Стажёра): WHERE с BETWEEN и AND,
агрегаты COUNT(*), MIN, MAX (SQLite).

Отчёт по журналу запросов: сколько успешных запросов уложились в «жёлтую зону» задержки и каковы её фактические
границы. Ловушки: BETWEEN включает обе границы (в данных всегда есть строки ровно на границе), второе условие AND
отсекает часть строк из диапазона. Ключ — независимый подсчёт по данным в генераторе; проверка — исполнение
запроса в SQLite на данных из условия.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "backend.db.t21_sql_between_latency_output"

CTX = [("API заказов", ["/orders", "/orders/{id}", "/cart"]), ("сервис профилей", ["/users", "/users/{id}", "/me"]),
       ("поиск по каталогу", ["/search", "/suggest", "/filters"]), ("шлюз оплаты", ["/pay", "/refund", "/status"]),
       ("сервис доставки", ["/quote", "/track", "/slots"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, endpoints = rng.choice(CTX)
    lo = rng.randrange(150, 400, 50)
    hi = lo + rng.randrange(200, 500, 50)
    mode = rng.choice(["status", "method"])
    for _ in range(300):
        n = rng.randint(7, 9)
        rows = []
        for i in range(n):
            kind = rng.random()
            if kind < 0.2:
                lat = lo
            elif kind < 0.35:
                lat = hi
            elif kind < 0.7:
                lat = rng.randrange(lo + 10, hi, 10)
            elif kind < 0.85:
                lat = rng.randrange(max(20, lo - 140), lo, 10)
            else:
                lat = rng.randrange(hi + 10, hi + 400, 10)
            status = rng.choice([200, 200, 200, 500, 503]) if mode == "status" else 200
            method = rng.choice(["GET", "GET", "POST"])
            rows.append((i + 1, rng.choice(endpoints), method, status, lat))
        if mode == "status":
            match = [r for r in rows if lo <= r[4] <= hi and r[3] == 200]
            miss_and = [r for r in rows if lo <= r[4] <= hi and r[3] != 200]
        else:
            match = [r for r in rows if lo <= r[4] <= hi and r[2] == "GET"]
            miss_and = [r for r in rows if lo <= r[4] <= hi and r[2] != "GET"]
        edge = [r for r in match if r[4] in (lo, hi)]
        if len(match) >= 2 and edge and miss_and and len(set(r[4] for r in rows)) == n:
            break
    else:
        raise RuntimeError("t21_sql_between: не собраны данные")
    cond = "status = 200" if mode == "status" else "method = 'GET'"
    query = (f"SELECT COUNT(*), MIN(latency_ms), MAX(latency_ms)\nFROM requests\n"
             f"WHERE latency_ms BETWEEN {lo} AND {hi}\n  AND {cond};")
    cols = ["id", "endpoint", "method", "status", "latency_ms"]
    setup = ("CREATE TABLE requests (id INTEGER PRIMARY KEY, endpoint TEXT, method TEXT, status INTEGER, "
             "latency_ms INTEGER);\n" + sql_inserts("requests", cols, rows) + "\n")
    lats = [r[4] for r in match]
    out = f"{len(match)}|{min(lats)}|{max(lats)}"
    expl = (f"BETWEEN {lo} AND {hi} включает обе границы, поэтому строки с задержкой ровно "
            + " и ".join(str(x) for x in sorted({r[4] for r in edge}))
            + f" попадают в выборку; условие {cond} отбрасывает id "
            + ", ".join(str(r[0]) for r in miss_and)
            + f". Остаются id {', '.join(str(r[0]) for r in match)}: COUNT = {len(match)}, MIN = {min(lats)}, "
              f"MAX = {max(lats)}.")
    stem = (f"Сервис «{ctx}»: отчёт по журналу запросов за минуту считает запросы в заданной полосе задержки. "
            f"Таблица `requests`:\n\nrequests\n{text_table(cols, rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=query, out=out, explanation=expl, context=ctx,
                          params={"lo": lo, "hi": hi, "mode": mode}, language="sql", files={"setup.sql": setup})
