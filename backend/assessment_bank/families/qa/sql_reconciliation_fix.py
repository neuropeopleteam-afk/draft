"""qa.sql.reconciliation_fix — choose_fix (sqlite): сверка источника и хранилища после загрузки.

Тестировщик данных сверяет таблицу-источник и таблицу хранилища (DWH) после ночной
загрузки: нужны id записей источника, которых нет в DWH или у которых отличается любое из
двух полей; NULL против значения — расхождение, NULL в обеих таблицах — нет. Показанный
запрос (INNER JOIN и ``<>``) теряет два класса расхождений: пропавшие записи и NULL против
значения (``NULL <> 'x'`` даёт NULL, а не TRUE). Правильный вариант — LEFT JOIN и
null-безопасное сравнение ``IS DISTINCT FROM``. Дистракторы: LEFT JOIN, но ``<>``; INNER JOIN
с IS DISTINCT FROM; только NOT IN (одни пропавшие); AND вместо OR между полями. Данные
генерируются так, что каждый дистрактор на них ошибается; все запросы исполняются в sqlite.
"""
from __future__ import annotations

import sqlite3

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options

FAMILY_ID = "qa.sql.reconciliation_fix"

CONTEXTS = [
    ("выгрузка заказов в DWH", "orders", "amount", "status", ["new", "paid", "shipped", "cancelled"],
     lambda r: r.randrange(300, 20000, 10)),
    ("платежи из процессинга", "payments", "amount", "state", ["authorized", "captured", "refunded"],
     lambda r: r.randrange(100, 90000, 50)),
    ("отгрузки со склада", "shipments", "weight_g", "carrier", ["cdek", "boxberry", "pochta"],
     lambda r: r.randrange(100, 30000, 25)),
    ("счета учётной системы", "invoices", "total", "currency", ["RUB", "USD", "CNY"],
     lambda r: r.randrange(1000, 500000, 100)),
    ("бронирования отелей", "bookings", "nights", "room_type", ["std", "lux", "suite"],
     lambda r: r.randint(1, 21)),
    ("заявки на кредит", "loan_apps", "amount", "decision", ["approved", "rejected", "manual"],
     lambda r: r.randrange(50000, 3000000, 5000)),
    ("каталог товаров", "products", "price", "category", ["audio", "video", "home", "sport"],
     lambda r: r.randrange(490, 99990, 10)),
    ("абоненты оператора", "subscribers", "fee", "plan", ["basic", "plus", "max"],
     lambda r: r.randrange(200, 2500, 50)),
]

PREFIXES = [("src", "dwh"), ("stg", "dm"), ("raw", "core")]
ALIASES = [("s", "d"), ("src", "tgt"), ("a", "b")]


def _q(kind, t, a, b, names):
    (ps, pd), (s_, d_) = names
    s, d = f"{ps}_{t}", f"{pd}_{t}"
    q = _q_raw(kind, s, d, a, b)
    return q.replace("§s", s_).replace("§d", d_)


def _q_raw(kind, s, d, a, b):
    if kind == "buggy":
        return (f"SELECT §s.id\nFROM {s} AS §s\nJOIN {d} AS §d ON §d.id = §s.id\n"
                f"WHERE §s.{a} <> §d.{a} OR §s.{b} <> §d.{b}\nORDER BY §s.id;")
    if kind == "good":
        return (f"SELECT §s.id\nFROM {s} AS §s\nLEFT JOIN {d} AS §d ON §d.id = §s.id\n"
                f"WHERE §d.id IS NULL\n   OR §s.{a} IS DISTINCT FROM §d.{a}\n"
                f"   OR §s.{b} IS DISTINCT FROM §d.{b}\nORDER BY §s.id;")
    if kind == "left_neq":
        return (f"SELECT §s.id\nFROM {s} AS §s\nLEFT JOIN {d} AS §d ON §d.id = §s.id\n"
                f"WHERE §d.id IS NULL\n   OR §s.{a} <> §d.{a}\n   OR §s.{b} <> §d.{b}\nORDER BY §s.id;")
    if kind == "inner_distinct":
        return (f"SELECT §s.id\nFROM {s} AS §s\nJOIN {d} AS §d ON §d.id = §s.id\n"
                f"WHERE §s.{a} IS DISTINCT FROM §d.{a}\n   OR §s.{b} IS DISTINCT FROM §d.{b}\n"
                f"ORDER BY §s.id;")
    if kind == "not_in":
        return (f"SELECT §s.id\nFROM {s} AS §s\nWHERE §s.id NOT IN (\n    SELECT §d.id FROM {d} AS §d\n)\n"
                f"ORDER BY §s.id;")
    if kind == "and_fields":
        return (f"SELECT §s.id\nFROM {s} AS §s\nLEFT JOIN {d} AS §d ON §d.id = §s.id\n"
                f"WHERE §d.id IS NULL\n   OR (§s.{a} IS DISTINCT FROM §d.{a}\n"
                f"       AND §s.{b} IS DISTINCT FROM §d.{b})\nORDER BY §s.id;")
    raise ValueError(kind)


