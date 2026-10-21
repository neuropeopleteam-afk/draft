"""data_eng.etl.partition_overwrite_fix — choose_fix: идемпотентный перезапуск дневной загрузки.

Дневная загрузка дописывает строки дня в таблицу фактов; перезапуск после частичного сбоя удваивает день.
Нужно: перезапуск за день D даёт ровно строки дня из источника, другие дни не трогаются, а сбой при
перезапуске оставляет таблицу как была (без «пустого» дня). Верно — удалить партицию дня и вставить заново
в одной транзакции. Дистракторы — фиксированный состав: те же DELETE и INSERT без транзакции (сбой оставляет
день пустым), «вставить, только если дня ещё нет» (частичный день остаётся частичным), INSERT OR IGNORE
(ключа нет — дубли остаются). Проверка — исполнение каждого варианта в sqlite3 (обвязка на Python) на двух
сценариях: успешный перезапуск после частичной загрузки и перезапуск со сбоем на середине.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert

FAMILY_ID = "data_eng.etl.partition_overwrite_fix"

CTX = [("продажи магазинов", "fact_sales", "raw_sales", "store_id"),
       ("поездки такси", "fact_trips", "raw_trips", "driver_id"),
       ("показы рекламы", "fact_impressions", "raw_impressions", "campaign_id"),
       ("звонки колл-центра", "fact_calls", "raw_calls", "operator_id")]

HARNESS = '''import sqlite3

def run(setup):
    con = sqlite3.connect(":memory:")
    con.executescript(setup)
    try:
        con.executescript(r"""
{sql}
""")
    except sqlite3.Error:
        con.rollback()
    return con.execute("SELECT day, {k}, amount FROM {f} ORDER BY day, {k}, amount").fetchall()

ok = run({setup_ok!r}) == {exp_ok!r} and run({setup_fail!r}) == {exp_fail!r}
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''


def _sqls(f, r, k, d):
    cols = f"day, {k}, amount"
    ins = f"INSERT INTO {f} ({cols})\nSELECT {cols} FROM {r} WHERE day = '{d}';"
    return {
        "orig": ins,
        "tx": f"BEGIN;\nDELETE FROM {f} WHERE day = '{d}';\n{ins}\nCOMMIT;",
        "no_tx": f"DELETE FROM {f} WHERE day = '{d}';\n{ins}",
        "skip": (f"INSERT INTO {f} ({cols})\nSELECT {cols} FROM {r} WHERE day = '{d}'\n"
                 f"  AND NOT EXISTS (SELECT 1 FROM {f} WHERE day = '{d}');"),
        "ignore": ins.replace("INSERT INTO", "INSERT OR IGNORE INTO"),
    }


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, f, r, k = rng.choice(CTX)
    day = rng.choice(["2026-10-03", "2026-10-05", "2026-10-07", "2026-10-08", "2026-10-09"])
    prev = day[:-1] + str(int(day[-1]) - 1)
    src = [(day, rng.randint(1, 9), rng.choice([120, 340, 560, 780, 910])) for _ in range(rng.randint(4, 6))]
    old_prev = [(prev, rng.randint(1, 9), rng.choice([100, 200, 300])) for _ in range(rng.randint(2, 3))]
    partial = src[: rng.randint(1, len(src) - 2)]
    schema = (f"CREATE TABLE {f} (id INTEGER PRIMARY KEY, day TEXT NOT NULL, {k} INTEGER NOT NULL, "
              "amount INTEGER NOT NULL);\n"
              f"CREATE TABLE {r} (day TEXT, {k} INTEGER, amount INTEGER);\n")
    cols = ["day", k, "amount"]
    base = schema + insert(f, cols, old_prev + partial) + "\n"
    setup_ok = base + insert(r, cols, src)
    bad = src[:2] + [(day, rng.randint(1, 9), None)] + src[2:]  # строка без суммы — вставка падает на середине
    setup_fail = base + insert(r, cols, bad)
    norm = lambda rows: sorted(rows)  # noqa: E731
    exp_ok = norm(old_prev + src)
    exp_fail = norm(old_prev + partial)
    S = _sqls(f, r, k, day)
    texts = {"tx": "Удалить строки дня и вставить заново в одной транзакции:",
             "no_tx": "Перед вставкой удалить строки дня:",
             "skip": "Вставлять, только если строк за день ещё нет:",
             "ignore": "Заменить INSERT на INSERT OR IGNORE:"}
    opts, key = make_options(rng, (texts["tx"], S["tx"]), [(texts[x], S[x]) for x in ("no_tx", "skip", "ignore")])

    def prog(sql):
        return HARNESS.format(sql=sql, k=k, f=f, setup_ok=setup_ok, exp_ok=exp_ok, setup_fail=setup_fail,
                              exp_fail=exp_fail)
    checks = [Check(name=f"option:{o.id}", runner="python", program=prog(o.code),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False) for o in opts]
    fmt = lambda rows: "; ".join(f"{a} | {b}" for _, a, b in rows)  # noqa: E731
    checks.append(Check(name="original_fails", runner="python", program=prog(S["orig"]), expect="fail"))
    stem = (f"Дневная загрузка ({ctx}) за {day} упала на середине, часть строк дня уже попала в `{f}`. После "
            f"перезапуска сумма за {day} оказалась завышенной. Нужно: перезапуск за день даёт ровно строки дня из "
            f"`{r}`, другие дни не трогает, а если перезапуск тоже упадёт — `{f}` остаётся как была до него. Какое "
            f"исправление загрузки верное? Пример: в `{f}` за {day} уже есть ({k} | amount): {fmt(partial)}; в `{r}` "
            f"за {day}: {fmt(src)}; за {prev} в `{f}`: {fmt(old_prev)}.")
    ak = AnswerKey(kind="option", value=key,
                   explanation="Перезапуск должен перезаписывать партицию дня атомарно: DELETE дня и INSERT в одной "
                               "транзакции. Без транзакции сбой оставит день пустым; «вставить, если дня нет» "
                               "оставит частичный день; OR IGNORE без уникального ключа не убирает дубли.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=S["orig"], options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"day": day, "partial": len(partial)})
