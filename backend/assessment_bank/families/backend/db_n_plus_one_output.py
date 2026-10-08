"""backend.db.n_plus_one_output — predict_output: сколько SQL-запросов выполнит код (N+1).

Список строк загружается одним запросом, связанная сущность — отдельными запросами:
без кэша (1 + N), с кэшем по id (1 + число различных id), с кэшем, который по ошибке
создаётся на каждый элемент (снова 1 + N), с предзагрузкой через IN (2) или JOIN (1).
Запросы считает `set_trace_callback`. Ключ — независимая модель, сверка исполнением.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.db.n_plus_one_output"

# (родитель, дочерняя, внешний ключ, числовое поле, имена родителей, контекст)
ENTITIES = [("authors", "books", "author_id", "price", ["Пушкин", "Гоголь", "Чехов", "Бунин"],
             "книжный магазин"),
            ("customers", "orders", "customer_id", "total", ["Иванов", "Петрова", "Сидоров", "Козлова"],
             "интернет-магазин"),
            ("teams", "tasks", "team_id", "points", ["web", "api", "data", "infra"], "трекер задач"),
            ("shops", "products", "shop_id", "price", ["Север", "Юг", "Центр", "Запад"], "маркетплейс"),
            ("clinics", "visits", "clinic_id", "cost", ["Здоровье", "Медлайн", "Вита", "Пульс"],
             "запись к врачу")]
STRATEGIES = ["naive", "cache", "cache_per_item", "prefetch_in", "join"]


def _code(ent, rows_parent, rows_child, thr, strategy, fn):
    parent, child, fk, val, _names, _ctx = ent
    p_ins = ", ".join(f"({i}, '{n}')" for i, n in rows_parent)
    c_ins = ", ".join(f"({i}, {p}, {v})" for i, p, v in rows_child)
    lines = ["import sqlite3", "", 'con = sqlite3.connect(":memory:")', 'con.executescript("""',
             f"CREATE TABLE {parent} (id INTEGER PRIMARY KEY, name TEXT);",
             f"CREATE TABLE {child} (id INTEGER PRIMARY KEY, {fk} INTEGER, {val} INTEGER);",
             f"INSERT INTO {parent} VALUES {p_ins};", f"INSERT INTO {child} VALUES {c_ins};",
             '""")', "queries = []", "con.set_trace_callback(queries.append)", "", ""]
    select_child = (f'rows = con.execute("SELECT id, {fk} FROM {child} WHERE {val} >= ?", '
                    f'({thr},)).fetchall()')
    one = f'con.execute("SELECT name FROM {parent} WHERE id = ?", ({fk},)).fetchone()[0]'
    if strategy == "naive":
        lines += [f"def {fn}({fk}):", f"    return {one}", "", "",
                  select_child, f"names = [{fn}({fk}) for _, {fk} in rows]"]
    elif strategy in ("cache", "cache_per_item"):
        lines += [f"def {fn}({fk}, cache):", f"    if {fk} not in cache:",
                  f"        cache[{fk}] = {one}", f"    return cache[{fk}]", "", "", select_child]
        if strategy == "cache":
            lines += ["cache = {}", f"names = [{fn}({fk}, cache) for _, {fk} in rows]"]
        else:
            lines += [f"names = [{fn}({fk}, {{}}) for _, {fk} in rows]"]
    elif strategy == "prefetch_in":
        lines += [select_child, f"ids = sorted({{{fk} for _, {fk} in rows}})",
                  'marks = ", ".join("?" * len(ids))',
                  f'found = dict(con.execute(f"SELECT id, name FROM {parent} WHERE id IN ({{marks}})", ids))',
                  f"names = [found[{fk}] for _, {fk} in rows]"]
    else:  # join
        lines += [f'rows = con.execute("SELECT c.id, p.name FROM {child} c JOIN {parent} p "',
                  f'                   "ON p.id = c.{fk} WHERE c.{val} >= ?", ({thr},)).fetchall()',
                  "names = [name for _, name in rows]"]
    lines.append("print(len(rows), len(queries))")
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ent = rng.choice(ENTITIES)
    parent, child, fk, val, names, ctx = ent
    strategy = rng.choice(STRATEGIES)
    n_par = rng.randint(3, 4)
    rows_parent = [(i, names[i - 1]) for i in range(1, n_par + 1)]
    while True:
        n_child = rng.randint(6, 9)
        rows_child = [(i, rng.randint(1, n_par), rng.randint(1, 9) * 100) for i in range(1, n_child + 1)]
        thr = rng.choice([200, 300, 400, 500])
        sel = [r for r in rows_child if r[2] >= thr]
        distinct = len({r[1] for r in sel})
        if 3 <= len(sel) and distinct < len(sel):  # кэш должен давать выигрыш
            break
    fn = rng.choice(["load_name", "get_name", "fetch_name"])
    code = _code(ent, rows_parent, rows_child, thr, strategy, fn)
    n = len(sel)
    q = {"naive": 1 + n, "cache": 1 + distinct, "cache_per_item": 1 + n, "prefetch_in": 2,
         "join": 1}[strategy]
    out = f"{n} {q}"
    stem = (f"Код ({ctx}) загружает строки `{child}` и имена связанных `{parent}`. "
            f"`set_trace_callback` вызывается для каждого выполненного SQL-запроса. Что напечатает "
            f"программа? Запишите вывод точно.")
    why = {"naive": f"1 запрос списка + по одному запросу на каждую из {n} строк (N+1)",
           "cache": f"1 запрос списка + по одному на каждый из {distinct} различных id: кэш общий",
           "cache_per_item": f"кэш создаётся заново (`{{}}`) для каждой строки и не помогает: 1 + {n}",
           "prefetch_in": "1 запрос списка + 1 запрос с IN по всем id",
           "join": "один запрос с JOIN"}[strategy]
    ak = AnswerKey(kind="output", value=out, explanation=f"Отобрано строк: {n}; запросов: {why}.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"strategy": strategy, "n": n, "distinct": distinct, "queries": q})
