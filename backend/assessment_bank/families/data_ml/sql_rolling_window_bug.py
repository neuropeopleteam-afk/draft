"""data_ml.sql.rolling_window_bug — find_bug: скользящее окно в SQL (оконные функции, sqlite).

Запрос считает скользящую сумму/среднее за последние k дней, включая текущий, отдельно по
каждому объекту (магазин, склад, канал). Окно описано именованным WINDOW (есть и в SQLite,
и в PostgreSQL). Подтипы дефекта (меняется одна строка):
* ``frame_off_by_one`` — ``k PRECEDING`` вместо ``k-1 PRECEDING`` (окно из k+1 строк);
* ``no_partition`` — нет PARTITION BY: окно «перетекает» между объектами;
* ``future_frame`` — окно смотрит вперёд (``CURRENT ROW AND k-1 FOLLOWING``) — утечка
  будущего в признак.

Проверка: показанный запрос дословно исполняется в sqlite3 из Python-обвязки, результат
сравнивается с независимым расчётом в генераторе.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import sql_py_program

FAMILY_ID = "data_ml.sql.rolling_window_bug"

# (таблица, объект, показатель, контекст, имя признака, диапазон)
CONTEXTS = [
    ("daily_sales", "store_id", "revenue", "ритейл", "выручка", (20, 90)),
    ("warehouse_daily", "warehouse_id", "shipped", "логистика", "отгрузки", (5, 60)),
    ("channel_daily", "channel_id", "signups", "маркетинг", "регистрации", (1, 40)),
    ("app_daily", "app_id", "crashes", "мобильная аналитика", "падения приложения", (0, 25)),
    ("branch_daily", "branch_id", "loans", "банк", "выданные кредиты", (2, 30)),
    ("route_daily", "route_id", "passengers", "транспорт", "пассажиропоток", (40, 300)),
    ("support_daily", "queue_id", "tickets", "служба поддержки", "обращения", (10, 120)),
]
SUBTYPES = ["frame_off_by_one", "no_partition", "future_frame"]


def _query(T, obj, val, agg, k, alias, sub, expanded=False, day="day"):
    part = f"PARTITION BY {obj} " if sub != "no_partition" else ""
    frame = f"  ROWS BETWEEN {k - 1} PRECEDING AND CURRENT ROW)"
    if sub == "frame_off_by_one":
        frame = f"  ROWS BETWEEN {k} PRECEDING AND CURRENT ROW)"
    elif sub == "future_frame":
        frame = f"  ROWS BETWEEN CURRENT ROW AND {k - 1} FOLLOWING)"
    head = ([f"SELECT {obj},", f"       {day},", f"       {val},"] if expanded
            else [f"SELECT {obj}, {day}, {val},"])
    lines = head + [f"       {agg}({val}) OVER w AS {alias}",
             f"FROM {T}",
             f"WINDOW w AS ({part}ORDER BY {day}",
             frame,
             f"ORDER BY {obj}, {day};"]
    return "\n".join(lines)


def _ref(rows, agg, k, sub):
    """Независимый расчёт: rows = [(obj, day, val)], результат в порядке (obj, day)."""
    rows = sorted(rows)
    out = []
    for i, (o, d, v) in enumerate(rows):
        if sub == "no_partition":
            seq = sorted(rows, key=lambda r: (r[1], r[0]))  # окно по всем объектам, порядок по day
            j = seq.index((o, d, v))
            win = seq[max(0, j - (k - 1)): j + 1]
        else:
            same = [r for r in rows if r[0] == o]
            j = same.index((o, d, v))
            if sub == "frame_off_by_one":
                win = same[max(0, j - k): j + 1]
            elif sub == "future_frame":
                win = same[j: j + k]
            else:
                win = same[max(0, j - (k - 1)): j + 1]
        vals = [r[2] for r in win]
        out.append((o, d, v, sum(vals) if agg == "SUM" else sum(vals) / len(vals)))
    return out


# Калибровка 05.10: подтипы no_partition выделены в data_ml.sql.rolling_partition_bug (варианты были неизоморфны).
SUBTYPES_HERE = ('frame_off_by_one', 'future_frame')


def _generate(seed: int, family_id: str, subtypes):
    rng = make_rng(family_id, seed)
    T, obj, val, ctx, what, (lo, hi) = rng.choice(CONTEXTS)
    sub = rng.choice(list(subtypes))
    agg = rng.choice(["SUM", "AVG"])
    k = rng.choice([3, 4, 5, 7])
    day = rng.choice(["day", "dt", "report_date", "date_key"])
    short = "sum" if agg == "SUM" else "avg"
    alias = rng.choice([f"{short}_{k}d", f"{val}_{short}_{k}d", f"rolling_{short}_{k}"])
    expanded = rng.random() < 0.5
    buggy = _query(T, obj, val, agg, k, alias, sub, expanded, day)
    fixed = _query(T, obj, val, agg, k, alias, "good", expanded, day)
    key_line = sorted(changed_lines(buggy, fixed))[0]
    assert changed_lines(buggy, fixed) == {key_line}
    month = rng.randint(1, 12)
    objs = rng.sample(range(1, 30), 2)
    n_days = k + 3
    # в тестах — все дни подряд (пропусков нет), иначе ROWS ≠ «k календарных дней»
    for _ in range(200):
        rows = [(o, f"2026-{month:02d}-{d + 1:02d}", rng.randint(lo, hi))
                for o in objs for d in range(n_days)]
        exp = _ref(rows, agg, k, "good")
        if _ref(rows, agg, k, sub) != exp:
            break
    else:
        raise RuntimeError("дефект не проявился на данных")
    setup = (f"CREATE TABLE {T} ({obj} INTEGER NOT NULL, {day} TEXT NOT NULL, {val} INTEGER NOT NULL, "
             f"PRIMARY KEY ({obj}, {day}));\n" + sql_inserts(T, [obj, day, val], rows) + "\n")
    checks = [Check(name="buggy_fails", runner="python", program=sql_py_program(buggy, setup, exp),
                    expect="fail"),
              Check(name="fixed_passes", runner="python", program=sql_py_program(fixed, setup, exp),
                    expect="pass", embeds_display_code=False)]
    agg_text = "сумму" if agg == "SUM" else "среднее"
    stem = (f"Таблица `{T}({obj}, {day}, {val})` ({ctx}) содержит по одной строке на объект и "
            f"день, дни идут без пропусков. Для модели прогноза нужен признак `{alias}` — "
            f"скользящее {agg_text} показателя «{what}» за последние {k} дней, включая текущий, "
            f"отдельно для каждого `{obj}`. Пример строк:\n"
            f"{text_table([obj, day, val], rows[:3])}\n"
            f"Признак получился неверным. Укажите номер строки запроса с ошибкой.")
    why = {"frame_off_by_one": f"`{k} PRECEDING AND CURRENT ROW` — это {k + 1} строк; для {k} "
                               f"дней нужно `{k - 1} PRECEDING`",
           "no_partition": f"без `PARTITION BY {obj}` окно захватывает дни соседнего объекта",
           "future_frame": "окно смотрит вперёд (`FOLLOWING`): в признак попадают будущие дни — "
                           "это и неверно, и утечка"}[sub]
    ak = AnswerKey(kind="line", value=key_line, explanation=f"Строка {key_line}: {why}.")
    return build_variant(family_id, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="window_frame",
                         params={"fixed_code": fixed, "subtype": sub, "k": k, "agg": agg})



def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES_HERE)
