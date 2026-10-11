"""analyst.sql.null_aggregate_output — predict_output: агрегаты SQL и NULL.

Небольшая таблица клиентов с пропусками (NULL) и запрос с 3–4 агрегатами из набора: COUNT(*), COUNT(столбец),
COUNT(DISTINCT столбец), SUM, ROUND(AVG, 1), иногда с фильтром «<> значение» (строки с NULL в фильтре
отбрасываются). Нужно предсказать строку результата. Ключ — независимый расчёт на Python, сверенный с
исполнением показанного запроса в sqlite3.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "analyst.sql.null_aggregate_output"

CTX = [("clients", "клиенты интернет-магазина", ["Москва", "Казань", "Пермь", "Тула"], "bonus"),
       ("members", "участники программы лояльности", ["Самара", "Омск", "Сочи", "Уфа"], "points"),
       ("drivers", "водители службы доставки", ["Тверь", "Курск", "Псков", "Орёл"], "rating_bonus"),
       ("tenants", "арендаторы бизнес-центра", ["Ярославль", "Иркутск", "Томск", "Чита"], "deposit"),
       ("students", "слушатели онлайн-курсов", ["Москва", "Липецк", "Тула", "Киров"], "cashback")]


def _avg1(vals):
    """Как ROUND(AVG(x), 1) в SQLite для целых без половинок на втором знаке."""
    return round(sum(vals) / len(vals) + 1e-12, 1) if vals else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(2000):
        T, ctx, cities, num = rng.choice(CTX)
        n = rng.randint(6, 8)
        rows = []
        for i in range(1, n + 1):
            city = rng.choice(cities[:3]) if rng.random() < 0.75 else None
            phone = f"+7 9{rng.randint(10, 99)} {rng.randint(100, 999)}-{rng.randint(10, 99)}" \
                if rng.random() < 0.7 else None
            val = rng.choice([100, 150, 200, 300, 400, 500]) if rng.random() < 0.7 else None
            rows.append((i, city, phone, val))
        nulls = [sum(r[j] is None for r in rows) for j in (1, 2, 3)]
        if min(nulls) < 1 or max(nulls) > 3:
            continue
        flt = rng.choice([None, "city"])
        fcity = rng.choice(sorted({r[1] for r in rows if r[1]}))
        sel = [r for r in rows if (flt is None or (r[1] is not None and r[1] != fcity))]
        if len(sel) < 3:
            continue
        pool = ["count_all", "count_phone", "count_distinct_city", "sum", "avg"]
        aggs = ["count_all"] + rng.sample(pool[1:], rng.choice([2, 3]))
        vals = [r[3] for r in sel if r[3] is not None]
        if not vals:
            continue
        avg = _avg1(vals)
        if abs(sum(vals) * 100 / len(vals) - round(sum(vals) * 100 / len(vals))) < 1e-9 and \
                (sum(vals) * 100 // len(vals)) % 10 == 5:
            continue  # половинка на втором знаке — разное округление
        res = {"count_all": len(sel), "count_phone": sum(r[2] is not None for r in sel),
               "count_distinct_city": len({r[1] for r in sel if r[1] is not None}),
               "sum": sum(vals), "avg": avg}
        out = "|".join(str(res[a]) for a in aggs)
        if len(set(res[a] for a in aggs)) == len(aggs):
            break
    else:
        raise RuntimeError("нет данных")
    expr = {"count_all": "COUNT(*)", "count_phone": "COUNT(phone)", "count_distinct_city": "COUNT(DISTINCT city)",
            "sum": f"SUM({num})", "avg": f"ROUND(AVG({num}), 1)"}
    alias = {"count_all": "total", "count_phone": "with_phone", "count_distinct_city": "cities",
             "sum": f"{num}_sum", "avg": f"{num}_avg"}
    lines = ["SELECT " + ",\n       ".join(f"{expr[a]} AS {alias[a]}" for a in aggs), f"FROM {T}"]
    if flt:
        lines.append(f"WHERE city <> '{fcity}'")
    code = "\n".join(lines) + ";"
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, city TEXT, phone TEXT, {num} INTEGER);\n"
             + sql_inserts(T, ["id", "city", "phone", num], rows) + "\n")
    checks = [Check(name="run", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    stem = (f"Таблица `{T}` ({ctx}); NULL — значение не заполнено:\n\n"
            f"{text_table(['id', 'city', 'phone', num], rows)}\n\n"
            f"Что вернёт запрос (SQLite)? Ответ — значения столбцов через «|», как в выводе sqlite3, например "
            f"`5|2|300`" + ("; результат AVG — вещественное число, печатается с точкой (например, `240.0`)."
                            if "avg" in aggs else "."))
    notes = ["COUNT(*) считает строки" + (", COUNT(phone) — только непустые значения" if "count_phone" in aggs else "")]
    if "count_distinct_city" in aggs:
        notes.append("COUNT(DISTINCT city) не считает NULL")
    if "sum" in aggs or "avg" in aggs:
        notes.append("SUM и AVG пропускают NULL (AVG делит на число непустых значений)")
    if flt:
        notes.append(f"условие city <> '{fcity}' для NULL даёт «неизвестно» — такие строки отбрасываются")
    ak = AnswerKey(kind="output", value=out, explanation=f"Результат: {out}. " + "; ".join(notes) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="sql",
                         params={"aggs": aggs, "filter": flt, "n_rows": len(rows)})
