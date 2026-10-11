"""analyst.sql.funnel_distinct_bug — find_bug: воронка считает события вместо пользователей на одном шаге.

Запрос воронки: число пользователей, у которых было событие шага (хотя бы одно). На одном шаге забыт
DISTINCT — считаются события, и у пользователей с повторными событиями шаг «раздувается» (конверсия выше
100 %). Один подтип дефекта; варьируются шаги, их число (3–4), номер шага с дефектом, период, контекст.
Ключ проверяется исполнением показанного запроса в sqlite3 на данных с повторными событиями.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import sql_py_program

FAMILY_ID = "analyst.sql.funnel_distinct_bug"

CTX = [("интернет-магазин", ["view_item", "add_to_cart", "checkout", "purchase"]),
       ("сервис доставки еды", ["open_menu", "add_dish", "pay", "order_done"]),
       ("онлайн-школа", ["open_course", "start_lesson", "finish_lesson", "buy_course"]),
       ("банк, оформление карты", ["open_form", "fill_passport", "sign_offer", "card_issued"]),
       ("сервис бронирования отелей", ["search", "open_hotel", "book_start", "book_paid"]),
       ("маркетплейс услуг", ["open_service", "choose_slot", "confirm", "visit_done"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, all_steps = rng.choice(CTX)
    k = rng.choice([3, 4])
    steps = all_steps[:k] if k == 4 or rng.random() < 0.5 else [all_steps[0], all_steps[1], all_steps[3]]
    bad = rng.randint(1, k - 1)
    tbl = rng.choice(["events", "app_events", "user_events"])
    month = rng.randint(1, 12)
    day_from, day_to = rng.choice([(1, 7), (8, 14), (15, 21)])
    d1, d2 = f"2026-{month:02d}-{day_from:02d}", f"2026-{month:02d}-{day_to:02d}"
    for _ in range(3000):
        rows, rid = [], 0
        users = rng.sample(range(100, 999), rng.randint(5, 7))
        reach = {}
        for u in users:
            depth = rng.randint(1, k)
            reach[u] = depth
            for i in range(depth):
                for _ in range(rng.choice([1, 1, 2, 3]) if i == bad else rng.choice([1, 1, 2])):
                    rid += 1
                    rows.append((rid, u, steps[i], f"2026-{month:02d}-{rng.randint(day_from, day_to):02d}"))
        for _ in range(2):  # события вне периода
            rid += 1
            rows.append((rid, rng.choice(users), steps[0], f"2026-{month:02d}-{rng.choice([28]):02d}"))
        good = tuple(sum(1 for u in users if reach[u] > i) for i in range(k))
        cnt_bad = sum(1 for r in rows if r[2] == steps[bad] and d1 <= r[3] <= d2)
        if cnt_bad > good[bad - 1] and good[bad] >= 1 and len(set(good)) >= 2:
            break
    else:
        raise RuntimeError("нет данных")
    rows.sort(key=lambda r: (r[3], r[0]))
    rows = [(i + 1, r[1], r[2], r[3]) for i, r in enumerate(rows)]
    aliases = ["step" + str(i + 1) for i in range(k)]

    def q(fixed: bool) -> str:
        sel = []
        for i, st in enumerate(steps):
            dist = "DISTINCT " if (i != bad or fixed) else ""
            sel.append(f"  COUNT({dist}CASE WHEN event = '{st}' THEN user_id END) AS {aliases[i]}")
        return ("SELECT\n" + ",\n".join(sel) + f"\nFROM {tbl}\nWHERE event_date BETWEEN '{d1}' AND '{d2}';")
    buggy, fixed = q(False), q(True)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    setup = (f"CREATE TABLE {tbl} (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, event TEXT NOT NULL, "
             f"event_date TEXT NOT NULL);\n" + sql_inserts(tbl, ["id", "user_id", "event", "event_date"], rows) + "\n")
    expected = [good]
    checks = [Check(name="buggy_fails", runner="python", program=sql_py_program(buggy, setup, expected), expect="fail"),
              Check(name="fixed_passes", runner="python", program=sql_py_program(fixed, setup, expected),
                    expect="pass", embeds_display_code=False)]
    names = " → ".join(f"`{s}`" for s in steps)
    stem = (f"Аналитик ({ctx}) считает воронку {names} за период {d1} … {d2}: на каждом шаге — число "
            f"пользователей, у которых было хотя бы одно событие шага. В отчёте шаг `{aliases[bad]}` "
            f"(`{steps[bad]}`) больше предыдущего, конверсия выше 100 %. Данные `{tbl}`:\n\n"
            f"{text_table(['id', 'user_id', 'event', 'event_date'], rows)}\n\nУкажите номер строки запроса с ошибкой.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: без DISTINCT шаг `{steps[bad]}` считает события, а не "
                                f"пользователей — повторные события одного пользователя считаются несколько раз. "
                                f"Верно: COUNT(DISTINCT CASE …). Правильная воронка: "
                                f"{' → '.join(map(str, good))}."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="count_events_not_users",
                         language="sql", params={"fixed_code": fixed, "steps": steps, "bad_step": bad})
