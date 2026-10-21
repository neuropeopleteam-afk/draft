"""analyst.sql.t21_and_or_where_output — predict_output (набор t21, порог Стажёра): приоритет AND над OR в WHERE
без скобок.

Таблица (лиды, обращения, пользователи, заказы, объявления) и запрос `SELECT id ... WHERE` с тремя условиями без
скобок: `c = 'X' OR c = 'Y' AND v >= T` или `v >= T AND c = 'X' OR c = 'Y'`. AND выполняется раньше OR, поэтому
одна из категорий отбирается целиком, без порога. В данных всегда есть строка, на которой прочтение «со скобками
вокруг OR» даёт другой ответ. Ключ — независимый отбор в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_and_or_where_output"

# (таблица, сюжет, колонка категории, категории, числовая колонка, сетка значений)
CTX = [
    ("leads", "Лиды из заявок на демо", "source", ["ads", "blog", "partner", "email"], "score",
     list(range(10, 100, 5))),
    ("tickets", "Обращения в поддержку за день", "channel", ["chat", "phone", "email"], "minutes",
     list(range(2, 61, 2))),
    ("users", "Пользователи сервиса за неделю", "plan", ["free", "pro", "team"], "sessions", list(range(1, 31))),
    ("orders", "Заказы маркетплейса за час", "payment", ["card", "cash", "sbp"], "amount",
     list(range(200, 5001, 100))),
    ("banners", "Баннеры рекламной кампании", "placement", ["search", "social", "video"], "clicks",
     list(range(5, 301, 5))),
]


def _pick(form, rows, x, y, t):
    if form == "or_and":      # c = X OR (c = Y AND v >= T)
        return [r for r in rows if r[1] == x or (r[1] == y and r[2] >= t)]
    return [r for r in rows if (r[2] >= t and r[1] == x) or r[1] == y]   # (v >= T AND c = X) OR c = Y


def _naive(form, rows, x, y, t):
    """Прочтение «(c = X OR c = Y) AND v >= T» — им ловушка и проверяется."""
    return [r for r in rows if r[1] in (x, y) and r[2] >= t]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, cat, cats, val, grid = rng.choice(CTX)
    form = rng.choice(["or_and", "and_or"])
    for _ in range(500):
        x, y = rng.sample(cats, 2)
        z = [c for c in cats if c not in (x, y)]
        it = rng.randrange(len(grid) // 4, 3 * len(grid) // 4)
        t = grid[it]
        n = rng.randint(7, 9)
        rows = []
        rid = rng.randint(1, 30)
        for _k in range(n):
            rid += rng.randint(1, 3)
            c = rng.choice([x, x, y, y] + z)
            v = grid[rng.randrange(0, len(grid))] if rng.random() < 0.8 else t
            rows.append((rid, c, v))
        sel = _pick(form, rows, x, y, t)
        naive = _naive(form, rows, x, y, t)
        free_cat = x if form == "or_and" else y          # категория, отбираемая без порога
        low_free = [r for r in rows if r[1] == free_cat and r[2] < t]
        thr_cat = y if form == "or_and" else x
        thr_low = [r for r in rows if r[1] == thr_cat and r[2] < t]
        thr_hi = [r for r in rows if r[1] == thr_cat and r[2] >= t]
        other_hi = [r for r in rows if r[1] in z and r[2] >= t] if z else [None]
        if low_free and thr_low and thr_hi and other_hi and 3 <= len(sel) <= len(rows) - 2 and sel != naive:
            break
    else:
        raise RuntimeError("t21_and_or_where: не собрались данные")
    if form == "or_and":
        where = f"WHERE {cat} = '{x}' OR {cat} = '{y}' AND {val} >= {t}"
    else:
        where = f"WHERE {val} >= {t} AND {cat} = '{x}' OR {cat} = '{y}'"
    code = f"SELECT id\nFROM {T}\n{where}\nORDER BY id;"
    out = "\n".join(str(r[0]) for r in sel)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {cat} TEXT NOT NULL, {val} INTEGER NOT NULL);\n"
             + sql_inserts(T, ["id", cat, val], rows) + "\n")
    stem = (f"{plot}: аналитик отбирает строки для выгрузки по {cat} и {val}.\n\n"
            f"{T}\n{text_table(['id', cat, val], rows)}")
    if form == "or_and":
        rule = (f"AND связывает сильнее OR: условие читается как {cat} = '{x}' OR ({cat} = '{y}' AND {val} >= {t}) — "
                f"все строки '{x}' независимо от {val} и строки '{y}' с {val} не меньше {t}")
    else:
        rule = (f"AND связывает сильнее OR: условие читается как ({val} >= {t} AND {cat} = '{x}') OR {cat} = '{y}' — "
                f"строки '{x}' с {val} не меньше {t} и все строки '{y}' независимо от {val}")
    lows = ", ".join(str(r[0]) for r in low_free)
    expl = (f"{rule}. Поэтому попадают и id {lows} ({cat} = '{free_cat}', {val} < {t}). "
            f"Итог по возрастанию id: {', '.join(str(r[0]) for r in sel)}.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "form": form, "x": x, "y": y, "t": t}, language="sql",
                          files={"setup.sql": setup})
