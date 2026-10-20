"""common.pg.pg_not_in_null_fix — choose_fix (Senior/Lead, PostgreSQL): NOT IN с NULL в подзапросе.

«Клиенты без заказов» через `NOT IN (SELECT customer_id FROM orders)`; в orders есть гостевые заказы с customer_id
NULL — по трёхзначной логике SQL условие для каждого клиента становится NULL и запрос возвращает пустой результат
(одинаково в PostgreSQL и SQLite). Верно: NOT EXISTS (или NOT IN с фильтром IS NOT NULL — здесь показан NOT EXISTS).
Неверные (схема 2×2: NOT EXISTS / NOT IN с DISTINCT × без фильтра / только
завершённые): NOT EXISTS только по завершённым, NOT IN с DISTINCT (NULL остаётся), NOT IN с DISTINCT по завершённым. Проверка — исполнением в SQLite.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import codefix_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.pg.pg_not_in_null_fix"
SCEN = [("customers", "orders", "customer_id", "клиенты без заказов", "заказов"),
        ("students", "submissions", "student_id", "студенты без сданных работ", "работ"),
        ("drivers", "trips", "driver_id", "водители без поездок", "поездок"),
        ("authors", "posts", "author_id", "авторы без публикаций", "публикаций"),
        ("sellers", "listings", "seller_id", "продавцы без объявлений", "объявлений"),
        ("couriers", "deliveries", "courier_id", "курьеры без доставок", "доставок"),
        ("clinics", "appointments", "clinic_id", "клиники без записей", "записей"),
        ("partners", "payouts", "partner_id", "партнёры без выплат", "выплат")]
ORD = ["ORDER BY p.id", "ORDER BY 1", "ORDER BY p.id ASC", "ORDER BY id", "ORDER BY p.id ASC NULLS LAST",
       "ORDER BY p.id NULLS LAST"]
SEL = ["1", "NULL", "o.id", "*", "1 AS hit"]   # косметика длины
NAMES = ["name", "title", "login", "email"]
DONE = ["done", "completed", "closed", "finished"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(50):              # данные подбираются, пока каждая неверная замена не отличается от эталона
        try:
            return _gen(seed, rng)
        except RuntimeError:
            continue
    raise RuntimeError("не удалось подобрать данные")


def _gen(seed, rng):
    p, c, fk, task, what = SCEN[seed % len(SCEN)]
    nm, done = rng.choice(NAMES), rng.choice(DONE)
    n = rng.randint(6, 9)
    ids = list(range(1, n + 1))
    active = sorted(rng.sample(ids, rng.randint(2, n - 3)))
    rows, oid = [], 0
    for i in active:
        for _ in range(rng.randint(1, 3)):
            oid += 1
            rows.append((oid, i, rng.choice([done, done, "cancelled"])))
    only_cancelled = rng.choice(active)                 # есть и такие, у кого только отменённые записи
    rows = [(r[0], r[1], "cancelled" if r[1] == only_cancelled else r[2]) for r in rows]
    for _ in range(rng.randint(1, 3)):
        oid += 1
        rows.append((oid, None, done))
    rng.shuffle(rows)
    setup = (f"CREATE TABLE {p} (id INTEGER PRIMARY KEY, {nm} TEXT NOT NULL);\n"
             f"CREATE TABLE {c} (id INTEGER PRIMARY KEY, {fk} INTEGER, status TEXT NOT NULL);\n"
             + "\n".join(f"INSERT INTO {p} VALUES ({i}, 'u{i}');" for i in ids) + "\n"
             + "\n".join(f"INSERT INTO {c} VALUES ({r[0]}, {'NULL' if r[1] is None else r[1]}, '{r[2]}');" for r in rows))
    buggy = f"SELECT p.id, p.{nm}\nFROM {p} p\nWHERE p.id NOT IN (SELECT {fk} FROM {c})\nORDER BY p.id;"
    st = rng.choice([f"o.status IN ('{done}') ", f"o.status = '{done}' ", "o.status <> 'cancelled' "])
    allst = rng.choice(["o.status IS NOT NULL ", f"o.status IN ('{done}', 'cancelled') ", "o.status <> '' "])

    def ex(flt):
        return (f"SELECT p.id, p.{nm}\nFROM {p} p\nWHERE NOT EXISTS (\n  SELECT {rng.choice(SEL)} FROM {c} o WHERE o.{fk} = p.id AND "
                f"{flt}\n)\n{rng.choice(ORD)};").replace(" \n", "\n")

    def nin(flt):
        return (f"SELECT p.id, p.{nm}\nFROM {p} p\nWHERE p.id NOT IN (\n  SELECT DISTINCT o.{fk} FROM {c} o WHERE "
                f"{flt}\n)\n{rng.choice(ORD)};").replace(" \n", "\n")
    good = ex(allst)
    # 2×2: NOT EXISTS / NOT IN (DISTINCT) × все статусы (условие, истинное для любого статуса) / только завершённые — все варианты одинаково «центральны»
    wrongs = [("exists_done_only", ex(st)), ("distinct", nin(allst)), ("distinct_done_only", nin(st))]
    stem = (rng.choice([f"Отчёт «{task}» в PostgreSQL.", f"Аналитик строит выборку «{task}» в PostgreSQL.",
                        f"Ночная выгрузка «{task}» (PostgreSQL) пришла пустой."])
            + f" В `{c}` есть " + rng.choice(["гостевые записи", "записи из старой системы", "анонимные записи"])
            + f" с `{fk}` = NULL; статус записи — `{done}` или `cancelled`, в отчёт должны попасть только те, у кого "
            f"нет ни одной записи {what} в любом статусе. Показанный запрос возвращает пустой результат, хотя такие "
            f"строки в `{p}` точно есть. Какая замена запроса верна?")
    expl = (f"`x NOT IN (…, NULL)` по трёхзначной логике даёт NULL (не TRUE) для каждого x, которого нет в списке, — "
            f"строки отбрасываются; DISTINCT оставляет NULL в списке. NOT EXISTS сравнивает построчно, и NULL не мешает. "
            f"Фильтр по статусу меняет задачу: в отчёт попадут и те, у кого есть только отменённые записи {what}.")
    return codefix_variant(FAMILY_ID, seed, rng, ctx=task, stem=stem, runner="sqlite", buggy=buggy, good=good,
                           wrongs=wrongs, label="Заменить запрос на:", harness=None, setup=setup, explanation=expl,
                           defect_type="null_semantics", params={"n": n, "n_rows": len(rows)}, language="sql")
