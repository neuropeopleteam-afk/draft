"""data_eng.sql.and_or_precedence_output — predict_output: приоритет AND над OR в WHERE.

Запрос выбирает строки по условию `A OR B AND C` без скобок; по стандарту SQL AND связывает сильнее, условие
читается как `A OR (B AND C)`. Ловушка уровня Intern/Junior — прочтение слева направо `(A OR B) AND C`: в каждом
варианте есть строка, которая попадает в результат только из-за приоритета AND (выполнено A, не выполнено C).
В каждом варианте есть и строка из второй части (B AND C). Порядок условий варьируется (A — по городу или по статусу), числа и данные — из генератора. Ключ — исполнение
запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.and_or_precedence_output"

CTX = [("заказы", "orders", "city", ["Казань", "Пермь", "Омск", "Тула", "Сочи", "Псков"], "amount", (300, 9000, 50)),
       ("доставки", "deliveries", "region", ["север", "юг", "центр", "запад", "восток", "урал"], "weight", (1, 40, 1)),
       ("обращения в поддержку", "tickets", "channel", ["чат", "почта", "телефон", "бот", "форма"], "wait_min",
        (1, 120, 1)),
       ("платежи", "payments", "method", ["карта", "СБП", "кошелёк", "счёт", "рассрочка"], "amount", (100, 20000, 100)),
       ("поездки такси", "rides", "tariff", ["эконом", "комфорт", "бизнес", "детский", "грузовой"], "km", (1, 60, 1)),
       ("загрузки файлов", "uploads", "source", ["web", "api", "ftp", "mobile", "sftp"], "size_mb", (1, 512, 1))]
STATUS = ["new", "done", "cancelled"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, cat, all_cats, num, (lo, hi, step) = rng.choice(CTX)
    for _ in range(2000):
        n = rng.randint(7, 9)
        cats = rng.sample(all_cats, rng.randint(3, 4))
        nums = sorted(rng.sample(range(lo, hi + 1, step), 6))
        first_id = rng.choice([1, 11, 101, 501, 1001])
        data = [(first_id + i, rng.choice(cats), rng.choice(STATUS), rng.choice(nums)) for i in range(n)]
        c1, c2 = rng.sample(cats, 2)
        thr = rng.choice(nums[1:-1])
        st = rng.choice(STATUS[:2])
        a_first = rng.random() < 0.5
        if a_first:
            a, b = f"{cat} = '{c1}'", f"{cat} = '{c2}'"
        else:
            a, b = f"status = '{st}'", f"{cat} = '{c1}'"
        c = f"{num} > {thr}"
        code = f"SELECT id, {cat}, status, {num}\nFROM {table}\nWHERE {a} OR {b} AND {c}\nORDER BY id;"
        setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {cat} TEXT, status TEXT, {num} INTEGER);\n"
                 + insert(table, ["id", cat, "status", num], data))
        out = rows(setup, code)
        wrong = rows(setup, code.replace(f"WHERE {a} OR {b} AND {c}", f"WHERE ({a} OR {b}) AND {c}"))
        only_a = rows(setup, code.replace(f"WHERE {a} OR {b} AND {c}", f"WHERE {a}"))
        k = len(out.splitlines()) if out else 0
        if out and out != wrong and out != only_a and 2 <= k <= 5 and k < n:
            break
    tbl = "\n".join(" | ".join(map(str, r)) for r in data)
    stem = (f"Таблица `{table}` ({ctx}) содержит строки (id | {cat} | status | {num}):\n{tbl}\n"
            "Что вернёт запрос? Ответ — строки вида `значение|значение|значение|значение`.")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"AND связывает сильнее OR: условие читается как {a} OR ({b} AND {c}). Строки, "
                               "где выполнено первое условие, попадают в результат независимо от третьего.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"a_first": a_first, "thr": thr})
