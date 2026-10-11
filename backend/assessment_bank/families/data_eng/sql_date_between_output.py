"""data_eng.sql.date_between_output — predict_output: BETWEEN по датам и столбец с датой и временем.

Отчёт за период считает строки `WHERE ts BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`, а столбец ts хранит дату и время
(текст ISO 8601, как в SQLite; в PostgreSQL то же происходит с timestamp: '2026-10-31' означает полночь). Верхняя
граница — полночь последнего дня, поэтому события последнего дня позже 00:00:00 в отчёт не попадают (ловушка
уровня Intern/Junior), а событие ровно в начале периода попадает (BETWEEN включает обе границы). Ключ — исполнение
запроса в sqlite.
"""
from __future__ import annotations

import calendar

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.date_between_output"

CTX = [("регистрации пользователей", "signups", "bonus"), ("заказы", "orders", "amount"),
       ("возвраты товаров", "refunds", "amount"), ("обращения в поддержку", "tickets", "minutes"),
       ("пополнения кошелька", "topups", "amount"), ("поездки каршеринга", "trips", "km")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, val = rng.choice(CTX)
    for _ in range(2000):
        month = rng.randint(1, 11)
        last = calendar.monthrange(2026, month)[1]
        d0, d1 = f"2026-{month:02d}-01", f"2026-{month:02d}-{last:02d}"
        n = rng.randint(7, 10)
        data = []
        for i in range(n):
            kind = rng.choice(["mid", "mid", "last", "start", "before", "after"])
            if kind == "mid":
                day, hh, mm = rng.randint(2, last - 1), rng.randint(0, 23), rng.randint(0, 59)
                ts = f"2026-{month:02d}-{day:02d} {hh:02d}:{mm:02d}:00"
            elif kind == "last":
                ts = f"{d1} {rng.randint(0, 23):02d}:{rng.randint(1, 59):02d}:00"
            elif kind == "start":
                ts = f"{d0} 00:00:00"
            elif kind == "before":
                pm = month - 1 if month > 1 else 12
                py = 2026 if month > 1 else 2025
                ts = f"{py}-{pm:02d}-28 {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00"
            else:
                ts = f"2026-{month + 1:02d}-01 {rng.randint(0, 9):02d}:{rng.randint(0, 59):02d}:00"
            data.append((rng.randint(1000, 9999) + i * 10000, ts, rng.randrange(100, 3000, 50)))
        data.sort(key=lambda r: r[1])
        code = (f"SELECT COUNT(*) AS n, SUM({val}) AS total\nFROM {table}\n"
                f"WHERE created_at BETWEEN '{d0}' AND '{d1}';")
        setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, created_at TEXT, {val} INTEGER);\n"
                 + insert(table, ["id", "created_at", val], data))
        out = rows(setup, code)
        naive = rows(setup, code.replace(f"'{d1}'", f"'{d1} 23:59:59'"))
        has_last = any(r[1].startswith(d1) and r[1] > d1 for r in data)
        has_start = any(r[1] == f"{d0} 00:00:00" for r in data)
        if out != naive and has_last and has_start and not out.startswith("0|"):
            break
    tbl = "\n".join(f"{a} | {b} | {c}" for a, b, c in data)
    stem = (f"Таблица `{table}` ({ctx}) в SQLite, created_at хранится текстом `ГГГГ-ММ-ДД ЧЧ:ММ:СС` (id | created_at | "
            f"{val}):\n{tbl}\nАналитик считает итоги за месяц запросом ниже. Что вернёт запрос? Ответ — строка "
            "`n|total`.")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"BETWEEN включает обе границы, но '{d1}' — это начало последнего дня: строки "
                               f"'{d1} 00:01:00' и позже больше границы и не попадают. Надёжный фильтр — "
                               f"created_at >= '{d0}' AND created_at < первое число следующего месяца.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"month": month, "last": last})
