"""data_eng.sql.left_join_filter_bug — find_bug: условие на правую таблицу в WHERE превращает LEFT JOIN во внутренний.

Отчёт должен содержать все записи левой таблицы, включая те, у которых нет подходящих строк справа (ноль).
Условие на столбец правой таблицы стоит в WHERE: строки с NULL справа отбрасываются. Исправление — перенести
условие в ON (строка `WHERE …` → `AND …`, продолжение условия соединения). Ловушки-«не ошибки»: COUNT(o.id)
вместо COUNT(*) и COALESCE(SUM(…), 0) — они верны. Проверка — исполнение показанного запроса в sqlite
(обвязка на Python): дефектный запрос теряет строки, исправленный совпадает с эталоном.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import harness, insert, rows

FAMILY_ID = "data_eng.sql.left_join_filter_bug"

CTX = [("клиенты и заказы", "customers", "orders", "customer_id", "клиента"),
       ("магазины и продажи", "stores", "sales", "store_id", "магазина"),
       ("курьеры и доставки", "couriers", "deliveries", "courier_id", "курьера"),
       ("авторы и статьи", "authors", "posts", "author_id", "автора")]
NAMES = ["Альфа", "Бета", "Гамма", "Дельта", "Омега", "Сигма"]
FILTERS = [("created_at >= '{d}'", "начиная с {d}"), ("status = '{st}'", "в статусе {st}"),
           ("amount >= {a}", "на сумму от {a}"), ("channel = '{ch}'", "из канала {ch}")]
ALIASES = [("l", "r"), ("c", "o"), ("a", "b"), ("m", "t")]


def _query(L, R, fk, flt, agg, fixed, sh):
    x, y = sh["alias"]
    cond = f"      AND {y}.{flt}" if fixed else f"WHERE {y}.{flt}"
    sel = f"COUNT({y}.id) AS cnt" if agg == "count" else f"COALESCE(SUM({y}.amount), 0) AS total"
    out = []
    if sh["comment"]:
        out.append(f"-- {sh['comment']}")
    if sh["city"]:
        out += [f"SELECT {x}.name,", f"       {x}.city,", f"       {sel}"]
    else:
        out.append(f"SELECT {x}.name, {sel}")
    out += [f"FROM {L} {x}", f"LEFT JOIN {R} {y} ON {y}.{fk} = {x}.id", cond]
    out.append(f"GROUP BY {x}.id, {x}.name" + (f", {x}.city" if sh["city"] else ""))
    out.append(f"ORDER BY {x}.name;" if sh["order"] == "name" else
               f"ORDER BY {sel.split(' AS ')[1]} DESC, {x}.name;")
    return "\n".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, L, R, fk, gen = rng.choice(CTX)
    flt_t, txt_t = rng.choice(FILTERS)
    pv = dict(d=rng.choice(["2026-01-01", "2026-03-01", "2025-12-01"]), st=rng.choice(["done", "new"]),
              a=rng.choice([800, 1000, 2500]), ch=rng.choice(["app", "web"]))
    flt, flt_txt = flt_t.format(**pv), txt_t.format(**pv)
    sh = {"alias": rng.choice(ALIASES), "city": rng.random() < 0.5, "order": rng.choice(["name", "agg"]),
          "comment": rng.choice([None, None, f"отчёт для отдела продаж", "выгрузка для дашборда", "сверка за период"])}
    agg = rng.choice(["count", "sum"])
    names = rng.sample(NAMES, rng.randint(3, 5))
    left = [(i + 1, n, rng.choice(["Москва", "Казань", "Пермь"])) for i, n in enumerate(names)]
    for _ in range(500):
        right = []
        for j in range(rng.randint(5, 9)):
            right.append((j + 1, rng.randint(1, len(names)), rng.choice(["2025-11-03", "2026-02-10", "2026-05-20"]),
                          rng.choice(["done", "new", "cancelled"]), rng.choice([300, 800, 1000, 2500, 4000]),
                          rng.choice(["app", "web"])))
        setup = (f"CREATE TABLE {L} (id INTEGER PRIMARY KEY, name TEXT, city TEXT);\n"
                 f"CREATE TABLE {R} (id INTEGER PRIMARY KEY, {fk} INTEGER, created_at TEXT, status TEXT, "
                 "amount INTEGER, channel TEXT);\n" + insert(L, ["id", "name", "city"], left) + "\n"
                 + insert(R, ["id", fk, "created_at", "status", "amount", "channel"], right))
        code = _query(L, R, fk, flt, agg, False, sh)
        fixed = _query(L, R, fk, flt, agg, True, sh)
        ref = rows(setup, fixed)
        if rows(setup, code) != ref and len(ref.splitlines()) == len(names):
            break
    ch = changed_lines(code, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    what = "число записей" if agg == "count" else "сумму amount"
    stem = (f"Отчёт ({ctx}) должен показывать для каждого {gen} из `{L}` {what} в `{R}` {flt_txt}; если таких "
            f"записей нет — 0, но строка {gen} в отчёте есть. В отчёте пропадают строки. Укажите номер строки "
            "запроса с ошибкой.")
    checks = [Check(name="buggy_fails", runner="python", program=harness(setup, code, ref), expect="fail"),
              Check(name="fixed_passes", runner="python", program=harness(setup, fixed, ref), expect="pass",
                    embeds_display_code=False)]
    ak = AnswerKey(kind="line", value=key,
                   explanation=f"Строка {key}: условие на правую таблицу в WHERE отбрасывает строки, где справа NULL, "
                               "и LEFT JOIN работает как внутренний. Условие нужно перенести в ON (AND r.… в "
                               "условии соединения). COUNT(r.id) и COALESCE(SUM(…), 0) верны.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="outer_join_filter",
                         params={"fixed_code": fixed, "filter": flt, "agg": agg})
