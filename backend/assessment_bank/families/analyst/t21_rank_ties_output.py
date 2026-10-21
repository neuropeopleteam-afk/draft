"""analyst.sql.t21_rank_ties_output — predict_output (набор t21, порог Middle): RANK, DENSE_RANK и ROW_NUMBER рядом
в одной партиции с ничьими.

Таблица (товары по категориям, менеджеры по регионам, статьи по рубрикам, курьеры по зонам) и один SELECT с тремя
ранжирующими функциями по одной партиции: `RANK() OVER w`, `DENSE_RANK() OVER w` и `ROW_NUMBER()` с тем же
порядком плюс второй ключ. В каждой группе есть ничья: RANK даёт равным одинаковый номер и пропускает следующие
(1, 1, 3), DENSE_RANK — без пропусков (1, 1, 2), ROW_NUMBER нумерует подряд, ничью решает второй ключ; нумерация
начинается заново в каждой партиции. Ключ — независимый расчёт в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_rank_ties_output"

# (таблица, сюжет, группа, группы, элемент, элементы, метрика, сетка)
CTX = [
    ("products", "Рейтинг товаров внутри категорий за неделю", "category", ["books", "games", "toys"], "sku",
     ["A-11", "A-27", "B-05", "B-40", "C-13", "C-31", "D-08", "D-19", "E-22", "F-04", "G-16", "H-30"], "orders",
     list(range(5, 60))),
    ("managers", "Рейтинг менеджеров внутри регионов за месяц", "region", ["north", "south", "volga"], "manager",
     ["anna", "boris", "vera", "gleb", "dina", "egor", "inna", "kira", "lev", "mila", "oleg", "petr"], "deals",
     list(range(3, 40))),
    ("articles", "Рейтинг статей внутри рубрик блога", "topic", ["news", "guides", "cases"], "slug",
     ["a-101", "a-102", "b-201", "b-202", "c-301", "c-302", "d-401", "d-402", "e-501", "e-502", "f-601"], "views",
     list(range(100, 2000, 50))),
    ("couriers", "Рейтинг курьеров внутри зон доставки", "zone", ["center", "east", "west"], "courier",
     ["c01", "c02", "c03", "c04", "c05", "c06", "c07", "c08", "c09", "c10", "c11", "c12"], "deliveries",
     list(range(10, 50))),
]


def _ranks(vals_desc):
    """(RANK, DENSE_RANK, ROW_NUMBER) для значений, уже упорядоченных как в окне."""
    out = []
    for i, v in enumerate(vals_desc):
        r = 1 + sum(1 for x in vals_desc if x > v)
        d = 1 + len({x for x in vals_desc if x > v})
        out.append((r, d, i + 1))
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, g, groups, item, items, m, grid = rng.choice(CTX)
    for _ in range(2000):
        gs = sorted(rng.sample(groups, 2))
        sizes = [rng.randint(3, 4) for _x in gs]
        names = rng.sample(items, sum(sizes))
        rows, ni = [], 0
        for x, k in zip(gs, sizes):
            vals = rng.sample(grid, k)
            j = rng.randrange(0, k - 1)
            vals.sort(reverse=True)
            vals[j + 1] = vals[j]                    # ничья на соседних местах
            for v in vals:
                rows.append((x, names[ni], v))
                ni += 1
        res, ok_skip = [], False
        for x in gs:
            grp = sorted((r for r in rows if r[0] == x), key=lambda r: (-r[2], r[1]))
            rk = _ranks([r[2] for r in grp])
            if any(rr != dd for rr, dd, _n in rk):
                ok_skip = True                        # RANK и DENSE_RANK где-то расходятся
            res += [(r, t) for r, t in zip(grp, rk)]
        if ok_skip:
            break
    else:
        raise RuntimeError("t21_rank_ties: не собрались данные")
    table_rows = list(rows)
    rng.shuffle(table_rows)
    code = (f"SELECT {g}, {item},\n"
            f"       RANK() OVER w AS rnk,\n"
            f"       DENSE_RANK() OVER w AS dense_rnk,\n"
            f"       ROW_NUMBER() OVER (PARTITION BY {g} ORDER BY {m} DESC, {item}) AS rn\n"
            f"FROM {T}\n"
            f"WINDOW w AS (PARTITION BY {g} ORDER BY {m} DESC)\n"
            f"ORDER BY {g}, rn;")
    out = "\n".join(f"{r[0]}|{r[1]}|{t[0]}|{t[1]}|{t[2]}" for r, t in res)
    setup = (f"CREATE TABLE {T} ({g} TEXT NOT NULL, {item} TEXT PRIMARY KEY, {m} INTEGER NOT NULL);\n"
             + sql_inserts(T, [g, item, m], table_rows) + "\n")
    stem = (f"{plot}: запрос нумерует строки внутри каждой группы {g} по убыванию {m} тремя функциями.\n\n"
            f"{T}\n{text_table([g, item, m], table_rows)}")
    per = "; ".join(f"{x}: " + ", ".join(f"{r[1]} ({r[2]})" for r, _t in res if r[0] == x) for x in gs)
    expl = (f"Порядок внутри групп по убыванию {m} (при равенстве ROW_NUMBER смотрит на {item}): {per}. RANK даёт "
            f"равным одинаковый номер и пропускает следующие (1, 1, 3), DENSE_RANK — без пропусков (1, 1, 2), "
            f"ROW_NUMBER нумерует подряд; в каждой группе {g} нумерация начинается с 1. Ответ: "
            + "; ".join(out.splitlines()) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows}, language="sql", files={"setup.sql": setup})
