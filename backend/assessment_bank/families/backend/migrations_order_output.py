"""backend.migrations.order_output — predict_output: порядок применения миграций схемы.

Самописный раннер миграций сортирует имена файлов. Без ведущих нулей сортировка строк
ставит «10_…» раньше «2_…», и миграция может выполниться раньше той, от которой зависит
(ALTER/INDEX до CREATE TABLE). В части вариантов раннер сортирует по числовому префиксу —
тогда все миграции применяются по порядку. Ключ считает независимая модель (множества
таблиц и столбцов), вывод сверяется с исполнением показанного кода (sqlite3).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.migrations.order_output"

TABLES = [("users", ["email", "phone", "city"]), ("orders", ["total", "status", "paid_at"]),
          ("products", ["price", "sku", "brand"]), ("payments", ["amount", "provider"]),
          ("tickets", ["priority", "assignee"]), ("invoices", ["due_date", "client_id"])]
CONTEXTS = ["интернет-магазин", "CRM", "сервис бронирования", "биллинг", "служба поддержки",
            "маркетплейс"]


def _plan(rng, table: str, cols: list[str]) -> list[tuple[str, str, str]]:
    c1, c2 = rng.sample(cols, 2)
    steps = [("create", table, ""), ("add", table, c1)]
    tail = rng.choice([[("index", table, c1)], [("add", table, c2)],
                       [("add", table, c2), ("index", table, c2)]])
    return steps + tail


def _sql(action: str, table: str, col: str) -> str:
    if action == "create":
        return f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"
    if action == "add":
        return f"ALTER TABLE {table} ADD COLUMN {col} TEXT"
    return f"CREATE INDEX ix_{table}_{col} ON {table} ({col})"


def _model(order: list[str], meta: dict[str, tuple[str, str, str]]) -> str:
    """Независимая модель: какие миграции применятся при заданном порядке."""
    tables: dict[str, set[str]] = {}
    out = []
    for name in order:
        action, table, col = meta[name]
        ok = (action == "create" and table not in tables) or (
            action == "add" and table in tables and col not in tables[table]) or (
            action == "index" and table in tables and col in tables[table])
        if not ok:
            out.append(f"ошибка: {name}")
            break
        if action == "create":
            tables[table] = {"id"}
        elif action == "add":
            tables[table].add(col)
        out.append(f"применена: {name}")
    return "\n".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    (t1, cols1), (t2, cols2) = rng.sample(TABLES, 2)
    p1, p2 = _plan(rng, t1, cols1), _plan(rng, t2, cols2)
    if len(p1) + len(p2) > 6:
        p2 = p2[:2]
    # случайное слияние двух планов с сохранением порядка внутри таблицы
    merged, i, j = [], 0, 0
    while i < len(p1) or j < len(p2):
        if j >= len(p2) or (i < len(p1) and rng.random() < 0.5):
            merged.append(p1[i]); i += 1
        else:
            merged.append(p2[j]); j += 1
    n = len(merged)
    while True:
        nums = [1] + sorted(rng.sample(range(2, 16), n - 1))  # нумерация проекта начинается с 1
        if sum(x >= 10 for x in nums) >= 2 and sum(x < 10 for x in nums) >= 2:
            break
    meta = {}
    for num, (action, table, col) in zip(nums, merged):
        name = f"{num}-{action}-{table}" + (f"-{col.replace('_', '-')}" if col else "")
        meta[name] = (action, table, col)
    numeric = rng.random() < 0.3
    names = list(meta)
    shown = names[:]
    rng.shuffle(shown)
    order = sorted(names, key=lambda s: int(s.split("-")[0])) if numeric else sorted(names)
    out = _model(order, meta)
    sort_expr = ("sorted(MIGRATIONS, key=lambda name: int(name.split(\"-\")[0]))" if numeric
                 else "sorted(MIGRATIONS)")
    lines = ["import sqlite3", "", "MIGRATIONS = {"]
    lines += [f'    "{nm}": "{_sql(*meta[nm])}",' for nm in shown]
    lines += ["}", "", 'con = sqlite3.connect(":memory:")', f"for name in {sort_expr}:",
              "    try:", "        con.execute(MIGRATIONS[name])",
              "    except sqlite3.OperationalError:", '        print("ошибка:", name)',
              "        break", '    print("применена:", name)']
    code = "\n".join(lines)
    ctx = rng.choice(CONTEXTS)
    stem = (f"Сервис ({ctx}) при старте применяет миграции схемы самописным раннером; в тестовом "
            f"окружении база — SQLite в памяти. Что напечатает программа? Запишите вывод точно, "
            f"по строкам.")
    failed = out.splitlines()[-1].startswith("ошибка")
    why = ("Раннер сортирует имена как строки: «10-…» идёт раньше «2-…», поэтому миграция "
           "выполняется раньше той, от которой зависит, и раннер останавливается на первой ошибке."
           if failed and not numeric else
           "Строковая сортировка меняет порядок, но в этом варианте зависимости не нарушаются."
           if not numeric else
           "Раннер сортирует по числовому префиксу, порядок совпадает с порядком создания миграций.")
    ak = AnswerKey(kind="output", value=out,
                   explanation=why + " Правильная практика — ведущие нули (0001-…) или номер "
                                     "ревизии с явной ссылкой на предыдущую (как в Alembic).")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"numeric_sort": numeric, "failed": failed, "order": order})
