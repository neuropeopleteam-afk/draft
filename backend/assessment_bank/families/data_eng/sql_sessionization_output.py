"""data_eng.sql.sessionization_output — predict_output: сессии пользователей через LAG и сумму флагов.

Новая сессия начинается с первого события пользователя (LAG даёт NULL) или после паузы строго больше порога.
Подтип один: в данных есть пауза ровно на пороге (не новая сессия) и паузы чуть больше. Разница считается в
целых секундах (strftime('%s')), без погрешностей дробных дней. Ключ — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert, rows

FAMILY_ID = "data_eng.sql.sessionization_output"

CTX = [("клики в мобильном приложении", "app_events"), ("просмотры страниц сайта", "page_views"),
       ("действия в личном кабинете", "lk_events"), ("запросы к API партнёров", "api_calls")]
USERS = ["u1", "u2", "u3", "u7", "u9"]


def _ts(m):
    return f"2026-10-0{1 + m // 1440} {(m % 1440) // 60:02d}:{m % 60:02d}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    gap = rng.choice([20, 30, 45])
    users = sorted(rng.sample(USERS, rng.randint(2, 3)))
    data, eid = [], 1
    has_exact = False
    for u in users:
        t = rng.randint(8 * 60, 11 * 60)
        for _ in range(rng.randint(3, 5)):
            data.append((eid, u, _ts(t)))
            eid += 1
            step = rng.choice([gap, gap + 1, 5, 12, gap * 3, gap - 1, 90])
            has_exact |= step == gap
            t += step
    if not has_exact:  # пауза ровно на пороге есть в каждом варианте
        u, last = data[-1][1], data[-1][2]
        h, mm = int(last[11:13]), int(last[14:16])
        data.append((eid, u, _ts(h * 60 + mm + gap)))
    rng.shuffle(data)
    code = (f"WITH ordered AS (\n  SELECT user_id, ts,\n         LAG(ts) OVER (PARTITION BY user_id ORDER BY ts) AS prev_ts\n"
            f"  FROM {table}\n), flagged AS (\n  SELECT user_id,\n         CASE WHEN prev_ts IS NULL\n"
            f"                OR strftime('%s', ts) - strftime('%s', prev_ts) > {gap} * 60\n"
            "              THEN 1 ELSE 0 END AS new_session\n  FROM ordered\n)\n"
            "SELECT user_id, SUM(new_session) AS sessions, COUNT(*) AS events\nFROM flagged\nGROUP BY user_id\n"
            "ORDER BY user_id;")
    setup = f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, user_id TEXT, ts TEXT);\n" + insert(
        table, ["id", "user_id", "ts"], data)
    out = rows(setup, code)
    tbl = "\n".join(f"{u} | {t}" for _, u, t in data)
    stem = (f"Таблица `{table}` ({ctx}), строки (user_id | ts) в порядке загрузки:\n{tbl}\nЧто вернёт запрос "
            "сессионизации? Ответ — строки `user_id|sessions|events`.")
    checks = [Check(name="stdout", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_equals", expected_stdout=out)]
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"LAG берёт предыдущее событие того же пользователя по времени (порядок загрузки не "
                               f"важен); первое событие — новая сессия; пауза ровно {gap} мин новой сессии не "
                               "начинает (строгое >).")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"gap": gap, "n": len(data)})