def _run(setup, query):
    con = sqlite3.connect(":memory:")
    con.executescript(setup)
    return [r[0] for r in con.execute(query).fetchall()]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, t, a, b, cats, gen = rng.choice(CONTEXTS)
    names = (rng.choice(PREFIXES), rng.choice(ALIASES))
    st, dt = f"{names[0][0]}_{t}", f"{names[0][1]}_{t}"
    n = rng.randint(8, 11)
    ids = sorted(rng.sample(range(1001, 1100), n))
    src = []
    for i in ids:
        src.append([i, gen(rng), rng.choice(cats)])
    # обе NULL — не расхождение
    src[rng.randrange(n)][2] = None
    dwh = {r[0]: list(r) for r in src}
    pool = [r[0] for r in src if r[2] is not None]
    rng.shuffle(pool)
    missing = pool[0]
    null_vs_val = pool[1]
    val_diff = pool[2]
    num_diff = pool[3]
    del dwh[missing]
    dwh[null_vs_val][2] = None if rng.random() < 0.5 else dwh[null_vs_val][2]
    if dwh[null_vs_val][2] is not None:   # NULL в источнике, значение в DWH
        for r in src:
            if r[0] == null_vs_val:
                r[2] = None
    dwh[val_diff][2] = rng.choice([c for c in cats if c != dwh[val_diff][2]])
    dwh[num_diff][1] = dwh[num_diff][1] + rng.choice([-1, 1]) * rng.choice([1, 10, 100])
    if dwh[num_diff][1] <= 0:
        dwh[num_diff][1] += 200
    orphan = max(ids) + rng.randint(1, 9)
    dwh[orphan] = [orphan, gen(rng), rng.choice(cats)]
    dwh_rows = sorted(dwh.values())
    cols = ["id", a, b]
    num_type = "INTEGER"
    setup = (f"CREATE TABLE {st} (id INTEGER PRIMARY KEY, {a} {num_type} NOT NULL, {b} TEXT);\n"
             f"CREATE TABLE {dt} (id INTEGER PRIMARY KEY, {a} {num_type} NOT NULL, {b} TEXT);\n"
             + sql_inserts(st, cols, [tuple(r) for r in src]) + "\n"
             + sql_inserts(dt, cols, [tuple(r) for r in dwh_rows]) + "\n")
    expected = sorted({missing, null_vs_val, val_diff, num_diff})
    good = _q("good", t, a, b, names)
    assert _run(setup, good) == expected, (_run(setup, good), expected)
    buggy = _q("buggy", t, a, b, names)
    assert _run(setup, buggy) != expected
    pool_d = ["left_neq", "inner_distinct", "not_in", "and_fields"]
    chosen = rng.sample(pool_d, 3)
    for d in chosen:
        assert _run(setup, _q(d, t, a, b, names)) != expected, d
    good_out = "\n".join(str(i) for i in expected)
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить запрос на:", good),
                                 [("Заменить запрос на:", _q(d, t, a, b, names)) for d in chosen])
    checks = [Check(name="buggy_differs", runner="sqlite", program=buggy,
                    files={"setup.sql": setup}, expect="stdout_differs", expected_stdout=good_out)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="sqlite", program=o.code,
                            files={"setup.sql": setup}, embeds_display_code=False,
                            expect="stdout_equals" if o.id == key else "stdout_differs",
                            expected_stdout=good_out))
    stem = (f"Тестирование данных ({ctx}): после ночной загрузки нужно сверить таблицу-источник "
            f"`{st}` с таблицей хранилища `{dt}` (обе — id, `{a}`, `{b}`; `{b}` может быть "
            f"NULL). Нужны id записей источника, которых нет в хранилище или у которых "
            f"отличается `{a}` или `{b}`; NULL в одной таблице и значение в другой — расхождение, "
            f"NULL в обеих — нет. Запрос ниже на тестовых данных нашёл не все расхождения. "
            f"Какой запрос находит все расхождения на любых данных?")
    why = {"left_neq": "LEFT JOIN возвращает пропавшие записи, но `<>` с NULL даёт NULL — "
                       "расхождение «NULL против значения» теряется",
           "inner_distinct": "сравнение null-безопасное, но INNER JOIN отбрасывает записи, "
                             "которых нет в хранилище",
           "not_in": "находит только пропавшие записи, расхождения значений не ищет",
           "and_fields": "AND между полями требует, чтобы отличались оба поля сразу"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Нужны LEFT JOIN (чтобы увидеть записи, которых нет в хранилище) "
                                f"и null-безопасное сравнение IS DISTINCT FROM. На тестовых данных "
                                f"расхождения: {', '.join(map(str, expected))}. Дистракторы: "
                                + "; ".join(why[d] for d in chosen) + ". Равнозначная "
                                "альтернатива — EXCEPT по всем столбцам (NULL там считаются "
                                "равными)."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="null_unsafe_reconciliation",
                         params={"distractors": chosen, "expected_ids": expected})
