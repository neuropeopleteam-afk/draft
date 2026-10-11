"""data_eng.sql.window_rank_output — predict_output: ROW_NUMBER, RANK и DENSE_RANK при равных значениях.

Запрос «топ-k по группе» через оконную функцию и фильтр `r <= k`. Подтип один — поведение на равных
значениях: ROW_NUMBER оставляет ровно k строк (порядок равных задан вторым ключом сортировки), RANK
пропускает номера после равных, DENSE_RANK — нет, поэтому строк может быть больше k. Ключ — исполнение
запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.window_rank_output"

CTX = [("выручка товаров по категориям", "sales_summary", "category", "product", "revenue",
        ["books", "games", "toys"], ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]),
       ("баллы участников по командам", "scores", "team", "player", "points", ["red", "blue", "green"],
        ["ann", "bob", "cat", "dan", "eve", "fox", "gus"]),
       ("продажи менеджеров по регионам", "manager_sales", "region", "manager", "deals", ["north", "south", "west"],
        ["ivanov", "petrov", "sidorov", "orlov", "lebedev", "volkov", "zaitsev"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, grp, item, val, groups, items = rng.choice(CTX)
    fn = rng.choice(["ROW_NUMBER", "RANK", "DENSE_RANK"])
    k = rng.choice([1, 2])
    gs = rng.sample(groups, 2)
    for _ in range(500):
        data, pool = [], rng.sample(items, 7)
        for g in gs:
            for it in pool[: rng.randint(3, 4)]:
                data.append((g, it, rng.choice([10, 20, 20, 30, 30, 40])))
            pool = pool[2:] + pool[:2]
        tie = ", " + item if fn == "ROW_NUMBER" else ""
        code = (f"WITH ranked AS (\n  SELECT {grp}, {item}, {val},\n"
                f"         {fn}() OVER (PARTITION BY {grp} ORDER BY {val} DESC{tie}) AS r\n  FROM {table}\n)\n"
                f"SELECT {grp}, {item}, {val}, r\nFROM ranked\nWHERE r <= {k}\nORDER BY {grp}, r, {item};")
        setup = f"CREATE TABLE {table} ({grp} TEXT, {item} TEXT, {val} INTEGER);\n" + insert(
            table, [grp, item, val], data)
        out = rows(setup, code)
        outs = {f: rows(setup, code.replace(fn + "()", f + "()")) for f in ("ROW_NUMBER", "RANK", "DENSE_RANK")}
        if len(set(outs.values())) >= 2 and len(set((g, v) for g, _, v in data)) < len(data):
            break
    tbl = "\n".join(f"{g} | {it} | {v}" for g, it, v in data)
    stem = (f"Таблица `{table}` ({ctx}), строки ({grp} | {item} | {val}):\n{tbl}\nЧто вернёт запрос? Ответ — "
            "строки вида `a|b|c|d`.")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"{fn}: " + {"ROW_NUMBER": "номера без повторов, равные упорядочены вторым ключом — "
                                                          "ровно k строк на группу",
                                            "RANK": "равные получают один номер, следующий номер пропускается",
                                            "DENSE_RANK": "равные получают один номер, без пропусков — строк может "
                                                          "быть больше k"}[fn] + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"fn": fn, "k": k})
