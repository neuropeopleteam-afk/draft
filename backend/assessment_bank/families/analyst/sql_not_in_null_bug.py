"""analyst.sql.not_in_null_bug — find_bug: «клиенты без заказов» через NOT IN по столбцу с NULL.

В таблице заказов есть гостевые заказы без клиента (client_id = NULL). `id NOT IN (SELECT client_id …)` при
наличии NULL в подзапросе для любого id даёт «неизвестно» — отчёт пустой. Исправление — исключить NULL в
подзапросе (или NOT EXISTS) в той же строке. Рядом — верные строки той же формы (LEFT JOIN справочника,
фильтр по дате). Ключ проверяется исполнением показанного запроса в sqlite3.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import sql_py_program

FAMILY_ID = "analyst.sql.not_in_null_bug"

CTX = [("интернет-магазин", "clients", "orders", "клиенты без заказов", "заказ без регистрации"),
       ("сервис такси", "riders", "trips", "пассажиры без поездок", "поездка, заказанная по телефону"),
       ("онлайн-кинотеатр", "subscribers", "payments", "подписчики без оплат", "оплата подарочной картой"),
       ("фитнес-клуб", "members", "visits", "участники без посещений", "гостевой визит"),
       ("служба доставки", "customers", "deliveries", "получатели без доставок", "доставка без аккаунта")]
CITIES = ["Москва", "Казань", "Пермь", "Тула", "Омск"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, P, C, what, guest = rng.choice(CTX)
    fk = rng.choice(["client_id", "owner_id", "account_id"])
    month = rng.randint(2, 11)
    since = f"2026-{month:02d}-01"
    for _ in range(2000):
        n = rng.randint(6, 8)
        people = []
        for i in range(1, n + 1):
            people.append((i, f"user{rng.randint(10, 99)}", rng.randint(1, 3),
                           f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"))
        acts, aid = [], 0
        for p in people:
            for _ in range(rng.choice([0, 0, 1, 2])):
                aid += 1
                acts.append((aid, p[0], f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"))
        for _ in range(rng.randint(1, 2)):
            aid += 1
            acts.append((aid, None, f"2026-{rng.randint(month, 12):02d}-{rng.randint(1, 28):02d}"))
        active = {a[1] for a in acts if a[1] is not None and a[2] >= since}
        good = [(p[0], p[1], CITIES[p[2] - 1]) for p in people if p[3] >= since and p[0] not in active]
        if 2 <= len(good) <= 4 and any(a[1] is None and a[2] >= since for a in acts):
            break
    else:
        raise RuntimeError("нет данных")
    acts.sort(key=lambda a: a[0])
    bad = f"  AND p.id NOT IN (SELECT a.{fk} FROM {C} a WHERE a.created_at >= '{since}')"
    good_line = f"  AND p.id NOT IN (SELECT a.{fk} FROM {C} a WHERE a.created_at >= '{since}' AND a.{fk} IS NOT NULL)"
    order_first = rng.random() < 0.5

    def q(line):
        where = [f"WHERE p.registered_at >= '{since}'", line] if order_first else \
            [f"WHERE p.id NOT IN (SELECT a.{fk} FROM {C} a WHERE a.created_at >= '{since}'" +
             (f" AND a.{fk} IS NOT NULL)" if line == good_line else ")"), f"  AND p.registered_at >= '{since}'"]
        return "\n".join([f"SELECT p.id, p.login, c.name AS city", f"FROM {P} p",
                          "LEFT JOIN cities c ON c.id = p.city_id", *where, "ORDER BY p.id;"])
    buggy, fixed = q(bad), q(good_line)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    setup = ("CREATE TABLE cities (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n"
             + sql_inserts("cities", ["id", "name"], [(i + 1, c) for i, c in enumerate(CITIES)]) + "\n"
             f"CREATE TABLE {P} (id INTEGER PRIMARY KEY, login TEXT NOT NULL, city_id INTEGER NOT NULL, "
             f"registered_at TEXT NOT NULL);\n"
             + sql_inserts(P, ["id", "login", "city_id", "registered_at"], people) + "\n"
             f"CREATE TABLE {C} (id INTEGER PRIMARY KEY, {fk} INTEGER, created_at TEXT NOT NULL);\n"
             + sql_inserts(C, ["id", fk, "created_at"], acts) + "\n")
    checks = [Check(name="buggy_fails", runner="python", program=sql_py_program(buggy, setup, good), expect="fail"),
              Check(name="fixed_passes", runner="python", program=sql_py_program(fixed, setup, good),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Отчёт «{what}» ({ctx}): зарегистрированные с {since}, у которых с этой даты нет ни одной записи в "
            f"`{C}`. Столбец `{C}.{fk}` допускает NULL — так хранится {guest}. Запрос возвращает пустой "
            f"результат, хотя по данным такие есть. Данные `{C}` (`{P}` — {len(people)} строк):\n\n"
            f"{text_table(['id', fk, 'created_at'], acts)}\n\nУкажите номер строки запроса с ошибкой.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: в подзапросе есть NULL ({guest}), а `x NOT IN (…, NULL)` "
                                f"никогда не бывает истинным — сравнение с NULL даёт «неизвестно», и WHERE "
                                f"отбрасывает все строки. Нужно исключить NULL в подзапросе "
                                f"(`AND a.{fk} IS NOT NULL`) или использовать NOT EXISTS."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="not_in_with_null",
                         language="sql", params={"fixed_code": fixed, "expected_rows": len(good)})
