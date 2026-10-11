"""analyst.lead.metric_definition_fix — choose_fix (Lead, SQL): запрос не реализует определение конверсии когорты.

Определение метрики: доля пользователей когорты (зарегистрировались в окне [D, D+7), без тестовых), совершивших
хотя бы одну покупку в течение W суток после момента регистрации — полуинтервал [registered_at, registered_at + W сут).
Покупки до регистрации (гостевой заказ, привязанный позже) не считаются; пользователь считается один раз.

Показан запрос дашборда: LEFT JOIN, а условия на покупку стоят в WHERE — соединение становится внутренним,
знаменатель схлопывается до купивших, дашборд показывает 100 %. Варианты — четыре запроса в другом стиле (CTE),
все с верным знаменателем; дистракторы — по схеме 2×2 из двух правил пула (нарушено одно, другое, оба; ни один
вариант не «центральный»):

* ``inclusive_bound`` — правая граница включительно (покупка ровно через W суток засчитывается);
* ``no_distinct`` — в числителе считаются покупки, а не пользователи (двойной счёт);
* ``day_lower_bound`` — нижняя граница по дате регистрации, а не моменту (гостевой заказ того же дня до регистрации).

Ключ — исполнение в SQLite (через Python) всех вариантов на данных варианта: в данных есть каждый пограничный
случай, ожидаемое значение считается генератором независимо от запросов.
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.families._lead_b_utils import factorial_distractors
from assessment_bank.families.data_ml._dm_utils import balanced_options, sql_py_program
from assessment_bank.gen_utils import build_variant, make_rng, plural, sql_inserts
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "analyst.lead.metric_definition_fix"

CONTEXTS = [("интернет-магазин", "users", "orders", "покупку"), ("сервис доставки еды", "clients", "orders", "заказ"),
            ("онлайн-школа", "students", "payments", "оплату курса"), ("приложение такси", "riders", "trips", "поездку"),
            ("маркетплейс услуг", "customers", "bookings", "бронирование"),
            ("сервис подписки", "accounts", "payments", "оплату подписки")]
COLS = [("registered_at", "is_test"), ("signup_at", "is_internal"), ("created_at", "test_flag")]
ALIASES = [("u", "p"), ("c", "o"), ("a", "e")]

BUGGY = """SELECT 1.0 * COUNT(DISTINCT {p}.user_id) / COUNT(DISTINCT {u}.id) AS conversion
FROM {users} {u}
LEFT JOIN {events} {p} ON {p}.user_id = {u}.id
WHERE {u}.{test} = 0
  AND {u}.{reg} >= '{d0}' AND {u}.{reg} < '{d1}'
  AND {p}.ts >= {u}.{reg}
  AND {p}.ts < datetime({u}.{reg}, '+{w} days')"""

CORRECT = """WITH cohort AS (
  SELECT id, {reg} AS reg FROM {users}
  WHERE {test} = 0 AND {reg} >= '{d0}' AND {reg} < '{d1}'
),
converted AS (
  SELECT DISTINCT c.id FROM cohort c
  JOIN {events} e ON e.user_id = c.id
  WHERE e.ts >= c.reg AND e.ts < datetime(c.reg, '+{w} days')
)
SELECT 1.0 * (SELECT COUNT(*) FROM converted) / (SELECT COUNT(*) FROM cohort) AS conversion"""

MUTATIONS = {  # правило → (фрагмент верного текста, замена); дистракторы — по схеме 2×2
    "inclusive_bound": ("e.ts < datetime(c.reg,", "e.ts <= datetime(c.reg,"),
    "no_distinct": ("SELECT DISTINCT c.id FROM cohort c", "SELECT c.id FROM cohort c"),
    "day_lower_bound": ("WHERE e.ts >= c.reg AND", "WHERE e.ts >= date(c.reg) AND"),
}
DISTRACTORS = {k: CORRECT.replace(*v) for k, v in MUTATIONS.items()}
assert all(d != CORRECT for d in DISTRACTORS.values())

WHY = {
    "inclusive_bound": "правая граница включительно — покупка ровно через W суток засчитывается, а по определению "
                       "окно — полуинтервал",
    "no_distinct": "без DISTINCT в числителе считаются покупки, а не пользователи — несколько покупок одного "
                   "пользователя завышают конверсию",
    "day_lower_bound": "нижняя граница по дате, а не моменту регистрации — засчитываются гостевые заказы того же "
                       "дня, сделанные до регистрации",
}


def _ts(x: dt.datetime) -> str:
    return x.strftime("%Y-%m-%d %H:%M:%S")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, users, events, what = rng.choice(CONTEXTS)
    reg, test = rng.choice(COLS)
    u, p = rng.choice(ALIASES)
    w = rng.choice([3, 7, 14])
    d0 = dt.datetime(2026, rng.choice([6, 7, 8, 9]), rng.randint(1, 20))
    d1 = d0 + dt.timedelta(days=7)
    n_none, n_one, n_multi = rng.randint(3, 6), rng.randint(2, 5), 1
    n_exact, n_guest, extra = rng.sample([1, 2, 3], 3)  # различные — значения вариантов не совпадают
    rows_u, rows_e = [], []
    uid, eid = rng.randint(100, 900), rng.randint(5000, 9000)

    def add_user(is_test=0, inside=True):
        nonlocal uid
        uid += rng.randint(1, 4)
        base = d0 if inside else d0 - dt.timedelta(days=rng.randint(8, 20))
        t = base + dt.timedelta(days=rng.randint(0, 6), hours=rng.randint(3, 21), minutes=rng.randint(0, 59))
        rows_u.append((uid, _ts(t), is_test))
        return uid, t

    def add_event(user, t):
        nonlocal eid
        eid += rng.randint(1, 5)
        rows_e.append((eid, user, _ts(t)))

    in_win = lambda t: t + dt.timedelta(hours=rng.randint(1, 24 * w - 2))  # noqa: E731
    for _ in range(n_none):
        add_user()
    for _ in range(n_one):
        i, t = add_user()
        add_event(i, in_win(t))
    i, t = add_user()  # один пользователь с несколькими покупками в окне: 1 + extra
    for _ in range(1 + extra):
        add_event(i, in_win(t))
    for _ in range(n_exact):
        i, t = add_user()
        add_event(i, t + dt.timedelta(days=w))
    for _ in range(n_guest):
        i, t = add_user()
        add_event(i, t.replace(hour=rng.randint(0, t.hour - 1), minute=rng.randint(0, 59)))
    i, t = add_user()
    add_event(i, t + dt.timedelta(days=w + rng.randint(2, 6)))
    for _ in range(rng.randint(1, 2)):
        i, t = add_user(is_test=1)
        add_event(i, in_win(t))
    for _ in range(2):
        i, t = add_user(inside=False)
        add_event(i, in_win(t))
    rng.shuffle(rows_u)
    rng.shuffle(rows_e)
    denom = n_none + n_one + n_multi + n_exact + n_guest + 1
    conv = n_one + n_multi
    multi_events = 1 + extra
    expected = {"good": conv / denom, "inclusive_bound": (conv + n_exact) / denom,
                "no_distinct": (n_one + multi_events) / denom, "day_lower_bound": (conv + n_guest) / denom}
    if len({round(v, 9) for v in expected.values()}) != 4:  # pragma: no cover
        raise RuntimeError("значения вариантов совпали")
    fmt = dict(users=users, events=events, reg=reg, test=test, u=u, p=p, w=w,
               d0=d0.strftime("%Y-%m-%d"), d1=d1.strftime("%Y-%m-%d"))
    setup = (f"CREATE TABLE {users} (id INTEGER PRIMARY KEY, {reg} TEXT, {test} INTEGER);\n"
             f"CREATE TABLE {events} (id INTEGER PRIMARY KEY, user_id INTEGER, ts TEXT);\n"
             + sql_inserts(users, ["id", reg, test], rows_u) + "\n" + sql_inserts(events, ["id", "user_id", "ts"], rows_e))
    code = BUGGY.format(**fmt)
    correct = CORRECT.format(**fmt)
    dis, kinds = factorial_distractors(CORRECT, MUTATIONS, rng)
    dis = [d.format(**fmt) for d in dis]
    label = "Заменить запрос на:"
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label, correct), [(label, d) for d in dis])
    by_text = {correct: "good", **{d: k for d, k in zip(dis, kinds)}}
    good = [(expected["good"],)]
    checks = [Check(name="buggy_fails", runner="python", program=sql_py_program(code, setup, good), expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python", program=sql_py_program(o.code, setup, good),
                            expect="pass" if o.id == key else "fail", embeds_display_code=False))
    days_w = plural(w, "сутки", "суток", "суток")
    stem = (f"{ctx.capitalize()}: метрика «конверсия в {what} за {w} {days_w}» определена так — доля пользователей "
            f"когорты (зарегистрировались с {fmt['d0']} по {(d1 - dt.timedelta(days=1)).strftime('%Y-%m-%d')} "
            f"включительно, без тестовых: `{test} = 0`), совершивших целевое действие ({what}) хотя бы раз в "
            f"полуинтервале [момент регистрации; момент регистрации + {w} {days_w}). Действия до регистрации "
            f"(гостевые заказы, привязанные позже) не считаются, пользователь считается один раз; действия — в "
            f"таблице `{events}` (`user_id`, `ts`). Запрос дашборда ниже показывает "
            f"100 %, хотя по выгрузке продукта конверсия намного ниже. Какой запрос реализует определение точно?")
    why = ("Показанный запрос ставит условия на покупку в WHERE после LEFT JOIN: строки пользователей без покупок "
           "отбрасываются, знаменатель равен числу купивших. Верный вариант считает когорту отдельно и пользователей "
           "с покупкой в полуинтервале — через DISTINCT. Остальные: " + "; ".join(WHY[k].replace("W суток", f"{w} {days_w}") for k in kinds[:2])
           + "; четвёртый вариант нарушает оба этих правила"
           + ". Для Lead: определение метрики фиксируется вместе с пограничными случаями (границы окна, гостевые "
           "заказы, тестовые пользователи) и проверочным набором данных, иначе дашборд и выгрузки расходятся.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts,
                         answer_key=AnswerKey(kind="option", value=key, explanation=why), context=ctx,
                         verification="execution", checks=checks, defect_type="where_kills_left_join",
                         params={"window_days": w, "expected": round(expected["good"], 6),
                                 "distractors": kinds, "option_kinds": {o.id: by_text[o.code] for o in opts}},
                         display_code_note="Каждый запрос исполняется в SQLite на одних и тех же данных; ожидаемое "
                                           "значение генератор считает по определению, независимо от запросов.")
