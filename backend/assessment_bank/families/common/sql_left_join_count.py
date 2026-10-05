"""common.sql.left_join_count — predict_output: LEFT JOIN + агрегат, ловушки NULL и COUNT(*)."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.left_join_count"

# (родитель, колонка имени, ребёнок, внешний ключ, числовая колонка, статусы, целевой статус, контекст)
CONTEXTS = [
    ("customers", "name", "orders", "customer_id", "amount", ["paid", "cancelled", "new"], "paid", "магазин"),
    ("authors", "name", "posts", "author_id", "views", ["published", "draft"], "published", "блог"),
    ("courses", "title", "enrollments", "course_id", "score", ["active", "dropped"], "active", "обучение"),
    ("warehouses", "city", "shipments", "warehouse_id", "weight", ["delivered", "lost", "in_transit"], "delivered", "логистика"),
    ("projects", "name", "tasks", "project_id", "hours", ["done", "open"], "done", "трекер задач"),
]
NAMES = {
    "name": ["Анна", "Борис", "Вера", "Глеб", "Дина", "Егор", "Жанна", "Илья", "Кира"],
    "title": ["SQL", "Python", "Go", "DevOps", "React", "Kotlin", "Linux"],
    "city": ["Казань", "Пермь", "Омск", "Тула", "Сочи", "Уфа", "Тверь"],
}
TEMPLATES = ["count_col_on", "count_star_on", "count_where", "sum_on", "coalesce_sum_on"]


def _query(t, P, nm, C, fk, num, st):
    p, c = P[0], C[0]
    if t == "count_col_on":
        sel, join_extra, where = f"COUNT({c}.id) AS cnt", f" AND {c}.status = '{st}'", ""
    elif t == "count_star_on":
        sel, join_extra, where = "COUNT(*) AS cnt", f" AND {c}.status = '{st}'", ""
    elif t == "count_where":
        sel, join_extra, where = f"COUNT({c}.id) AS cnt", "", f"\nWHERE {c}.status = '{st}'"
    elif t == "sum_on":
        sel, join_extra, where = f"SUM({c}.{num}) AS total", f" AND {c}.status = '{st}'", ""
    else:
        sel, join_extra, where = (f"COALESCE(SUM({c}.{num}), 0) AS total",
                                  f" AND {c}.status = '{st}'", "")
    return (f"SELECT {p}.{nm}, {sel}\nFROM {P} {p}\nLEFT JOIN {C} {c} ON {c}.{fk} = {p}.id"
            f"{join_extra}{where}\nGROUP BY {p}.id, {p}.{nm}\nORDER BY {p}.id;")


def _ref(t, parents, children, st):
    out = []
    for pid, name in parents:
        kids = [k for k in children if k[1] == pid]
        match = [k for k in kids if k[3] == st]
        if t == "count_col_on":
            out.append(f"{name}|{len(match)}")
        elif t == "count_star_on":
            out.append(f"{name}|{max(len(match), 1)}")
        elif t == "count_where":
            if match:
                out.append(f"{name}|{len(match)}")
        elif t == "sum_on":
            out.append(f"{name}|{sum(k[2] for k in match) if match else 'NULL'}")
        else:
            out.append(f"{name}|{sum(k[2] for k in match)}")
    return "\n".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    P, nm, C, fk, num, statuses, st, ctx = rng.choice(CONTEXTS)
    t = rng.choice(TEMPLATES)
    n_par = rng.randint(3, 5)
    names = rng.sample(NAMES[nm], n_par)
    parents = [(i + 1, names[i]) for i in range(n_par)]
    while True:
        children = []
        cid = 100 + rng.randrange(0, 50)
        for _ in range(rng.randint(4, 7)):
            cid += rng.randint(1, 3)
            children.append((cid, rng.randint(1, n_par), rng.randint(1, 20) * 10, rng.choice(statuses)))
        pids_with = {k[1] for k in children}
        pids_match = {k[1] for k in children if k[3] == st}
        no_kids = [p for p, _ in parents if p not in pids_with]
        only_other = [p for p in pids_with if p not in pids_match]
        if no_kids and (only_other or rng.random() < 0.3) and pids_match:
            break
    query = _query(t, P, nm, C, fk, num, st)
    setup = (f"CREATE TABLE {P} (id INTEGER PRIMARY KEY, {nm} TEXT NOT NULL);\n"
             f"CREATE TABLE {C} (id INTEGER PRIMARY KEY, {fk} INTEGER NOT NULL REFERENCES {P}(id), "
             f"{num} INTEGER NOT NULL, status TEXT NOT NULL);\n"
             + sql_inserts(P, ["id", nm], parents) + "\n"
             + sql_inserts(C, ["id", fk, num, "status"], children) + "\n")
    out = _ref(t, parents, children, st)
    stem = (f"Даны таблицы `{P}` и `{C}`:\n\n{P}\n{text_table(['id', nm], parents)}\n\n{C}\n"
            f"{text_table(['id', fk, num, 'status'], children)}\n\n"
            "Что вернёт запрос? Запишите строки результата по порядку, по одной в строке, "
            "значения через «|» (например: `Анна|2`); отсутствующее значение записывайте как NULL.")
    trap = {"count_col_on": "COUNT(столбец) не считает NULL — у строк без пары будет 0",
            "count_star_on": "COUNT(*) считает и строку, дополненную NULL, — у строк без пары будет 1",
            "count_where": "условие в WHERE отбрасывает строки, дополненные NULL, — LEFT JOIN "
                           "фактически становится INNER JOIN",
            "sum_on": "SUM по одним NULL даёт NULL, а не 0",
            "coalesce_sum_on": "COALESCE превращает NULL от SUM в 0"}[t]
    assert out, "в каждом варианте есть хотя бы одна строка результата"
    ak = AnswerKey(kind="output", value=out, explanation=f"Ключевая деталь: {trap}.")
    checks = [Check(name="stdout", runner="sqlite", program=query, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=query, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"template": t})
