"""data_eng.sql.group_by_having_output — predict_output: WHERE до группировки, HAVING после.

Запрос считает по клиентам число и сумму записей, отфильтрованных WHERE (статус), и оставляет группы по
условию HAVING; сортировка по агрегату. Ловушки уровня Intern/Junior: строки, отброшенные WHERE, не входят в
COUNT; HAVING применяется к группе, а не к строке; порядок по убыванию суммы. Ключ — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.group_by_having_output"

CTX = [("заказы интернет-магазина", "orders", "customer", ["paid", "cancelled", "refunded"], "paid"),
       ("платежи по подпискам", "payments", "account", ["ok", "failed", "pending"], "ok"),
       ("заявки на доставку", "deliveries", "client", ["done", "cancelled", "lost"], "done"),
       ("счета поставщикам", "invoices", "supplier", ["approved", "rejected", "draft"], "approved")]
NAMES = ["anna", "boris", "vera", "gleb", "dina", "egor", "zhanna", "ilya"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, who, statuses, good = rng.choice(CTX)
    names = rng.sample(NAMES, rng.randint(3, 4))
    for _ in range(500):
        data = []
        for i in range(rng.randint(7, 10)):
            data.append((i + 1, rng.choice(names), rng.choice([good, good] + statuses[1:]),
                         rng.choice([100, 150, 200, 250, 300, 400, 500])))
        mode = rng.choice(["count", "sum"])
        thr = rng.choice([2, 3]) if mode == "count" else rng.choice([300, 400, 500])
        having = f"COUNT(*) >= {thr}" if mode == "count" else f"SUM(amount) > {thr}"
        where = rng.choice([f"status = '{good}'", f"status <> '{statuses[1]}'"])
        code = (f"SELECT {who}, COUNT(*) AS n, SUM(amount) AS total\nFROM {table}\nWHERE {where}\n"
                f"GROUP BY {who}\nHAVING {having}\nORDER BY total DESC, {who};")
        setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {who} TEXT, status TEXT, amount INTEGER);\n"
                 + insert(table, ["id", who, "status", "amount"], data))
        out = rows(setup, code)
        # WHERE и HAVING оба должны что-то менять, а результат — не пустой
        no_where = rows(setup, code.replace(f"WHERE {where}\n", ""))
        no_having = rows(setup, code.replace(f"HAVING {having}\n", ""))
        if out and out != no_where and out != no_having and 1 <= len(out.splitlines()) <= 3:
            break
    tbl = "\n".join(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}" for r in data)
    stem = (f"Таблица `{table}` ({ctx}) содержит строки (id | {who} | status | amount):\n{tbl}\n"
            "Что вернёт запрос? Ответ — строки вида `значение|значение|значение`.")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out,
                   explanation="WHERE отбрасывает строки до группировки, COUNT и SUM считают оставшиеся; HAVING "
                               "фильтрует уже группы; сортировка — по сумме по убыванию.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"mode": mode, "thr": thr})
