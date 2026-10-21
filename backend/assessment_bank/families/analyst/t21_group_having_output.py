"""analyst.sql.t21_group_having_output — predict_output (набор t21, порог Junior): WHERE до группировки, GROUP BY
и HAVING после неё.

Таблица (заказы по каналам, поездки по тарифам, заявки по регионам, покупки по категориям, подписки по планам) и
запрос `WHERE status = '…' GROUP BY … HAVING COUNT(*) >= k` (или `HAVING SUM(…) >= X`) `ORDER BY` по сумме.
Ловушки: WHERE отбрасывает строки другого статуса ДО подсчёта, поэтому группа, у которой «всего строк» хватает,
но «нужных» мало, отсекается HAVING; порядок — по сумме, а не по имени группы. Ключ — независимый расчёт в
генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_group_having_output"

# (таблица, сюжет, колонка группы, группы, статусы [нужный, прочие], числовая колонка, сетка, алиасы)
CTX = [
    ("orders", "Заказы за неделю по каналам привлечения", "channel", ["ads", "seo", "email", "social"],
     ["paid", "cancelled"], "amount", list(range(500, 5001, 100)), ("paid_orders", "revenue")),
    ("rides", "Поездки такси за вечер по тарифам", "tariff", ["econom", "comfort", "business", "kids"],
     ["done", "cancelled"], "price", list(range(200, 2001, 50)), ("done_rides", "revenue")),
    ("applications", "Заявки на кредит за день по регионам", "region", ["Самара", "Тверь", "Уфа", "Курск"],
     ["approved", "rejected"], "amount", list(range(50, 1001, 50)), ("approved_cnt", "approved_sum")),
    ("purchases", "Покупки за день по категориям", "category", ["books", "games", "music", "toys"],
     ["paid", "refund"], "amount", list(range(100, 3001, 100)), ("paid_cnt", "paid_sum")),
    ("subscriptions", "Подписки за месяц по тарифным планам", "plan", ["basic", "plus", "team", "family"],
     ["active", "churned"], "mrr", list(range(200, 2001, 100)), ("active_cnt", "active_mrr")),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, g, groups, statuses, num, grid, (a_cnt, a_sum) = rng.choice(CTX)
    good = statuses[0]
    mode = rng.choice(["count", "count", "sum"])
    for _ in range(1000):
        gs = rng.sample(groups, rng.randint(3, 4))
        n = rng.randint(10, 12)
        rows = []
        rid = rng.randint(1, 30)
        for _k in range(n):
            rid += rng.randint(1, 3)
            rows.append((rid, rng.choice(gs), good if rng.random() < 0.6 else rng.choice(statuses[1:]),
                         rng.choice(grid)))
        stat = {}
        for x in gs:
            mine = [r for r in rows if r[1] == x]
            good_rows = [r for r in mine if r[2] == good]
            stat[x] = (len(mine), len(good_rows), sum(r[3] for r in good_rows), sum(r[3] for r in mine))
        if mode == "count":
            k = rng.choice([2, 3])
            keep = [x for x in gs if stat[x][1] >= k]
            trap_groups = [x for x in gs if stat[x][1] < k <= stat[x][0]]
            having = f"HAVING COUNT(*) >= {k}"
        else:
            sums = sorted({stat[x][2] for x in gs})
            if len(sums) < 3:
                continue
            k = (sums[0] + sums[1]) // 200 * 100 + 100
            if not sums[0] < k <= sums[1]:
                continue
            keep = [x for x in gs if stat[x][2] >= k]
            trap_groups = [x for x in gs if stat[x][2] < k <= stat[x][3]]
            having = f"HAVING SUM({num}) >= {k}"
        kept_sums = [stat[x][2] for x in keep]
        if not keep or not trap_groups or len(keep) == len(gs) or len(set(kept_sums)) != len(kept_sums):
            continue
        if not any(stat[x][0] > stat[x][1] for x in keep):
            continue
        if any(stat[x][1] == 0 for x in gs):
            continue
        break
    else:
        raise RuntimeError("t21_group_having: не собрались данные")
    code = (f"SELECT {g}, COUNT(*) AS {a_cnt}, SUM({num}) AS {a_sum}\n"
            f"FROM {T}\n"
            f"WHERE status = '{good}'\n"
            f"GROUP BY {g}\n"
            f"{having}\n"
            f"ORDER BY {a_sum} DESC;")
    res = sorted(keep, key=lambda x: -stat[x][2])
    out = "\n".join(f"{x}|{stat[x][1]}|{stat[x][2]}" for x in res)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {g} TEXT NOT NULL, status TEXT NOT NULL, "
             f"{num} INTEGER NOT NULL);\n" + sql_inserts(T, ["id", g, "status", num], rows) + "\n")
    stem = (f"{plot}: запрос строит сводку по группам {g} для статуса '{good}'.\n\n"
            f"{T}\n{text_table(['id', g, 'status', num], rows)}")
    per = "; ".join(f"{x}: {stat[x][1]} шт., {stat[x][2]}" for x in gs)
    tg = ", ".join(trap_groups)
    what = "строк" if mode == "count" else "суммы"
    expl = (f"WHERE оставляет только строки '{good}' до группировки. По группам: {per}. {having} проверяется уже "
            f"по отобранным строкам, поэтому {tg} не проходит, хотя вместе со строками других статусов {what} "
            f"хватило бы. Сортировка — по {a_sum} по убыванию. Ответ: " + "; ".join(out.splitlines()) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "mode": mode, "k": k}, language="sql",
                          files={"setup.sql": setup})
