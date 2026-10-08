"""common.sql.aggregate_filter_fix — choose_fix: агрегат в WHERE, верный вариант с HAVING."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.aggregate_filter_fix"

# (таблица, субъект, дата, успешный статус, другие статусы, «кто», «что», контекст)
CONTEXTS = [
    ("orders", "customer_id", "created_at", "paid", ["cancelled", "new"], "клиентов", "оплаченных заказов", "магазин"),
    ("payments", "user_id", "paid_at", "succeeded", ["failed", "refunded"], "пользователей", "успешных платежей", "финтех"),
    ("tickets", "operator_id", "closed_at", "resolved", ["reopened", "spam"], "операторов", "решённых обращений", "поддержка"),
    ("trips", "driver_id", "finished_at", "completed", ["cancelled", "disputed"], "водителей", "завершённых поездок", "такси"),
]
DISTRACTORS = ["no_status", "between_dates", "strict_gt", "count_bool"]


def _q(kind, T, subj, dcol, st, k, y):
    lo, hi = f"'{y}-01-01'", f"'{y + 1}-01-01'"
    date_ok = f"{dcol} >= {lo} AND {dcol} < {hi}"
    where = f"WHERE status = '{st}'\n  AND {date_ok}"
    having = f"HAVING COUNT(*) >= {k}"
    if kind == "no_status":
        where = f"WHERE {date_ok}"
    elif kind == "between_dates":
        where = f"WHERE status = '{st}'\n  AND {dcol} BETWEEN '{y}-01-01' AND '{y}-12-31'"
    elif kind == "strict_gt":
        having = f"HAVING COUNT(*) > {k}"
    elif kind == "count_bool":
        where = f"WHERE {date_ok}"
        having = f"HAVING COUNT(status = '{st}') >= {k}"
    return f"SELECT {subj}\nFROM {T}\n{where}\nGROUP BY {subj}\n{having}\nORDER BY {subj};"


def _ref(kind, rows, st, k, y):
    counts: dict[int, int] = {}
    for _id, subj, status, ts in rows:
        in_year = f"{y}-01-01" <= ts < f"{y + 1}-01-01"
        if kind == "between_dates":
            in_year = f"{y}-01-01" <= ts <= f"{y}-12-31"
        ok_status = status == st or kind in ("no_status", "count_bool")
        if in_year and ok_status:
            counts[subj] = counts.get(subj, 0) + 1
    thr = (lambda c: c > k) if kind == "strict_gt" else (lambda c: c >= k)
    return "\n".join(str(s) for s in sorted(counts) if thr(counts[s]))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, subj, dcol, st, others, who, what, ctx = rng.choice(CONTEXTS)
    k = rng.randint(2, 3)
    y = rng.choice([2024, 2025, 2026])
    chosen = rng.sample(DISTRACTORS, 3)
    for _ in range(5000):
        rows, rid = [], rng.randint(1, 30)
        subjects = rng.sample(range(10, 60), rng.randint(4, 6))
        for s in subjects:
            for _ in range(rng.randint(1, 5)):
                rid += 1
                yr = rng.choice([y - 1, y, y, y, y + 1])
                if rng.random() < 0.18:
                    ts = f"{y}-12-31 {rng.randint(8, 23):02d}:{rng.randint(0, 59):02d}:00"
                else:
                    ts = f"{yr}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00"
                status = st if rng.random() < 0.6 else rng.choice(others)
                rows.append((rid, s, status, ts))
        good = _ref("good", rows, st, k, y)
        if good and len(rows) <= 16 and all(_ref(d, rows, st, k, y) != good for d in chosen):
            break
    else:
        raise RuntimeError("не удалось подобрать данные")
    rows.sort()
    buggy = (f"SELECT {subj}\nFROM {T}\nWHERE status = '{st}'\n  AND {dcol} >= '{y}-01-01' "
             f"AND {dcol} < '{y + 1}-01-01'\n  AND COUNT(*) >= {k}\nGROUP BY {subj}\nORDER BY {subj};")
    correct = _q("good", T, subj, dcol, st, k, y)
    # текст варианта — нейтральная подпись, сам запрос показывается один раз (в блоке кода)
    label = "Заменить запрос на:"
    opts, key = make_options(rng, (label, correct), [(label, _q(d, T, subj, dcol, st, k, y)) for d in chosen])
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {subj} INTEGER NOT NULL, "
             f"status TEXT NOT NULL, {dcol} TEXT NOT NULL);\n"
             + sql_inserts(T, ["id", subj, "status", dcol], rows) + "\n")
    stem = (f"Нужно получить id {who}, у которых не меньше {k} {what} за {y} год, по возрастанию "
            f"id. Столбец `{dcol}` хранит дату и время (TIMESTAMP). Аналитик написал запрос, но "
            f"он падает с ошибкой «aggregate functions are not allowed in WHERE». Какой из "
            f"вариантов решает задачу правильно (на любых данных, а не только на примере)?\n\n"
            f"Пример данных `{T}`:\n{text_table(['id', subj, 'status', dcol], rows)}")
    checks = [Check(name="buggy_errors", runner="sqlite", program=buggy, files={"setup.sql": setup},
                    expect="stdout_differs", expected_stdout=good)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="sqlite", program=o.code,
                            files={"setup.sql": setup}, embeds_display_code=False,
                            expect="stdout_equals" if o.id == key else "stdout_differs",
                            expected_stdout=good))
    why = {"no_status": "нет фильтра по статусу — считаются все записи",
           "between_dates": f"BETWEEN … '{y}-12-31' теряет записи 31 декабря после полуночи",
           "strict_gt": f"«> {k}» вместо «>= {k}»",
           "count_bool": "COUNT(условие) считает все непустые значения, в том числе false"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Фильтр по строкам — в WHERE, по агрегату — в HAVING, год — "
                               "полуоткрытым интервалом. Ошибки дистракторов: "
                               + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="aggregate_in_where", params={"distractors": chosen, "k": k, "year": y})
