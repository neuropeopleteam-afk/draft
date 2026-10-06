"""common.db.index_plan_mcq — mcq_concept: как составной индекс используется запросом.

Правило «левого префикса»: индекс (a, b) помогает условию на a и на (a, b); равенство по a
плюс диапазон по b — оба столбца; диапазон по a «обрывает» использование b; функция над
столбцом и OR по разным столбцам ведут к полному просмотру. Ключ проверяется исполнением:
показанные DDL и запрос выполняются в SQLite, класс плана берётся из EXPLAIN QUERY PLAN.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.db.index_plan_mcq"

# (таблица, a, b, c, значения c, контекст)
CONTEXTS = [("orders", "customer_id", "created_at", "status", ["paid", "new", "cancelled"], "интернет-магазин"),
            ("events", "user_id", "occurred_at", "kind", ["click", "view", "login"], "продуктовая аналитика"),
            ("tickets", "project_id", "opened_at", "state", ["open", "closed", "hold"], "служба поддержки"),
            ("payments", "merchant_id", "paid_at", "method", ["card", "sbp", "cash"], "эквайринг")]

LABELS = {"scan": "Полный просмотр всей таблицы, индекс не используется",
          "both": "Поиск по индексу по обоим столбцам, затем чтение строк",
          "first": "Поиск по индексу только по первому столбцу и чтение строк",
          "covering": "Поиск только по индексу, сами строки таблицы не читаются"}

CASES = [
    ("both_eq_range", "both", "SELECT * FROM {t}\nWHERE {a} = {n} AND {b} >= '{d}';",
     "равенство по первому столбцу и диапазон по второму — используется префикс (a, b)"),
    ("both_reordered", "both", "SELECT * FROM {t}\nWHERE {b} >= '{d}' AND {a} = {n};",
     "порядок условий в WHERE не важен — важен порядок столбцов в индексе"),
    ("both_in", "both", "SELECT * FROM {t}\nWHERE {a} IN ({n}, {n2}, {n3}) AND {b} >= '{d}';",
     "IN по первому столбцу — несколько точек входа в индекс, диапазон по второму сохраняется"),
    ("scan_second", "scan", "SELECT * FROM {t}\nWHERE {b} >= '{d}';",
     "условие только на второй столбец — у индекса (a, b) нет нужного левого префикса"),
    ("scan_func", "scan", "SELECT * FROM {t}\nWHERE substr({b}, 1, 7) = '{m}';",
     "функция над столбцом, и это не первый столбец индекса — просмотр всей таблицы"),
    ("scan_or", "scan", "SELECT * FROM {t}\nWHERE {a} = {n} OR {b} >= '{d}';",
     "OR по разным столбцам: вторую ветку индекс (a, b) не покрывает — полный просмотр"),
    ("first_other", "first", "SELECT * FROM {t}\nWHERE {a} = {n} AND {c} = '{cv}';",
     "столбца {c} нет в индексе: поиск по {a}, затем проверка {c} в строках таблицы"),
    ("first_range", "first", "SELECT * FROM {t}\nWHERE {a} > {n} AND {b} = '{d}';",
     "диапазон по первому столбцу обрывает использование второго столбца индекса"),
    ("first_func", "first", "SELECT * FROM {t}\nWHERE {a} = {n} AND substr({b}, 1, 7) = '{m}';",
     "функция над {b} не позволяет искать по второму столбцу, используется только {a}"),
    ("covering", "covering", "SELECT {a}, {b} FROM {t}\nWHERE {a} = {n};",
     "все нужные столбцы есть в индексе — строки таблицы не читаются"),
]

PROGRAM = '''import sqlite3
CODE = """{code}"""
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE {t} (id INTEGER PRIMARY KEY, {a} INTEGER NOT NULL, {b} TEXT NOT NULL, "
            "{c} TEXT NOT NULL, amount INTEGER NOT NULL)")
ddl, query = CODE.split("\\n\\n")
con.executescript(ddl)
plan = " ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + query))
if "COVERING INDEX" in plan and "SEARCH" in plan:
    print("covering")
elif plan.startswith("SEARCH") and " AND " in plan:
    print("both")
elif plan.startswith("SEARCH"):
    print("first")
else:
    print("scan")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    t, a, b, c, cvals, ctx = rng.choice(CONTEXTS)
    # Калибровка 05.10: класс «both» (индекс по обоим столбцам) решался в 0,66 против 0,19–0,31;
    # как ключ исключён, как дистрактор остаётся.
    name, cls, tpl, why = rng.choice([c for c in CASES if c[1] != "both"])
    month = rng.randint(1, 9)
    vals = dict(t=t, a=a, b=b, c=c, n=rng.randint(10, 999), n2=rng.randint(1000, 1999),
                n3=rng.randint(2000, 2999), d=f"2026-{month:02d}-{rng.randint(1, 28):02d}",
                m=f"2026-{month:02d}", cv=rng.choice(cvals))
    idx = f"idx_{t}_{a.split('_')[0]}_{b.split('_')[0]}"
    code = f"CREATE INDEX {idx} ON {t} ({a}, {b});\n\n" + tpl.format(**vals)
    program = PROGRAM.replace("{code}", code).format(t=t, a=a, b=b, c=c)
    opts, key = make_options(rng, (LABELS[cls], None),
                             [(LABELS[k], None) for k in LABELS if k != cls])
    stem = (f"Таблица `{t}` ({ctx}): `id INTEGER PRIMARY KEY, {a} INTEGER, {b} TEXT, {c} TEXT, "
            f"amount INTEGER`; других индексов, кроме показанного, нет, статистика (ANALYZE) не "
            f"собрана. Как SQLite выполнит запрос?")
    ak = AnswerKey(kind="option", value=key, explanation=why.format(a=a, b=b, c=c) + ".")
    checks = [Check(name="plan", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=cls)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks, language="sql",
                         params={"case": name, "class": cls})
