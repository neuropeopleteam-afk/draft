"""data_eng.etl.tz_partition_bug — find_bug: дата партиции берётся из времени UTC, а партиции — по местной дате.

Событие хранит время в UTC; партиции витрины — по дате в местном часовом поясе (UTC+3…+10: Москва, Екатеринбург,
Новосибирск, Владивосток). В одной строке дата берётся из времени UTC без перевода, и поздние по UTC события
попадают в предыдущий день. Ловушки-«не ошибки»: константа пояса, is_valid и перевод в функции метки загрузки
верны. Исправление — `ts.astimezone(<пояс>).date()` в той же строке. Проверка — исполнение показанного кода
в песочнице Python.
"""
from __future__ import annotations

from datetime import date, timedelta

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.etl.tz_partition_bug"

CTX = [("заказы интернет-магазина", "orders"), ("поездки каршеринга", "rides"), ("платежи", "payments"),
       ("заявки поддержки", "tickets"), ("показы рекламы", "impressions"), ("доставки курьеров", "deliveries"),
       ("звонки колл-центра", "calls")]
TZ = [("Москве", "MSK", 3), ("Екатеринбургу", "YEKT", 5), ("Новосибирску", "NOVT", 7), ("Владивостоку", "VLAT", 10)]
PART = ["dt", "date", "day"]
SOURCES = [("app", "web", "api"), ("ios", "android", "web"), ("site", "partner", "api")]


def _code(table, fixed, order, field, tzname, off, pk, comment, srcs):
    day = f"ts.astimezone({tzname}).date().isoformat()" if fixed else "ts.date().isoformat()"
    cm = "  # время в UTC" if comment else ""
    part = ["def partition_path(event):", f'    ts = datetime.fromisoformat(event["{field}"]){cm}',
            f"    day = {day}", f'    return f"{table}/{pk}={{day}}/source={{event[\'source\']}}"']
    load = ["def load_label(now_utc):", f'    return now_utc.astimezone({tzname}).strftime("%Y-%m-%d %H:%M")']
    valid = ["def is_valid(event):", '    return event.get("source") in SOURCES']
    blocks = [[part, load, valid], [load, part, valid], [valid, part, load], [load, valid, part]][order]
    out = ["from datetime import datetime, timedelta, timezone", "", f"{tzname} = timezone(timedelta(hours={off}))",
           f"SOURCES = {srcs!r}", "", ""]
    for i, b in enumerate(blocks):
        out += b + ([] if i == len(blocks) - 1 else ["", ""])
    return "\n".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    city, tzname, off = rng.choice(TZ)
    order = rng.randrange(4)
    field = rng.choice(["ts", "created_at", "event_time", "occurred_at"])
    pk = rng.choice(PART)
    comment = rng.random() < 0.5
    srcs = rng.choice(SOURCES)
    code = _code(table, False, order, field, tzname, off, pk, comment, srcs)
    fixed = _code(table, True, order, field, tzname, off, pk, comment, srcs)
    ch = changed_lines(code, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    day = rng.choice(["2026-09-30", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-31"])
    late_h = rng.randint(24 - off, 23)
    early_h = rng.randint(1, 23 - off)
    s_late, s_early = rng.sample(srcs, 2)
    ev = [{field: f"{day}T{late_h:02d}:{rng.randint(10, 59)}:00+00:00", "source": s_late},
          {field: f"{day}T{early_h:02d}:{rng.choice(['05', '20', '45'])}:00+00:00", "source": s_early}]
    if rng.random() < 0.5:
        ev.reverse()
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    exp = [f"{table}/{pk}={nxt if e['source'] == s_late else day}/source={e['source']}" for e in ev]
    test = (f"\n\n\nEVENTS = {ev!r}\ngot = [partition_path(e) for e in EVENTS]\n"
            f"print(\"RESULT: PASS\" if got == {exp!r} else \"RESULT: FAIL\")\n")
    checks = [Check(name="buggy_fails", runner="python", program=code + test, expect="fail"),
              Check(name="fixed_passes", runner="python", program=fixed + test, expect="pass",
                    embeds_display_code=False)]
    ex = "\n".join(f"{e[field]} (source={e['source']}) → ожидается {x}" for e, x in zip(ev, exp))
    stem = (f"Витрина «{ctx}» разложена по партициям с датой по {city} (UTC+{off}); время событий в `{field}` "
            "хранится в UTC. Аналитики видят, что вечерние события попадают в партицию предыдущего дня. "
            f"Пример:\n{ex}\nУкажите номер строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key,
                   explanation=f"Строка {key}: дата берётся из времени UTC; событие в {late_h}:xx UTC — это уже "
                               f"следующие сутки по {city} (UTC+{off}). Нужно ts.astimezone({tzname}).date(). "
                               f"Константа {tzname}, is_valid и load_label верны.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="utc_date_partition",
                         params={"fixed_code": fixed, "order": order, "field": field, "tz": tzname})
