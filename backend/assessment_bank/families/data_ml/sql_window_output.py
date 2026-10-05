"""data_ml.sql.window_output — predict_output: результат запроса с оконными функциями (sqlite).

Шаблоны (ловушки):
* ``row_number`` / ``rank`` / ``dense_rank`` — топ-2 в группе при равных значениях:
  ROW_NUMBER отрезает, RANK пропускает места, DENSE_RANK не пропускает;
* ``running_peers`` — накопительная сумма ``SUM() OVER (PARTITION BY … ORDER BY дата)``:
  рамка по умолчанию RANGE … CURRENT ROW включает «равных» по дате — строки одной даты
  получают одинаковую сумму;
* ``lag_diff`` — разница с предыдущей записью через LAG: у первой записи группы NULL.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.sql.window_output"

RANK_CTX = [
    ("seller_sales", "region", "seller", "sales", "продажи по регионам",
     ["north", "south"], ["Анна", "Борис", "Вера", "Глеб", "Дина", "Егор", "Ия", "Кира"]),
    ("exam_scores", "course", "student", "score", "оценки на курсах",
     ["sql", "ml"], ["Лев", "Мила", "Ника", "Олег", "Петр", "Рита", "Саша", "Тая"]),
    ("app_stats", "category", "app", "installs", "магазин приложений",
     ["games", "tools"], ["alpha", "beta", "gamma", "delta", "omega", "sigma", "kappa", "zeta"]),
]
SEQ_CTX = [
    ("orders", "customer_id", "order_date", "amount", "покупки клиентов"),
    ("transfers", "account_id", "op_date", "amount", "банковские переводы"),
    ("deliveries", "courier_id", "day", "parcels", "курьерская доставка"),
]
TEMPLATES = ["row_number", "rank", "dense_rank", "running_peers", "lag_diff"]


def _rank_query(fn, T, g, nm, val):
    order = f"{val} DESC, {nm}" if fn == "ROW_NUMBER" else f"{val} DESC"
    return (f"SELECT {g}, {nm}, {val}\nFROM (\n  SELECT {g}, {nm}, {val},\n"
            f"         {fn}() OVER (PARTITION BY {g} ORDER BY {order}) AS pos\n"
            f"  FROM {T}\n) t\nWHERE pos <= 2\nORDER BY {g}, {val} DESC, {nm};")


def _rank_ref(fn, rows):
    out = []
    for grp in sorted({r[1] for r in rows}):
        items = sorted([r for r in rows if r[1] == grp], key=lambda r: (-r[3], r[2]))
        for i, r in enumerate(items):
            if fn == "ROW_NUMBER":
                pos = i + 1
            elif fn == "RANK":
                pos = 1 + sum(1 for x in items if x[3] > r[3])
            else:
                pos = 1 + len({x[3] for x in items if x[3] > r[3]})
            if pos <= 2:
                out.append(f"{r[1]}|{r[2]}|{r[3]}")
    return "\n".join(out)


def _seq_query(t, T, g, d, val):
    if t == "running_peers":
        sel = f"SUM({val}) OVER (PARTITION BY {g} ORDER BY {d}) AS running"
    else:
        sel = f"{val} - LAG({val}) OVER (PARTITION BY {g} ORDER BY {d}, id) AS diff"
    return f"SELECT id, {g}, {d}, {val},\n       {sel}\nFROM {T}\nORDER BY {g}, {d}, id;"


def _seq_ref(t, rows):
    out = []
    for grp in sorted({r[1] for r in rows}):
        items = sorted([r for r in rows if r[1] == grp], key=lambda r: (r[2], r[0]))
        prev = None
        for r in items:
            if t == "running_peers":
                v = sum(x[3] for x in items if x[2] <= r[2])  # RANGE: включая равных по дате
            else:
                v = "NULL" if prev is None else r[3] - prev
                prev = r[3]
            out.append(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{v}")
    return "\n".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    t = rng.choice(TEMPLATES)
    if t in ("row_number", "rank", "dense_rank"):
        T, g, nm, val, ctx, groups, names = rng.choice(RANK_CTX)
        fn = {"row_number": "ROW_NUMBER", "rank": "RANK", "dense_rank": "DENSE_RANK"}[t]
        while True:
            people = rng.sample(names, rng.randint(6, 7))
            rows, rid = [], rng.randint(1, 20)
            for p in people:
                rid += 1
                rows.append((rid, rng.choice(groups), p, rng.randint(2, 9) * 10))
            ok = True
            for grp in groups:
                vals = sorted([r[3] for r in rows if r[1] == grp], reverse=True)
                if len(vals) < 3:
                    ok = False
                    break
            # ничья на первом или втором месте хотя бы в одной группе — суть задания
            ties = [grp for grp in groups
                    if len(set(sorted([r[3] for r in rows if r[1] == grp], reverse=True)[:3])) < 3]
            if ok and ties:
                break
        query = _rank_query(fn, T, g, nm, val)
        out = _rank_ref(fn, rows)
        setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {g} TEXT NOT NULL, {nm} TEXT NOT NULL, "
                 f"{val} INTEGER NOT NULL);\n" + sql_inserts(T, ["id", g, nm, val], rows) + "\n")
        table = text_table(["id", g, nm, val], rows)
        trap = {"ROW_NUMBER": "ROW_NUMBER нумерует подряд даже при равных значениях (порядок ничьей — по имени)",
                "RANK": "RANK даёт равным одинаковое место и пропускает следующие (1, 1, 3)",
                "DENSE_RANK": "DENSE_RANK даёт равным одинаковое место без пропусков (1, 1, 2)"}[fn]
    else:
        T, g, d, val, ctx = rng.choice(SEQ_CTX)
        month = rng.randint(1, 12)
        while True:
            rows, rid = [], rng.randint(1, 50)
            for grp in rng.sample(range(10, 40), 2):
                days = sorted(rng.sample(range(1, 28), 3))
                if t == "running_peers" and rng.random() < 0.8:
                    days.append(rng.choice(days))  # две записи в одну дату
                else:
                    days.append(rng.choice([x for x in range(1, 28) if x not in days]))
                for day in sorted(days):
                    rid += rng.randint(1, 3)
                    rows.append((rid, grp, f"2026-{month:02d}-{day:02d}", rng.randint(1, 30) * 10))
            dup = any(sum(1 for y in rows if (y[1], y[2]) == (x[1], x[2])) > 1 for x in rows)
            if t == "lag_diff" or dup:
                break
        query = _seq_query(t, T, g, d, val)
        out = _seq_ref(t, rows)
        setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {g} INTEGER NOT NULL, {d} TEXT NOT NULL, "
                 f"{val} INTEGER NOT NULL);\n" + sql_inserts(T, ["id", g, d, val], rows) + "\n")
        table = text_table(["id", g, d, val], rows)
        trap = ("при ORDER BY без явной рамки действует RANGE BETWEEN UNBOUNDED PRECEDING AND "
                "CURRENT ROW: строки с одинаковой датой — «равные» и получают одну и ту же сумму"
                if t == "running_peers" else
                "LAG у первой строки группы возвращает NULL, и разность тоже NULL")
    stem = (f"Таблица `{T}` ({ctx}):\n{table}\n\nЧто вернёт запрос? Запишите строки результата по "
            "порядку, по одной в строке, значения через «|» (например: `a|1|20`); отсутствующее "
            "значение записывайте как NULL.")
    ak = AnswerKey(kind="output", value=out, explanation=f"Ключевая деталь: {trap}.")
    checks = [Check(name="stdout", runner="sqlite", program=query, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=query, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"template": t})
