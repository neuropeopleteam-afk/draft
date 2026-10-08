"""common.sql.not_in_null — find_bug: NOT IN по подзапросу, в котором встречается NULL.

`x NOT IN (…, NULL)` никогда не бывает истинным (UNKNOWN), поэтому запрос возвращает пустой
результат. Исправление в одной строке — NOT EXISTS или фильтр IS NOT NULL в подзапросе.
Проверка: исполнение показанного запроса в SQLite (Python sqlite3) на данных с NULL.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.not_in_null"

# (родитель, алиас, имя, ребёнок, алиас, внешний ключ, причина NULL, что ищем, фильтр, контекст)
CONTEXTS = [
    ("customers", "c", "name", "orders", "o", "customer_id", "гостевые заказы без покупателя",
     "покупателей без единого заказа", ("c.city", ["Казань", "Пермь", "Омск"]), "интернет-магазин"),
    ("employees", "e", "full_name", "employees", "m", "manager_id",
     "у генерального директора нет руководителя", "сотрудников, у которых нет подчинённых",
     ("e.department", ["ИТ", "Продажи", "Финансы"]), "оргструктура"),
    ("products", "p", "title", "order_items", "i", "product_id",
     "позиции «услуга» и удалённые товары без product_id", "товары, которые ни разу не продавались",
     ("p.category", ["книги", "игры", "посуда"]), "склад"),
    ("users", "u", "login", "sessions", "s", "user_id", "анонимные сессии без пользователя",
     "пользователей, которые ни разу не входили", ("u.plan", ["free", "pro", "team"]), "SaaS-сервис"),
]
NAMES = {"name": ["Анна", "Борис", "Вера", "Глеб", "Дина", "Егор", "Жанна", "Илья", "Кира", "Лев"],
         "full_name": ["Анна Орлова", "Борис Ким", "Вера Лис", "Глеб Сом", "Дина Рой", "Егор Шах",
                       "Жанна Бок", "Илья Гусь"],
         "title": ["Арт. 104", "Арт. 217", "Арт. 305", "Арт. 412", "Арт. 528", "Арт. 633", "Арт. 741", "Арт. 856"],
         "login": ["anna", "boris", "vera", "gleb", "dina", "egor", "zhanna", "ilya"]}


def _query(P, p, nm, C, c, fk, flt, val, kind, fix_kind, layout):
    sub = f"SELECT {c}.{fk} FROM {C} {c}"
    if kind == "bad":
        cond = f"{p}.id NOT IN ({sub})"
    elif fix_kind == "exists":
        cond = f"NOT EXISTS (SELECT 1 FROM {C} {c} WHERE {c}.{fk} = {p}.id)"
    else:
        cond = f"{p}.id NOT IN ({sub} WHERE {c}.{fk} IS NOT NULL)"
    other = f"{flt} = '{val}'"
    lines = [f"SELECT {p}.id, {p}.{nm}", f"FROM {P} {p}"]
    if layout == "cond_first":
        lines += [f"WHERE {cond}", f"  AND {other}"]
    else:
        lines += [f"WHERE {other}", f"  AND {cond}"]
    if layout == "with_active":
        lines.append(f"  AND {p}.is_active = 1")
    lines.append(f"ORDER BY {p}.id;")
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    P, p, nm, C, c, fk, why_null, what, (flt, vals), ctx = rng.choice(CONTEXTS)
    val = rng.choice(vals)
    layout = rng.choice(["cond_first", "cond_second", "with_active"])
    fix_kind = rng.choice(["exists", "not_null"])
    fcol = flt.split(".")[1]
    n = rng.randint(5, 6)
    names = rng.sample(NAMES[nm], n)
    while True:
        parents = [(i + 1, names[i], rng.choice(vals), rng.choice([1, 1, 1, 0])) for i in range(n)]
        refs = rng.sample(range(1, n + 1), rng.randint(2, 3))
        kids = [r for r in refs] + [None] * rng.randint(1, 2)
        rng.shuffle(kids)
        expected = [(pid, nmv) for pid, nmv, fv, act in parents
                    if fv == val and pid not in refs and (layout != "with_active" or act == 1)]
        if expected:
            break
    self_ref = P == C
    if self_ref:
        setup = (f"CREATE TABLE {P} (id INTEGER PRIMARY KEY, {nm} TEXT NOT NULL, {fcol} TEXT NOT NULL, "
                 f"is_active INTEGER NOT NULL, {fk} INTEGER NULL);\n")
        # руководители: ссылки refs; у остальных — руководитель из refs или NULL
        rows = []
        for idx, (pid, nmv, fv, act) in enumerate(parents):
            mgr = None if idx == 0 else rng.choice([r for r in refs if r != pid] or [None])
            rows.append((pid, nmv, fv, act, mgr))
        # пересчитать «у кого нет подчинённых» по фактическим ссылкам
        has_sub = {r[4] for r in rows if r[4] is not None}
        if not any(r[4] is None for r in rows):
            rows[0] = rows[0][:4] + (None,)
        expected = [(pid, nmv) for pid, nmv, fv, act, _ in rows
                    if fv == val and pid not in has_sub and (layout != "with_active" or act == 1)]
        if not expected:
            pid = next(r[0] for r in rows if r[0] not in has_sub)
            rows = [(r[0], r[1], val if r[0] == pid else r[2], 1 if r[0] == pid else r[3], r[4])
                    for r in rows]
            expected = [(r[0], r[1]) for r in rows if r[2] == val and r[0] not in has_sub
                        and (layout != "with_active" or r[3] == 1)]
        setup += sql_inserts(P, ["id", nm, fcol, "is_active", fk], rows) + "\n"
        shown = f"{P}\n" + text_table(["id", nm, fcol, "is_active", fk], rows)
    else:
        setup = (f"CREATE TABLE {P} (id INTEGER PRIMARY KEY, {nm} TEXT NOT NULL, {fcol} TEXT NOT NULL, "
                 f"is_active INTEGER NOT NULL);\n"
                 f"CREATE TABLE {C} (id INTEGER PRIMARY KEY, {fk} INTEGER NULL);\n"
                 + sql_inserts(P, ["id", nm, fcol, "is_active"], parents) + "\n"
                 + sql_inserts(C, ["id", fk], [(100 + i, k) for i, k in enumerate(kids)]) + "\n")
        shown = (f"{P}\n" + text_table(["id", nm, fcol, "is_active"], parents) + f"\n\n{C}\n"
                 + text_table(["id", fk], [(100 + i, k) for i, k in enumerate(kids)]))
    buggy = _query(P, p, nm, C, c, fk, flt, val, "bad", fix_kind, layout)
    fixed = _query(P, p, nm, C, c, fk, flt, val, "good", fix_kind, layout)
    key_line = next(i for i, (a, b) in enumerate(zip(buggy.splitlines(), fixed.splitlines()), 1)
                    if a != b)
    assert changed_lines(buggy, fixed) == {key_line}
    exp_lit = repr([tuple(e) for e in expected])

    def prog(sql):
        return ("import sqlite3\n_con = sqlite3.connect(':memory:')\n_con.executescript("
                + repr(setup) + ")\nQUERY = \"\"\"" + sql + "\"\"\"\n"
                "_rows = _con.execute(QUERY).fetchall()\n"
                f"print('RESULT: PASS' if _rows == {exp_lit} else 'RESULT: FAIL ' + repr(_rows))\n")
    checks = [Check(name="buggy_fails", runner="python", program=prog(buggy), expect="fail"),
              Check(name="fixed_passes", runner="python", program=prog(fixed), expect="pass",
                    embeds_display_code=False)]
    extra = " и только активные (`is_active = 1`)" if layout == "with_active" else ""
    stem = (f"Запрос ({ctx}) должен вернуть {what}: строки с `{flt} = '{val}'`{extra}. В таблице "
            f"`{C}` столбец `{fk}` допускает NULL ({why_null}). Данные:\n\n{shown}\n\n"
            f"Подходящие строки есть, но запрос возвращает пустой результат. Укажите номер "
            f"строки запроса, которую нужно исправить.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: если подзапрос возвращает хотя бы один NULL, "
                               "`x NOT IN (...)` даёт UNKNOWN для всех x, не найденных среди "
                               "значений, и строка отбрасывается. Исправление: NOT EXISTS с "
                               "коррелированным подзапросом или `WHERE ... IS NOT NULL` в подзапросе.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="not_in_with_null",
                         language="sql",
                         params={"fixed_code": fixed, "layout": layout, "fix": fix_kind})
