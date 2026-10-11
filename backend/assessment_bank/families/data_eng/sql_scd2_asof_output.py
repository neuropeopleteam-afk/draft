"""data_eng.sql.scd2_asof_output — predict_output: соединение фактов с измерением SCD2 по интервалу действия.

Измерение SCD типа 2: у версии записи [valid_from, valid_to) — правая граница не включается, у текущей версии
valid_to = '9999-12-31'. Факты соединяются с версией, действовавшей на дату факта. Подтип один: в данных есть
факт ровно на дате смены версии (относится к новой версии). Ключ — исполнение запроса в sqlite.
Версия 2 (11.10): даты, ключи, суммы и значения атрибутов — из генератора (6 контекстов), чтобы различимых
вариантов было ≥ 20 (в версии 1 — 11 на 80 seed по tools/check_family_variants.py).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.scd2_asof_output"

CTX = [("выручка по городам клиентов", "dim_customer", "orders", "customer_id", "city",
        ["Москва", "Казань", "Самара", "Пермь", "Тверь", "Сочи"]),
       ("продажи по регионам магазинов", "dim_store", "sales", "store_id", "region",
        ["north", "south", "east", "west", "center"]),
       ("выплаты по тарифам курьеров", "dim_courier", "payouts", "courier_id", "tariff",
        ["base", "pro", "night", "weekend", "peak"]),
       ("заказы по сегментам партнёров", "dim_partner", "partner_orders", "partner_id", "segment",
        ["smb", "mid", "enterprise", "gov", "startup"]),
       ("звонки по отделам сотрудников", "dim_employee", "calls", "employee_id", "department",
        ["sales", "support", "retention", "billing", "onboarding"]),
       ("поставки по категориям поставщиков", "dim_supplier", "deliveries", "supplier_id", "category",
        ["food", "electronics", "textile", "pharma", "tools"])]


def _dates(rng):
    """Пять различных дат 2026 года по возрастанию."""
    out = set()
    while len(out) < 5:
        out.add(f"2026-{rng.randint(1, 11):02d}-{rng.randint(1, 28):02d}")
    return sorted(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, dim, fact, key, attr, values = rng.choice(CTX)
    for _ in range(500):
        dates = _dates(rng)
        dim_rows, facts, fid = [], [], rng.choice([1, 101, 1001, 5001])
        ent0 = rng.randint(10, 900)
        for ent in range(ent0, ent0 + rng.randint(2, 3)):
            changes = sorted(rng.sample(dates[1:], rng.randint(1, 2)))
            bounds = ["2025-01-01"] + changes + ["9999-12-31"]
            vals = rng.sample(values, len(bounds) - 1)
            for i in range(len(bounds) - 1):
                dim_rows.append((ent, vals[i], bounds[i], bounds[i + 1]))
            for d in rng.sample(dates, 3) + [changes[0]]:
                facts.append((fid, ent, d, rng.randrange(50, 1000, 10)))
                fid += 1
        code = (f"SELECT d.{attr}, SUM(f.amount) AS total\nFROM {fact} f\nJOIN {dim} d\n"
                f"  ON d.{key} = f.{key}\n AND f.{fact[0]}_date >= d.valid_from\n AND f.{fact[0]}_date < d.valid_to\n"
                f"GROUP BY d.{attr}\nORDER BY d.{attr};")
        setup = (f"CREATE TABLE {dim} ({key} INTEGER, {attr} TEXT, valid_from TEXT, valid_to TEXT);\n"
                 f"CREATE TABLE {fact} (id INTEGER PRIMARY KEY, {key} INTEGER, {fact[0]}_date TEXT, amount INTEGER);\n"
                 + insert(dim, [key, attr, "valid_from", "valid_to"], dim_rows) + "\n"
                 + insert(fact, ["id", key, f"{fact[0]}_date", "amount"], facts))
        out = rows(setup, code)
        incl = rows(setup, code.replace(f"< d.valid_to", f"<= d.valid_to"))
        if out != incl and len(out.splitlines()) >= 2:
            break
    t_dim = "\n".join(f"{a} | {b} | {c} | {d}" for a, b, c, d in dim_rows)
    t_fact = "\n".join(f"{a} | {b} | {c} | {d}" for a, b, c, d in facts)
    stem = (f"Отчёт «{ctx}». Измерение `{dim}` ({key} | {attr} | valid_from | valid_to):\n{t_dim}\n"
            f"Факты `{fact}` (id | {key} | {fact[0]}_date | amount):\n{t_fact}\nЧто вернёт запрос? Ответ — строки "
            "`значение|сумма`.")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out,
                   explanation="Интервал версии полуоткрытый: valid_from включается, valid_to — нет, поэтому факт в "
                               "день смены относится к новой версии и не считается дважды.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"n_dim": len(dim_rows)})
