"""data_eng.dwh.scd2_rerun_fix — choose_fix: повторный запуск загрузки SCD2 за ту же дату.

Измерение SCD2: версия [valid_from, valid_to), текущая — valid_to = '9999-12-31'. Скрипт загрузки за дату D:
UPDATE закрывает текущие версии ключей, у которых атрибут в staging изменился (valid_to = D); INSERT добавляет
версию для новых ключей и для ключей, «закрытых сегодня» (valid_to = D). При повторном запуске за ту же дату
(перезапуск упавшей задачи оркестратора) закрытые сегодня версии всё ещё есть — INSERT снова добавляет версию, у
ключа становится две текущие. Верно — вставлять, если у ключа нет текущей версии (`NOT EXISTS … valid_to =
'9999-12-31'`): это покрывает и новые, и только что закрытые ключи, а повторный запуск ничего не меняет.
Дистракторы — фиксированный состав: `SELECT DISTINCT` (повтор приходит из второго запуска, а не из соединения),
`INSERT OR IGNORE` (в таблице нет уникального ключа (ключ, valid_from) — игнорировать нечего), условие
`valid_from < D` в UPDATE (UPDATE и так ничего не закрывает при повторе — дубль даёт INSERT). Проверка —
исполнение каждого варианта ДВАЖДЫ в sqlite3 (обвязка на Python) и сверка всего измерения с эталоном.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert

FAMILY_ID = "data_eng.dwh.scd2_rerun_fix"

CTX = [("клиенты", "customer", "city", ["Москва", "Казань", "Самара", "Пермь", "Тверь", "Сочи"]),
       ("магазины", "store", "region", ["north", "south", "east", "west", "center"]),
       ("сотрудники", "employee", "department", ["sales", "support", "billing", "it", "hr"]),
       ("товары", "product", "category", ["food", "toys", "books", "tools", "garden"]),
       ("тарифы курьеров", "courier", "tariff", ["base", "pro", "night", "peak"]),
       ("договоры", "contract", "status", ["draft", "active", "paused", "closed"])]

HARNESS = '''import sqlite3

con = sqlite3.connect(":memory:")
con.executescript({setup!r})
LOAD = r"""
{sql}
"""
con.executescript(LOAD)
con.executescript(LOAD)  # повторный запуск за ту же дату
got = con.execute("SELECT {k}, {a}, valid_from, valid_to FROM dim_{e} ORDER BY {k}, valid_from").fetchall()
print("RESULT: PASS" if got == {expected!r} else "RESULT: FAIL")
'''


def _sql(e, k, a, d, fix=None):
    upd_extra = f"\n  AND valid_from < '{d}'" if fix == "upd_from" else ""
    head = "INSERT OR IGNORE INTO" if fix == "or_ignore" else "INSERT INTO"
    sel = "SELECT DISTINCT" if fix == "distinct" else "SELECT"
    if fix == "current":
        cond = (f"WHERE NOT EXISTS (SELECT 1 FROM dim_{e} d\n"
                f"                  WHERE d.{k} = s.{k} AND d.valid_to = '9999-12-31');")
    else:
        cond = (f"WHERE NOT EXISTS (SELECT 1 FROM dim_{e} d WHERE d.{k} = s.{k})\n"
                f"   OR EXISTS (SELECT 1 FROM dim_{e} d WHERE d.{k} = s.{k} AND d.valid_to = '{d}');")
    return (f"UPDATE dim_{e}\nSET valid_to = '{d}'\nWHERE valid_to = '9999-12-31'{upd_extra}\n"
            f"  AND EXISTS (SELECT 1 FROM stg_{e} s\n"
            f"              WHERE s.{k} = dim_{e}.{k} AND s.{a} <> dim_{e}.{a});\n"
            f"{head} dim_{e} ({k}, {a}, valid_from, valid_to)\n"
            f"{sel} s.{k}, s.{a}, '{d}', '9999-12-31'\nFROM stg_{e} s\n{cond}")


def _expected(dim, stg, d):
    cur = {r[0]: r for r in dim if r[3] == "9999-12-31"}
    out = []
    for r in dim:
        if r[3] == "9999-12-31" and r[0] in stg and stg[r[0]] != r[1]:
            out.append((r[0], r[1], r[2], d))
        else:
            out.append(r)
    for key, val in stg.items():
        if key not in cur or cur[key][1] != val:
            out.append((key, val, d, "9999-12-31"))
    return sorted(out, key=lambda r: (r[0], r[2]))


def _run(setup, sql, e, k, a):
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.executescript(setup)
    con.executescript(sql)
    con.executescript(sql)
    return con.execute(f"SELECT {k}, {a}, valid_from, valid_to FROM dim_{e} ORDER BY {k}, valid_from").fetchall()


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, e, a, values = rng.choice(CTX)
    k = f"{e}_id"
    for _ in range(500):
        d = f"2026-{rng.randint(3, 11):02d}-{rng.randint(1, 28):02d}"
        k0 = rng.randint(10, 800)
        keys = list(range(k0, k0 + rng.randint(3, 4)))
        dim = []
        for key in keys:
            if rng.random() < 0.4:  # у ключа есть закрытая история
                v_old, v_cur = rng.sample(values, 2)
                mid = f"2026-0{rng.randint(1, 2)}-{rng.randint(10, 28)}"
                dim += [(key, v_old, "2025-01-01", mid), (key, v_cur, mid, "9999-12-31")]
            else:
                dim.append((key, rng.choice(values), "2025-01-01", "9999-12-31"))
        cur = {r[0]: r[1] for r in dim if r[3] == "9999-12-31"}
        changed = rng.sample(keys, rng.randint(1, 2))
        stg = {}
        for key in keys:
            if key in changed:
                stg[key] = rng.choice([v for v in values if v != cur[key]])
            elif rng.random() < 0.6:
                stg[key] = cur[key]
        new_key = keys[-1] + rng.randint(1, 5)
        stg[new_key] = rng.choice(values)
        setup = (f"CREATE TABLE dim_{e} (sk INTEGER PRIMARY KEY, {k} INTEGER, {a} TEXT NOT NULL, valid_from TEXT, "
                 "valid_to TEXT);\n"
                 f"CREATE TABLE stg_{e} ({k} INTEGER PRIMARY KEY, {a} TEXT NOT NULL);\n"
                 + insert(f"dim_{e}", [k, a, "valid_from", "valid_to"], dim) + "\n"
                 + insert(f"stg_{e}", [k, a], sorted(stg.items())))
        expected = _expected(dim, stg, d)
        S = {f: _sql(e, k, a, d, f) for f in (None, "current", "distinct", "or_ignore", "upd_from")}
        ok = _run(setup, S["current"], e, k, a) == expected
        bad = all(_run(setup, S[f], e, k, a) != expected for f in (None, "distinct", "or_ignore", "upd_from"))
        if ok and bad:
            break
    code = S[None]
    texts = {"current": "Во втором условии INSERT вставлять, только если у ключа нет текущей версии:",
             "distinct": "Заменить SELECT на SELECT DISTINCT:",
             "or_ignore": "Заменить INSERT INTO на INSERT OR IGNORE INTO:",
             "upd_from": f"Добавить в UPDATE условие valid_from < '{d}':"}
    opts, key = make_options(rng, (texts["current"], S["current"]),
                             [(texts[f], S[f]) for f in ("distinct", "or_ignore", "upd_from")])
    checks = [Check(name=f"option:{o.id}", runner="python",
                    program=HARNESS.format(setup=setup, sql=o.code, e=e, k=k, a=a, expected=expected),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False) for o in opts]
    checks.append(Check(name="original_fails", runner="python",
                        program=HARNESS.format(setup=setup, sql=code, e=e, k=k, a=a, expected=expected),
                        expect="fail"))
    t_dim = "\n".join(" | ".join(map(str, r)) for r in dim)
    t_stg = "\n".join(f"{kk} | {vv}" for kk, vv in sorted(stg.items()))
    stem = (f"Измерение «{ctx}» ведётся как SCD2 (SQLite): версия действует на [valid_from, valid_to), текущая — "
            f"valid_to = '9999-12-31'. Ежедневная загрузка за {d} выполняет скрипт ниже. Задача оркестратора упала "
            "после скрипта и была перезапущена — скрипт выполнился ещё раз за ту же дату, и у изменившихся ключей "
            f"появилось по две текущие версии. Атрибут {a} не бывает NULL. До загрузки `dim_{e}` ({k} | {a} | valid_from | "
            f"valid_to; sk — суррогатный ключ):\n{t_dim}\n`stg_{e}` ({k} | {a}):\n{t_stg}\nКакое исправление делает загрузку "
            "идемпотентной (повторный запуск ничего не меняет) и сохраняет историю верной?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="После первого запуска закрытые сегодня версии остаются, и условие «valid_to = дата "
                               "загрузки» снова выбирает эти ключи. «Нет текущей версии» верно и для новых, и для "
                               "только что закрытых ключей, а при повторе ложно. DISTINCT не убирает повтор между "
                               "запусками; INSERT OR IGNORE без уникального ключа (ключ, valid_from) ничего не "
                               "игнорирует; условие в UPDATE не влияет — дубль добавляет INSERT.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="sql",
                         params={"date": d, "changed": changed, "new_key": new_key})
