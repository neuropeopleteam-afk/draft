"""analyst.sql.join_fanout_fix — choose_fix: соединение «один ко многим» раздувает число и сумму заказов.

Нужно: по каналам — число и выручка оплаченных заказов, где есть хотя бы одна позиция категории X. Запрос
соединяет заказы с позициями (несколько позиций категории в заказе → заказ повторяется). Верно — фильтр
через полусоединение (подзапрос DISTINCT order_id или IN). Состав дистракторов фиксирован, все «почти верные»:
  * count_distinct — COUNT(DISTINCT o.id) чинит число, но SUM остаётся раздутой;
  * sum_distinct — SUM(DISTINCT o.amount) ошибается, когда у двух заказов канала одинаковая сумма;
  * group_by_id — GROUP BY канал и заказ: строка на заказ, а не на канал.
Ключ проверяется исполнением каждого варианта в sqlite3 на данных, где все три ошибки проявляются.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, run_sql

FAMILY_ID = "analyst.sql.join_fanout_fix"

CTX = [("книжный интернет-магазин", "books", ["books", "toys", "stationery"], ["web", "app", "partner"]),
       ("магазин электроники", "accessories", ["accessories", "phones", "laptops"], ["web", "app", "retail"]),
       ("сервис доставки продуктов", "dairy", ["dairy", "bakery", "fruit"], ["app", "web", "phone"]),
       ("аптечная сеть", "vitamins", ["vitamins", "cosmetics", "medicines"], ["app", "web", "pickup"]),
       ("зоомагазин", "feed", ["feed", "toys", "care"], ["web", "app", "marketplace"]),
       ("магазин спорттоваров", "shoes", ["shoes", "clothes", "equipment"], ["web", "app", "retail"])]


def _q(kind, cat, alias_n, alias_r):
    sel_n = {"count_distinct": f"COUNT(DISTINCT o.id) AS {alias_n}"}.get(kind, f"COUNT(*) AS {alias_n}")
    sel_r = {"sum_distinct": f"SUM(DISTINCT o.amount) AS {alias_r}"}.get(kind, f"SUM(o.amount) AS {alias_r}")
    if kind == "good":
        src = (f"FROM orders o\nJOIN (SELECT DISTINCT order_id FROM order_items\n"
               f"      WHERE category = '{cat}') i ON i.order_id = o.id")
    else:
        src = f"FROM orders o\nJOIN order_items i ON i.order_id = o.id AND i.category = '{cat}'"
    grp = "GROUP BY o.channel, o.id" if kind == "group_by_id" else "GROUP BY o.channel"
    return (f"SELECT o.channel, {sel_n}, {sel_r}\n{src}\nWHERE o.status = 'paid'\n{grp}\nORDER BY o.channel;")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cat, cats, chans = rng.choice(CTX)
    alias_n = rng.choice(["orders", "orders_cnt", "n_orders"])
    alias_r = rng.choice(["revenue", "revenue_rub", "gmv"])
    dist = ["count_distinct", "sum_distinct", "group_by_id"]
    for _ in range(3000):
        orders, items, iid = [], [], 0
        for oid in range(1, rng.randint(7, 9) + 1):
            orders.append((oid, rng.choice(chans[:2]), rng.choice([900, 1200, 1500, 2400, 3100]),
                           rng.choice(["paid", "paid", "paid", "cancelled"])))
            for _ in range(rng.randint(1, 3)):
                iid += 1
                items.append((iid, oid, rng.choice(cats), rng.randint(1, 3)))
        sel = [o for o in orders if o[3] == "paid" and any(i[1] == o[0] and i[2] == cat for i in items)]
        exp = []
        for ch in sorted({o[1] for o in sel}):
            mine = [o for o in sel if o[1] == ch]
            exp.append(f"{ch}|{len(mine)}|{sum(o[2] for o in mine)}")
        good_out = "\n".join(exp)
        setup = ("CREATE TABLE orders (id INTEGER PRIMARY KEY, channel TEXT NOT NULL, amount INTEGER NOT NULL, "
                 "status TEXT NOT NULL);\n" + sql_inserts("orders", ["id", "channel", "amount", "status"], orders) +
                 "\nCREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, category TEXT NOT NULL, "
                 "qty INTEGER NOT NULL);\n" + sql_inserts("order_items", ["id", "order_id", "category", "qty"], items)
                 + "\n")
        if len(exp) < 2 or run_sql(setup, _q("good", cat, alias_n, alias_r)) != good_out:
            continue
        outs = [run_sql(setup, _q(d, cat, alias_n, alias_r)) for d in dist]
        buggy_out = run_sql(setup, _q("buggy", cat, alias_n, alias_r))
        if all(o != good_out for o in outs) and buggy_out != good_out and len(set(outs)) == 3:
            break
    else:
        raise RuntimeError("нет данных")
    code = _q("buggy", cat, alias_n, alias_r)
    label = "Заменить запрос на:"
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label, _q("good", cat, alias_n, alias_r)),
                                 [(label, _q(d, cat, alias_n, alias_r)) for d in dist])
    checks = [Check(name="buggy_differs", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_differs", expected_stdout=good_out)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="sqlite", program=o.code, files={"setup.sql": setup},
                            embeds_display_code=False, expect="stdout_equals" if o.id == key else "stdout_differs",
                            expected_stdout=good_out))
    stem = (f"Аналитик ({ctx}) считает по каналам продаж число и выручку оплаченных заказов, в которых есть хотя "
            f"бы одна позиция категории `{cat}`. Отчёт показывает больше заказов и выручки, чем в учётной "
            f"системе. Данные:\n\n`orders`:\n{text_table(['id', 'channel', 'amount', 'status'], orders)}\n\n"
            f"`order_items`:\n{text_table(['id', 'order_id', 'category', 'qty'], items)}\n\n"
            f"Какой из запросов даёт правильный результат на любых данных?")
    why = {"count_distinct": "COUNT(DISTINCT o.id) исправляет число заказов, но сумма по-прежнему считает заказ "
                             "столько раз, сколько в нём позиций категории",
           "sum_distinct": "SUM(DISTINCT o.amount) складывает различные суммы — два разных заказа с одинаковой "
                           "суммой сольются",
           "group_by_id": "группировка по каналу и заказу даёт строку на заказ, а не итог по каналу, и повторы "
                          "внутри заказа всё равно суммируются"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Соединение с позициями повторяет заказ на каждую позицию категории. Верно — "
                                "сначала получить множество заказов с категорией (DISTINCT order_id) и соединять с "
                                "ним. Дистракторы: " + "; ".join(why[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="join_fanout", language="sql",
                         params={"category": cat, "distractors": dist})
