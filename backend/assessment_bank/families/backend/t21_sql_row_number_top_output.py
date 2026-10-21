"""backend.db.t21_sql_row_number_top_output — predict_output (набор t21, порог Middle): ROW_NUMBER() по PARTITION
и отбор «первых N в группе» (SQLite).

Отчёт по самым медленным (или самым быстрым) запросам: ROW_NUMBER() OVER (PARTITION BY endpoint ORDER BY
latency_ms DESC|ASC) во вложенном запросе и фильтр rn <= N снаружи. Ловушка (одна неочевидная семантика):
нумерация начинается заново в каждой партиции, поэтому в ответ попадает по N строк из КАЖДОЙ группы (из маленькой —
сколько есть), а не N строк на всю таблицу; направление сортировки внутри окна. Значения в группе различны.
Ключ — независимая модель (группировка и сортировка списков) в генераторе; проверка — исполнение запроса в SQLite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "backend.db.t21_sql_row_number_top_output"

CTX = [("API заказов", "endpoint", ["/orders", "/cart", "/users", "/auth"]),
       ("шлюз оплаты", "merchant", ["coffee", "books", "sport", "travel"]),
       ("поиск по каталогу", "endpoint", ["/search", "/suggest", "/filters", "/facets"]),
       ("сервис уведомлений", "channel", ["sms", "email", "push", "webhook"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, gcol, gpool = rng.choice(CTX)
    top_n = rng.choice([1, 2, 2])
    slow = rng.random() < 0.7
    want_small = top_n > 1 and rng.random() < 0.5
    for _ in range(300):
        groups = rng.sample(gpool, 3)
        n = rng.randint(8, 9)
        lats = rng.sample(range(40, 990, 10), n)
        rows = [(i + 1, rng.choice(groups), lats[i]) for i in range(n)]
        sizes = {g: sum(1 for r in rows if r[1] == g) for g in groups}
        small_ok = (min(sizes.values()) < top_n) == want_small
        if min(sizes.values()) >= 1 and max(sizes.values()) >= top_n + 2 and small_ok:
            break
    else:
        raise RuntimeError("t21_row_number: не собраны данные")
    direction = "DESC" if slow else "ASC"
    cond = f"rn <= {top_n}" if top_n > 1 else "rn = 1"
    query = (f"SELECT {gcol}, latency_ms\nFROM (\n"
             f"  SELECT {gcol}, latency_ms,\n"
             f"         ROW_NUMBER() OVER (PARTITION BY {gcol} ORDER BY latency_ms {direction}) AS rn\n"
             "  FROM requests\n)\n"
             f"WHERE {cond}\nORDER BY {gcol}, latency_ms {direction};")
    cols = ["id", gcol, "latency_ms"]
    setup = (f"CREATE TABLE requests (id INTEGER PRIMARY KEY, {gcol} TEXT NOT NULL, latency_ms INTEGER NOT NULL);\n"
             + sql_inserts("requests", cols, rows) + "\n")
    res = []
    per = []
    for g in sorted(groups):
        lst = sorted((r[2] for r in rows if r[1] == g), reverse=slow)
        per.append(f"{g}: {', '.join(str(x) for x in lst)}")
        res += [(g, x) for x in lst[:top_n]]
    out = "\n".join(f"{g}|{x}" for g, x in res)
    expl = (f"ROW_NUMBER() нумерует строки заново в каждой партиции {gcol}, по latency_ms "
            f"{'по убыванию' if slow else 'по возрастанию'}: " + "; ".join(per)
            + f". Фильтр {cond} оставляет первые {top_n} в КАЖДОЙ группе"
            + (" (из группы с одной строкой — одну)" if want_small else "")
            + ", а не на всю таблицу: " + ", ".join(f"{g}|{x}" for g, x in res) + ".")
    what = "самые медленные" if slow else "самые быстрые"
    stem = (f"«{ctx}»: отчёт для разбора инцидента показывает {what} запросы по каждому значению {gcol}. Таблица "
            f"`requests`:\n\nrequests\n{text_table(cols, rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=query, out=out, explanation=expl, context=ctx,
                          params={"top_n": top_n, "slow": slow}, language="sql", files={"setup.sql": setup})
