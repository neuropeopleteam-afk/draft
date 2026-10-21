"""backend.db.t21_sql_group_having_output — predict_output (набор t21, порог Junior): WHERE + GROUP BY + HAVING
(SQLite).

Отчёт для дежурного: группы (эндпоинты / мерчанты / очереди), где «плохих» строк не меньше порога. Ловушки
(две конструкции вместе): WHERE отбрасывает строки до группировки, HAVING — группы после; группа с большим числом
строк, но малым числом «плохих» в отчёт не попадает; сортировка по счётчику по убыванию, при равенстве — по имени.
Ключ — независимая модель (подсчёт по данным) в генераторе; проверка — исполнение запроса в SQLite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "backend.db.t21_sql_group_having_output"

# (контекст, таблица, колонка группы, имена групп, колонка признака, значения признака, «плохие» значения, условие)
CTX = [("API заказов", "requests", "endpoint", ["/orders", "/cart", "/users", "/auth", "/search"], "status",
        [200, 200, 201, 404, 500, 502, 503], lambda v: v >= 500, "status >= 500", "ошибок 5xx"),
       ("шлюз оплаты", "payments", "merchant", ["coffee", "books", "sport", "pharma", "travel"], "result",
        ["ok", "ok", "ok", "declined", "declined", "timeout"], lambda v: v == "declined", "result = 'declined'",
        "отказов"),
       ("фоновые задачи", "jobs", "queue", ["emails", "exports", "thumbs", "billing", "search"], "attempts",
        [1, 1, 1, 2, 3, 4], lambda v: v > 1, "attempts > 1", "повторов")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, gcol, gnames, fcol, fvals, bad, cond, what = rng.choice(CTX)
    thr = rng.choice([2, 2, 3])
    for _ in range(500):
        groups = rng.sample(gnames, 4)
        n = rng.randint(9, 11)
        rows = [(i + 1, rng.choice(groups), rng.choice(fvals)) for i in range(n)]
        cnt = {g: sum(1 for r in rows if r[1] == g and bad(r[2])) for g in groups}
        tot = {g: sum(1 for r in rows if r[1] == g) for g in groups}
        passed = [g for g in groups if cnt[g] >= thr]
        below = [g for g in groups if 0 < cnt[g] < thr]
        busy_not_passed = [g for g in groups if tot[g] >= thr and cnt[g] < thr]
        if passed and below and busy_not_passed and len(passed) <= 3 and min(tot.values()) >= 1:
            break
    else:
        raise RuntimeError("t21_group_having: не собраны данные")
    alias = rng.choice(["bad", "cnt", "n"])
    query = (f"SELECT {gcol}, COUNT(*) AS {alias}\nFROM {table}\nWHERE {cond}\nGROUP BY {gcol}\n"
             f"HAVING COUNT(*) >= {thr}\nORDER BY {alias} DESC, {gcol};")
    lit = (lambda v: f"{v}") if isinstance(fvals[0], int) else (lambda v: v)
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {gcol} TEXT NOT NULL, "
             f"{fcol} {'INTEGER' if isinstance(fvals[0], int) else 'TEXT'} NOT NULL);\n"
             + sql_inserts(table, ["id", gcol, fcol], rows) + "\n")
    res = sorted(passed, key=lambda g: (-cnt[g], g))
    out = "\n".join(f"{g}|{cnt[g]}" for g in res)
    expl = (f"WHERE {cond} оставляет до группировки только строки с признаком; по группам: "
            + ", ".join(f"{g} — {cnt[g]} из {tot[g]}" for g in sorted(groups))
            + f". HAVING COUNT(*) >= {thr} отбрасывает группы с меньшим числом {what}, даже если всего строк у них "
            + f"не меньше {thr} (" + ", ".join(sorted(busy_not_passed)) + "). Порядок — по счётчику по убыванию, "
            + "при равенстве по имени: "
            + "; ".join(f"{g}|{cnt[g]}" for g in res) + ".")
    _ = lit
    stem = (f"Сервис «{ctx}»: отчёт для дежурного показывает, где за последний час набралось не меньше {thr} "
            f"{what}. Таблица `{table}`:\n\n{table}\n{text_table(['id', gcol, fcol], rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=query, out=out, explanation=expl, context=ctx,
                          params={"thr": thr, "groups": groups}, language="sql", files={"setup.sql": setup})
