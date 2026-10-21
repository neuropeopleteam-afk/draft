"""analyst.sql.retention_cohort_fix — choose_fix: удержание дня N по когортам регистрации.

Требование: для каждой даты регистрации — размер когорты (все зарегистрированные), сколько из них вернулись
ровно на N-й день и доля в процентах. Показанный запрос соединяет пользователей с сессиями внутренним
соединением — пользователи без сессий выпадают из знаменателя. Верно — LEFT JOIN с условием дня N в ON.
Состав дистракторов фиксирован, все «почти верные»:
  * left_where — LEFT JOIN, но условие дня N в WHERE: соединение снова становится внутренним;
  * no_distinct — COUNT(s.user_id) без DISTINCT: несколько сессий в день N считаются несколько раз;
  * on_or_after — «на N-й день или позже» вместо «ровно на N-й день».
Ключ проверяется исполнением каждого варианта в sqlite3. Размеры когорт подобраны так, чтобы при ROUND до
десятых не было половинок (одинаковое округление в Python и SQLite).
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, run_sql

FAMILY_ID = "analyst.sql.retention_cohort_fix"

CTX = ["мобильная игра", "приложение для изучения языков", "фитнес-трекер", "сервис заметок", "онлайн-кинотеатр",
       "приложение банка"]


def _q(kind, n, uid, sess):
    day = f"DATE(u.signup_date, '+{n} day')"
    cond = f"s.session_date >= {day}" if kind == "on_or_after" else f"s.session_date = {day}"
    retained = "COUNT(s.user_id)" if kind == "no_distinct" else "COUNT(DISTINCT s.user_id)"
    if kind == "buggy":
        join = f"JOIN {sess} s\n  ON s.user_id = u.{uid} AND {cond}"
    elif kind == "left_where":
        join = f"LEFT JOIN {sess} s\n  ON s.user_id = u.{uid}\nWHERE {cond}"
    else:
        join = f"LEFT JOIN {sess} s\n  ON s.user_id = u.{uid} AND {cond}"
    return (f"SELECT u.signup_date AS cohort,\n       COUNT(DISTINCT u.{uid}) AS users,\n"
            f"       {retained} AS retained,\n"
            f"       ROUND(100.0 * {retained} / COUNT(DISTINCT u.{uid}), 1) AS rate\n"
            f"FROM users u\n{join}\nGROUP BY u.signup_date\nORDER BY cohort;")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    n = rng.choice([1, 3, 7])
    uid = rng.choice(["id", "user_id"])
    sess = rng.choice(["sessions", "app_sessions", "visits"])
    month = rng.randint(1, 11)
    dist = ["left_where", "no_distinct", "on_or_after"]
    for _ in range(3000):
        start = dt.date(2026, month, rng.randint(1, 10))
        cohorts = [start, start + dt.timedelta(days=rng.randint(1, 3))]
        users, sessions, sid = [], [], 0
        for c in cohorts:
            size = rng.choice([3, 6, 7])
            for _ in range(size):
                u = len(users) + 1
                users.append((u, c.isoformat()))
                for _ in range(rng.randint(0, 3)):
                    sid += 1
                    off = rng.choice([0, n, n, n + 1, n + 2])
                    sessions.append((sid, u, (c + dt.timedelta(days=off)).isoformat()))
        exp = []
        for c in cohorts:
            mine = [u for u in users if u[1] == c.isoformat()]
            ret = {s[1] for s in sessions if s[2] == (c + dt.timedelta(days=n)).isoformat()} & {u[0] for u in mine}
            exp.append(f"{c.isoformat()}|{len(mine)}|{len(ret)}|{round(100.0 * len(ret) / len(mine) + 1e-9, 1)}")
        good_out = "\n".join(exp)
        setup = (f"CREATE TABLE users ({uid} INTEGER PRIMARY KEY, signup_date TEXT NOT NULL);\n"
                 + sql_inserts("users", [uid, "signup_date"], users) +
                 f"\nCREATE TABLE {sess} (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, session_date TEXT NOT NULL);\n"
                 + sql_inserts(sess, ["id", "user_id", "session_date"], sessions) + "\n")
        if run_sql(setup, _q("good", n, uid, sess)) != good_out:
            continue
        outs = [run_sql(setup, _q(d, n, uid, sess)) for d in dist]
        if all(o != good_out for o in outs) and run_sql(setup, _q("buggy", n, uid, sess)) != good_out:
            break
    else:
        raise RuntimeError("нет данных")
    sessions.sort(key=lambda s: (s[2], s[1]))
    sessions = [(i + 1, s[1], s[2]) for i, s in enumerate(sessions)]
    setup = (f"CREATE TABLE users ({uid} INTEGER PRIMARY KEY, signup_date TEXT NOT NULL);\n"
             + sql_inserts("users", [uid, "signup_date"], users) +
             f"\nCREATE TABLE {sess} (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, session_date TEXT NOT NULL);\n"
             + sql_inserts(sess, ["id", "user_id", "session_date"], sessions) + "\n")
    code = _q("buggy", n, uid, sess)
    label = "Заменить запрос на:"
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label, _q("good", n, uid, sess)),
                                 [(label, _q(d, n, uid, sess)) for d in dist])
    checks = [Check(name="buggy_differs", runner="sqlite", program=code, files={"setup.sql": setup},
                    expect="stdout_differs", expected_stdout=good_out)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="sqlite", program=o.code, files={"setup.sql": setup},
                            embeds_display_code=False, expect="stdout_equals" if o.id == key else "stdout_differs",
                            expected_stdout=good_out))
    stem = (f"Продуктовый аналитик ({ctx}) считает удержание дня {n}: для каждой даты регистрации — размер когорты "
            f"(все зарегистрировавшиеся в этот день), сколько из них открыли приложение ровно на {n}-й день после "
            f"регистрации и доля в процентах. Показанный запрос даёт завышенное удержание. Данные: `users` — "
            f"{len(users)} пользователей в двух когортах; `{sess}`:\n\n"
            f"{text_table(['id', 'user_id', 'session_date'], sessions)}\n\n"
            f"Какой из запросов считает требуемую метрику правильно на любых данных?")
    why = {"left_where": "условие дня в WHERE отбрасывает строки без сессии (NULL) — LEFT JOIN снова становится "
                         "внутренним, знаменатель занижен",
           "no_distinct": "без DISTINCT несколько сессий одного пользователя в этот день считаются несколько раз",
           "on_or_after": f"«не раньше {n}-го дня» — другая метрика (возврат в любой день после), а не удержание "
                          f"ровно на {n}-й день"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Внутреннее соединение выбрасывает тех, кто не вернулся, — они пропадают из размера "
                                f"когорты. Верно: LEFT JOIN, условие дня {n} — в ON, вернувшиеся — COUNT(DISTINCT "
                                f"s.user_id). Дистракторы: " + "; ".join(why[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="inner_join_denominator",
                         language="sql", params={"day": n, "distractors": dist})
