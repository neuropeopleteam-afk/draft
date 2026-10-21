"""analyst.sql.t21_case_segment_output — predict_output (набор t21, порог Стажёра): CASE WHEN с двумя порогами —
сегмент каждой строки.

Таблица (клиенты, пользователи, обращения, продавцы, сделки) и запрос `SELECT id, CASE WHEN … THEN … WHEN … THEN …
ELSE … END`. Ловушки чтения: срабатывает первая подходящая ветка WHEN (в части вариантов ветки стоят «не в том»
порядке, и одна метка не встречается вовсе), значения ровно на пороге. Ключ — независимый расчёт в генераторе;
проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_case_segment_output"

# (таблица, сюжет, колонка, оператор, метки (строгий порог, мягкий порог, иначе), сетка, имя столбца сегмента)
CTX = [
    ("clients", "Клиенты магазина: сумма покупок за год", "spent", ">=", ("vip", "regular", "new"),
     list(range(500, 20001, 500)), "segment"),
    ("users", "Пользователи приложения: сессии за неделю", "sessions", ">=", ("core", "casual", "sleeping"),
     list(range(0, 31)), "activity"),
    ("tickets", "Обращения в поддержку: минуты до первого ответа", "wait_min", "<=", ("fast", "normal", "slow"),
     list(range(1, 61)), "speed"),
    ("sellers", "Продавцы маркетплейса: доля возвратов в процентах", "returns_pct", "<=", ("good", "watch", "risk"),
     list(range(0, 31)), "status"),
    ("deals", "Сделки отдела продаж: скидка в процентах", "discount_pct", "<=", ("standard", "approval", "director"),
     list(range(0, 41)), "route"),
]


def _cmp(op, v, t):
    return v >= t if op == ">=" else v <= t


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, col, op, labels, grid, alias = rng.choice(CTX)
    reverse = rng.random() < 0.4
    for _ in range(500):
        i1, i2 = sorted(rng.sample(range(2, len(grid) - 2), 2))
        if i2 - i1 < 3:
            continue
        if op == ">=":
            t_strict, t_soft = grid[i2], grid[i1]     # v >= t_strict — первая метка
        else:
            t_strict, t_soft = grid[i1], grid[i2]     # v <= t_strict — первая метка
        whens = [(t_strict, labels[0]), (t_soft, labels[1])]
        if reverse:
            whens.reverse()
        n = rng.randint(5, 6)
        rid = rng.randint(1, 20)
        rows = []
        vals = [t_strict, t_soft] + [grid[rng.randrange(len(grid))] for _k in range(n - 2)]
        rng.shuffle(vals)
        for v in vals:
            rid += rng.randint(1, 3)
            rows.append((rid, v))

        def seg(v):
            for t, lab in whens:
                if _cmp(op, v, t):
                    return lab
            return labels[2]
        res = [(r[0], seg(r[1])) for r in rows]
        strict_rows = [r for r in rows if _cmp(op, r[1], t_strict) and r[1] != t_strict]
        mid_rows = [r for r in rows if _cmp(op, r[1], t_soft) and not _cmp(op, r[1], t_strict)]
        else_rows = [r for r in rows if not _cmp(op, r[1], t_soft)]
        if strict_rows and mid_rows and else_rows and len({r[1] for r in rows}) == len(rows):
            break
    else:
        raise RuntimeError("t21_case_segment: не собрались данные")
    w = [f"WHEN {col} {op} {t} THEN '{lab}'" for t, lab in whens]
    code = (f"SELECT id,\n"
            f"       CASE {w[0]}\n"
            f"            {w[1]}\n"
            f"            ELSE '{labels[2]}' END AS {alias}\n"
            f"FROM {T}\n"
            f"ORDER BY id;")
    out = "\n".join(f"{i}|{s}" for i, s in res)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {col} INTEGER NOT NULL);\n"
             + sql_inserts(T, ["id", col], rows) + "\n")
    stem = f"{plot}. Запрос присваивает каждой строке метку {alias}.\n\n{T}\n{text_table(['id', col], rows)}"
    if reverse:
        trap = (f"CASE берёт первую подходящую ветку: условие {col} {op} {whens[0][0]} проверяется первым и забирает "
                f"все строки, которые подошли бы и под {col} {op} {whens[1][0]}, — метка '{labels[0]}' не "
                f"достаётся никому")
    else:
        trap = (f"CASE берёт первую подходящую ветку: сначала {col} {op} {t_strict} → '{labels[0]}', иначе "
                f"{col} {op} {t_soft} → '{labels[1]}', иначе '{labels[2]}'; значение ровно на пороге "
                f"подходит (сравнение нестрогое)")
    expl = f"{trap}. По строкам: " + "; ".join(f"id {r[0]} ({col} = {r[1]}) → {s}" for r, (_i, s) in
                                                 zip(rows, res)) + "."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "whens": whens, "reverse": reverse}, language="sql",
                          files={"setup.sql": setup})
