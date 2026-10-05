"""common.sql.window_rank — predict_output: оконные функции, ничьи, рамка по умолчанию, LAG.

Ловушки: RANK даёт пропуски после ничьей, DENSE_RANK — нет; SUM(...) OVER (ORDER BY x) по
умолчанию использует рамку RANGE ... CURRENT ROW и включает все строки-«ровесники» с тем же x;
LAG возвращает NULL для первой строки секции. Ключ — независимая модель и исполнение в SQLite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.window_rank"

# (таблица, столбец группы, столбец порядка, числовой столбец, имена, контекст)
CONTEXTS = [("sales", "manager", "day", "amount", ["Анна", "Борис", "Вера"], "продажи менеджеров"),
            ("payments", "client", "day", "total", ["ООО Ромашка", "ИП Петров", "АО Вектор"], "платежи клиентов"),
            ("deploys", "team", "week", "incidents", ["core", "web", "data"], "инциденты после релизов"),
            ("matches", "player", "round", "points", ["Кира", "Лев", "Мира"], "турнир по шахматам")]
TEMPLATES = ["rank_dense", "running_range", "running_rows", "lag_partition", "top_per_group"]


def _query(t, T, g, o, v):
    if t == "rank_dense":
        return (f"SELECT id, {v},\n       RANK() OVER (ORDER BY {v} DESC) AS rnk,\n"
                f"       DENSE_RANK() OVER (ORDER BY {v} DESC) AS drnk\nFROM {T}\nORDER BY id;")
    if t == "running_range":
        return (f"SELECT id, {o},\n       SUM({v}) OVER (ORDER BY {o}) AS running\nFROM {T}\n"
                f"ORDER BY id;")
    if t == "running_rows":
        return (f"SELECT id, {o},\n       SUM({v}) OVER (ORDER BY {o}, id\n"
                f"                     ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS last2\n"
                f"FROM {T}\nORDER BY id;")
    if t == "lag_partition":
        return (f"SELECT id, {g},\n       {v} - LAG({v}) OVER (PARTITION BY {g} ORDER BY {o}, id) AS diff\n"
                f"FROM {T}\nORDER BY id;")
    return (f"WITH ranked AS (\n  SELECT id, {g}, {v},\n         ROW_NUMBER() OVER (PARTITION BY {g} "
            f"ORDER BY {v} DESC, id) AS rn\n  FROM {T}\n)\nSELECT {g}, id, {v}\nFROM ranked\n"
            f"WHERE rn = 1\nORDER BY id;")


def _ref(t, rows):
    # rows: (id, group, order, value)
    out = []
    if t == "rank_dense":
        vals = sorted({r[3] for r in rows}, reverse=True)
        for r in rows:
            rnk = 1 + sum(1 for x in rows if x[3] > r[3])
            out.append(f"{r[0]}|{r[3]}|{rnk}|{vals.index(r[3]) + 1}")
    elif t == "running_range":
        for r in rows:
            out.append(f"{r[0]}|{r[2]}|{sum(x[3] for x in rows if x[2] <= r[2])}")
    elif t == "running_rows":
        order = sorted(rows, key=lambda x: (x[2], x[0]))
        pos = {x[0]: i for i, x in enumerate(order)}
        for r in rows:
            i = pos[r[0]]
            out.append(f"{r[0]}|{r[2]}|{sum(x[3] for x in order[max(0, i - 1):i + 1])}")
    elif t == "lag_partition":
        for r in rows:
            prev = sorted([x for x in rows if x[1] == r[1] and (x[2], x[0]) < (r[2], r[0])],
                          key=lambda x: (x[2], x[0]))
            out.append(f"{r[0]}|{r[1]}|{r[3] - prev[-1][3] if prev else 'NULL'}")
    else:
        best = {}
        for r in rows:
            cur = best.get(r[1])
            if cur is None or (-r[3], r[0]) < (-cur[3], cur[0]):
                best[r[1]] = r
        for r in sorted(best.values(), key=lambda x: x[0]):
            out.append(f"{r[1]}|{r[0]}|{r[3]}")
    return "\n".join(out)


def _rows(rng, groups):
    n = rng.randint(5, 6)
    ids = sorted(rng.sample(range(1, 30), n))
    orders = [rng.randint(1, 4) for _ in range(n)]
    vals = [rng.randint(1, 9) * 10 for _ in range(n)]
    return [(ids[i], rng.choice(groups), orders[i], vals[i]) for i in range(n)]


def _interesting(t, rows):
    from collections import Counter
    if t == "rank_dense":
        c = Counter(r[3] for r in rows)
        return any(k > 1 for k in c.values()) and len(c) >= 3 and \
            any(c[x] > 1 and x != min(c) for x in c)
    if t in ("running_range", "running_rows"):
        c = Counter(r[2] for r in rows)
        orders = [r[2] for r in rows]
        return any(k > 1 for k in c.values()) and orders != sorted(orders)
    if t == "lag_partition":
        c = Counter(r[1] for r in rows)
        return len(c) >= 2 and any(k >= 2 for k in c.values())
    c = Counter(r[1] for r in rows)
    return len(c) >= 2 and any(k >= 2 for k in c.values())


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, g, o, v, groups, ctx = rng.choice(CONTEXTS)
    t = rng.choice(TEMPLATES)
    for _ in range(500):
        rows = _rows(rng, groups)
        if _interesting(t, rows):
            break
    else:
        raise RuntimeError("не подобраны данные")
    query = _query(t, T, g, o, v)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {g} TEXT NOT NULL, {o} INTEGER NOT NULL, "
             f"{v} INTEGER NOT NULL);\n" + sql_inserts(T, ["id", g, o, v], rows) + "\n")
    out = _ref(t, rows)
    stem = (f"Таблица `{T}` ({ctx}):\n\n{text_table(['id', g, o, v], rows)}\n\n"
            "Что вернёт запрос (PostgreSQL или SQLite — результат одинаков)? Запишите строки "
            "результата по порядку, значения через «|» (например: `3|20|1`); NULL записывайте "
            "как NULL.")
    trap = {"rank_dense": "RANK после ничьей пропускает места (1, 1, 3), DENSE_RANK — нет (1, 1, 2)",
            "running_range": "при ORDER BY без явной рамки действует RANGE BETWEEN UNBOUNDED "
                             "PRECEDING AND CURRENT ROW: строки с одинаковым значением порядка "
                             "(«ровесники») получают одну и ту же сумму",
            "running_rows": "рамка ROWS — две физические строки (предыдущая и текущая) в порядке "
                            "(значение, id); у первой строки — только она сама",
            "lag_partition": "LAG считается внутри секции, у первой строки секции — NULL, и "
                             "разность с NULL тоже NULL",
            "top_per_group": "ROW_NUMBER нумерует внутри секции; при равных значениях выигрывает "
                             "меньший id"}[t]
    ak = AnswerKey(kind="output", value=out, explanation=f"Ключевая деталь: {trap}.")
    checks = [Check(name="stdout", runner="sqlite", program=query, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=query, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="sql",
                         params={"template": t})
