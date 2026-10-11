"""data_eng.sql.null_agg_canary — predict_output (канарейка): агрегаты и NULL.

Канареечное семейство: seed 1..30 опубликованы, служат детектору предзнания, в грейд не входят.
COUNT(*) считает строки, COUNT(col), SUM, AVG, MAX пропускают NULL; COALESCE подставляет значение до агрегата.
Ключ — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.null_agg_canary"

CTX = [("скидки по заказам", "orders", "discount"), ("бонусы сотрудникам", "bonuses", "bonus"),
       ("оценки отзывов", "reviews", "rating"), ("чаевые курьерам", "tips", "tip")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, col = rng.choice(CTX)
    n = rng.randint(4, 6)
    vals = [rng.choice([None, 10, 20, 30, 40]) for _ in range(n)]
    if all(v is None for v in vals) or None not in vals:
        vals[0], vals[-1] = None, 20
    exprs = rng.sample(["COUNT(*)", f"COUNT({col})", f"SUM({col})", f"AVG({col})", f"MAX({col})",
                        f"AVG(COALESCE({col}, 0))"], 4)
    code = f"SELECT {', '.join(exprs)}\nFROM {table};"
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {col} INTEGER);\n"
             + insert(table, ["id", col], [(i + 1, v) for i, v in enumerate(vals)]))
    out = rows(setup, code)
    shown = ", ".join("NULL" if v is None else str(v) for v in vals)
    stem = (f"В таблице `{table}` ({ctx}) столбец `{col}` по строкам: {shown}. Что вернёт запрос? Ответ — строка "
            "значений через `|` (дробные — как выведет sqlite, например `25.0`).")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out, explanation="COUNT(*) считает все строки; COUNT, SUM, AVG и MAX по "
                   "столбцу пропускают NULL; COALESCE превращает NULL в 0 до усреднения.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"exprs": exprs})
