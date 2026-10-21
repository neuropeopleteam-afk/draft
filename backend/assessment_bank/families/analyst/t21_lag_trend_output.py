"""analyst.sql.t21_lag_trend_output — predict_output (набор t21, порог Senior): LAG по партициям внутри CASE —
сравнение с NULL у первой строки партиции.

Таблица периодических метрик по сегментам (выручка магазинов по неделям, MAU платформ по месяцам, заказы регионов по
дням, регистрации каналов по неделям) и запрос, который размечает каждую строку 'up' / 'down' / 'flat' по сравнению
с предыдущим периодом того же сегмента: `CASE WHEN x > LAG(x) OVER w … WHEN x < LAG(x) OVER w … ELSE 'flat'`.
Ловушки: у первой строки каждой партиции LAG = NULL, оба сравнения «неизвестно» — срабатывает ELSE; партиция
начинается заново (первый период второго сегмента не сравнивается с последним первого); в части вариантов LAG с
default 0 (`LAG(x, 1, 0)`) — тогда первая строка 'up'. Ключ — независимый расчёт в генераторе; проверка — sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_lag_trend_output"

# (таблица, сюжет, сегмент, сегменты, период, числовая колонка, сетка)
CTX = [
    ("weekly", "Выручка магазинов по неделям (тыс. руб.)", "shop", ["north", "south", "center", "west"], "week",
     "revenue", list(range(100, 300, 10))),
    ("mau", "Ежемесячная аудитория приложения по платформам", "platform", ["ios", "android", "web"], "month",
     "users", list(range(500, 1500, 50))),
    ("daily", "Заказы по регионам за дни недели", "region", ["msk", "spb", "kzn", "ekb"], "day", "orders",
     list(range(20, 80, 2))),
    ("signups", "Регистрации по каналам привлечения по неделям", "channel", ["ads", "seo", "email", "social"],
     "week", "signups", list(range(30, 120, 5))),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, seg, segs, per, num, grid = rng.choice(CTX)
    default0 = rng.random() < 0.3
    for _ in range(1000):
        gs = sorted(rng.sample(segs, rng.choice([2, 3])))
        rows = []
        for g in gs:
            k = rng.randint(3, 4) if len(gs) == 2 else rng.randint(2, 3)
            start = rng.randint(1, 3)
            v = rng.choice(grid)
            for p in range(start, start + k):
                rows.append((g, p, v))
                r = rng.random()
                if r < 0.25:
                    pass                               # без изменений — 'flat'
                else:
                    v = rng.choice(grid)
        if not 6 <= len(rows) <= 9:
            continue
        res = []
        for i, (g, p, v) in enumerate(rows):
            prev = rows[i - 1][2] if i > 0 and rows[i - 1][0] == g else (0 if default0 else None)
            if prev is None:
                t = "flat"
            elif v > prev:
                t = "up"
            elif v < prev:
                t = "down"
            else:
                t = "flat"
            res.append((g, p, t))
        kinds = {t for _g, _p, t in res}
        mid_flat = any(t == "flat" and i > 0 and rows[i - 1][0] == rows[i][0] for i, (_g, _p, t) in enumerate(res))
        # «соблазн» сравнить через границу партиции: первый период следующего сегмента отличается от последнего
        cross = any(rows[i][0] != rows[i - 1][0] and rows[i][2] != rows[i - 1][2] for i in range(1, len(rows)))
        if {"up", "down"} <= kinds and cross and (mid_flat or rng.random() < 0.5):
            break
    else:
        raise RuntimeError("t21_lag_trend: не собрались данные")
    lag = f"LAG({num}, 1, 0)" if default0 else f"LAG({num})"
    code = (f"SELECT {seg}, {per},\n"
            f"       CASE\n"
            f"         WHEN {num} > {lag} OVER w THEN 'up'\n"
            f"         WHEN {num} < {lag} OVER w THEN 'down'\n"
            f"         ELSE 'flat'\n"
            f"       END AS trend\n"
            f"FROM {T}\n"
            f"WINDOW w AS (PARTITION BY {seg} ORDER BY {per})\n"
            f"ORDER BY {seg}, {per};")
    out = "\n".join(f"{g}|{p}|{t}" for g, p, t in res)
    table_rows = list(rows)
    rng.shuffle(table_rows)
    setup = (f"CREATE TABLE {T} ({seg} TEXT NOT NULL, {per} INTEGER NOT NULL, {num} INTEGER NOT NULL, "
             f"PRIMARY KEY ({seg}, {per}));\n" + sql_inserts(T, [seg, per, num], table_rows) + "\n")
    stem = (f"{plot}: запрос помечает, вырос показатель {num} к предыдущему периоду своего сегмента {seg} "
            f"или упал.\n\n{T}\n{text_table([seg, per, num], table_rows)}")
    if default0:
        first = (f"у первой строки каждого {seg} LAG({num}, 1, 0) возвращает значение по умолчанию 0, поэтому "
                 f"{num} > 0 и метка 'up'")
    else:
        first = (f"у первой строки каждого {seg} LAG возвращает NULL, оба сравнения с NULL дают «неизвестно», "
                 f"и срабатывает ELSE — 'flat'")
    expl = (f"Окно разбито по {seg} и упорядочено по {per}; сравнение идёт только с предыдущей строкой того же "
            f"{seg}. {first[0].upper() + first[1:]}; равные соседние значения тоже дают 'flat'. По строкам: "
            + "; ".join(f"{g} {p}: {v} → {t}" for (g, p, v), (_g, _p, t) in zip(rows, res)) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "default0": default0}, language="sql", files={"setup.sql": setup})
