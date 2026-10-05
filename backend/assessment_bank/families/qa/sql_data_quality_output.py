"""qa.sql.data_quality_output — predict_output: что вернёт SQL-проверка качества данных (SQLite).

Шесть видов проверок с ловушками NULL: NOT IN по подзапросу с NULL, сироты через LEFT JOIN,
COUNT(*)/COUNT(col)/COUNT(DISTINCT), дубликаты с группой NULL, NOT BETWEEN и NULL, SUM при
NULL. Ключ считает независимая модель на Python, он сверяется с исполнением запроса в SQLite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.sql.data_quality_output"

CTX = [
    dict(label="интернет-магазин", parent="customers", child="orders", fk="customer_id",
         people="users", contact="email", pay="payments", amount="amount",
         emails=["anna@shop.ru", "ivan@shop.ru", "olga@shop.ru", "petr@shop.ru", "Anna@shop.ru"]),
    dict(label="банк", parent="clients", child="loans", fk="client_id",
         people="employees", contact="work_email", pay="transfers", amount="sum_rub",
         emails=["k.ivanov@bank.ru", "m.orlova@bank.ru", "a.lee@bank.ru", "d.kim@bank.ru",
                 "K.Ivanov@bank.ru"]),
    dict(label="онлайн-школа", parent="students", child="submissions", fk="student_id",
         people="teachers", contact="email", pay="invoices", amount="total",
         emails=["math@lms.ru", "rus@lms.ru", "art@lms.ru", "it@lms.ru", "Math@lms.ru"]),
    dict(label="такси", parent="drivers", child="trips", fk="driver_id",
         people="dispatchers", contact="email", pay="fares", amount="price",
         emails=["d1@taxi.ru", "d2@taxi.ru", "d3@taxi.ru", "d4@taxi.ru", "D1@taxi.ru"]),
]
KINDS = ["not_in_null", "left_join_orphans", "count_nulls", "dup_groups", "between_null", "sum_null"]


def _rel_data(rng, c):
    pids = sorted(rng.sample(range(1, 30), rng.randint(4, 6)))
    parents = [(p,) for p in pids]
    child, cid = [], rng.randint(100, 500)
    for _ in range(rng.randint(5, 8)):
        cid += rng.randint(1, 9)
        r = rng.random()
        fk = None if r < 0.18 else (rng.choice(range(30, 40)) if r < 0.32 else rng.choice(pids))
        child.append((cid, fk))
    return parents, child


def _people(rng, c, allow_empty=True):
    rows, pid = [], rng.randint(1, 20)
    for _ in range(rng.randint(6, 9)):
        pid += 1
        r = rng.random()
        val = None if r < 0.25 else ("" if r < 0.35 and allow_empty else rng.choice(c["emails"]))
        rows.append((pid, val))
    return rows


def _amounts(rng):
    rows, pid = [], rng.randint(1000, 5000)
    for _ in range(rng.randint(6, 9)):
        pid += rng.randint(1, 7)
        r = rng.random()
        val = None if r < 0.25 else (rng.choice([0, -100, 60000, 75000]) if r < 0.45
                                      else rng.randint(1, 499) * 100)
        rows.append((pid, val))
    return rows


def _fmt(rows):
    return "\n".join("|".join("NULL" if v is None else str(v) for v in r) for r in rows)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CTX)
    kind = rng.choice(KINDS)
    P, C, fk = c["parent"], c["child"], c["fk"]
    tables: list[tuple[str, list[str], list[tuple]]] = []
    for _ in range(300):
        if kind in ("not_in_null", "left_join_orphans"):
            parents, child = _rel_data(rng, c)
            tables = [(P, ["id"], parents), (C, ["id", fk], child)]
            fks = [r[1] for r in child]
            pset = {p[0] for p in parents}
            if kind == "not_in_null":
                q = f"SELECT COUNT(*) AS no_{C}\nFROM {P}\nWHERE id NOT IN (SELECT {fk} FROM {C});"
                res = 0 if None in fks else sum(1 for p in pset if p not in fks)
                ok = sum(1 for p in pset if p not in fks) > 0
                out = str(res)
            else:
                q = (f"SELECT COUNT(*) AS orphans\nFROM {C} AS ch\nLEFT JOIN {P} AS p ON p.id = ch.{fk}\n"
                     f"WHERE p.id IS NULL;")
                res = sum(1 for f in fks if f is None or f not in pset)
                ok = None in fks and any(f is not None and f not in pset for f in fks)
                out = str(res)
        elif kind in ("count_nulls", "dup_groups"):
            rows = _people(rng, c, allow_empty=kind == "count_nulls")
            col = c["contact"]
            tables = [(c["people"], ["id", col], rows)]
            vals = [r[1] for r in rows]
            if kind == "count_nulls":
                q = (f"SELECT COUNT(*) AS total, COUNT({col}) AS filled,\n"
                     f"       COUNT(DISTINCT {col}) AS uniq\nFROM {c['people']};")
                filled = [v for v in vals if v is not None]
                out = f"{len(vals)}|{len(filled)}|{len(set(filled))}"
                ok = None in vals and "" in vals and len(set(filled)) < len(filled)
            else:
                q = (f"SELECT {col}, COUNT(*) AS n\nFROM {c['people']}\nGROUP BY {col}\n"
                     f"HAVING COUNT(*) > 1\nORDER BY n DESC, {col};")
                cnt: dict = {}
                for v in vals:
                    cnt[v] = cnt.get(v, 0) + 1
                groups = [(k, n) for k, n in cnt.items() if n > 1]
                groups.sort(key=lambda kn: (-kn[1], kn[0] is not None, kn[0] or ""))
                out = _fmt(groups)
                ok = vals.count(None) >= 2 and len(groups) >= 2
        else:
            rows = _amounts(rng)
            col = c["amount"]
            tables = [(c["pay"], ["id", col], rows)]
            vals = [r[1] for r in rows]
            if kind == "between_null":
                lo, hi = 1, 50000
                q = f"SELECT COUNT(*) AS suspicious\nFROM {c['pay']}\nWHERE {col} NOT BETWEEN {lo} AND {hi};"
                res = sum(1 for v in vals if v is not None and not lo <= v <= hi)
                out = str(res)
                ok = None in vals and res > 0
            else:
                q = (f"SELECT COUNT(*) AS n, COUNT({col}) AS with_sum, SUM({col}) AS total\n"
                     f"FROM {c['pay']}\nWHERE {col} IS NULL OR {col} > 0;")
                sel = [v for v in vals if v is None or v > 0]
                nn = [v for v in sel if v is not None]
                out = f"{len(sel)}|{len(nn)}|{sum(nn) if nn else 'NULL'}"
                ok = None in vals and any(v is not None and v <= 0 for v in vals) and nn
        if ok:
            break
    else:
        raise RuntimeError("не удалось подобрать данные")
    setup = []
    for t, cols, rows in tables:
        types = ", ".join(f"{col} {'INTEGER PRIMARY KEY' if col == 'id' else ('TEXT' if col in (c['contact'],) else 'INTEGER')}"
                          for col in cols)
        setup.append(f"CREATE TABLE {t} ({types});")
        setup.append(sql_inserts(t, cols, rows))
    show = lambda rows: [tuple("''" if v == "" else v for v in r) for r in rows]
    data = "\n\n".join(f"Таблица `{t}`:\n{text_table(cols, show(rows))}" for t, cols, rows in tables)
    stem = (f"Проверка качества данных после миграции ({c['label']}). Пустая строка показана как "
            f"'', отсутствующее значение — как NULL.\n\n{data}\n\nЧто вернёт запрос в SQLite? Запишите "
            f"строки результата, значения столбцов через `|`, NULL — словом NULL.")
    why = {"not_in_null": "если подзапрос NOT IN содержит NULL, условие для любой строки — UNKNOWN, "
                          "и результат пуст (0); для поиска «без пары» нужен NOT EXISTS",
           "left_join_orphans": "LEFT JOIN … IS NULL находит и строки с несуществующим ключом, и "
                                "строки с NULL во внешнем ключе",
           "count_nulls": "COUNT(*) считает строки, COUNT(col) — не-NULL значения (пустая строка "
                          "считается), COUNT(DISTINCT) — различные не-NULL, регистр различается",
           "dup_groups": "GROUP BY объединяет все NULL в одну группу; сравнение строк "
                         "чувствительно к регистру; NULL при сортировке по возрастанию идёт первым",
           "between_null": "для NULL выражение NOT BETWEEN даёт UNKNOWN — такие строки не попадают "
                           "в результат",
           "sum_null": "COUNT(col) и SUM пропускают NULL; строки с NULL попали в выборку через IS NULL"}
    ak = AnswerKey(kind="output", value=out, explanation=why[kind] + ".")
    checks = [Check(name="stdout", runner="sqlite", program=q, files={"setup.sql": "\n".join(setup) + "\n"},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=q, answer_key=ak, context=c["label"],
                         verification="execution", checks=checks, params={"kind": kind})
