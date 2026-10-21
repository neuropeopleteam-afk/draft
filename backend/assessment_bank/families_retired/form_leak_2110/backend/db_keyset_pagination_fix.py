"""backend.db.keyset_pagination_fix — choose_fix: курсорная (keyset) пагинация с одинаковыми метками времени.

Курсор — (created_at, id) последней строки, сортировка ORDER BY created_at, id. Условие
`created_at > ?` теряет строки с той же меткой времени, что у последней строки страницы.
Верно — сравнение пар `(created_at, id) > (?, ?)` (row values, SQLite ≥ 3.15). Дистракторы:
`>=` (повторы и зацикливание на группе одинаковых меток), `created_at >= ? AND id > ?`
и `id > ?` (id не монотонен по времени), пара в обратном порядке `(id, created_at)`.
Данные подбираются так, чтобы каждый показанный вариант ошибался; эталон — модель на Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, dedent, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.db.keyset_pagination_fix"

CONTEXTS = [("events", "журнал событий", "next_events"), ("orders", "ленту заказов", "orders_page"),
            ("messages", "историю чата", "load_messages"),
            ("transactions", "выписку по счёту", "statement_page"),
            ("audit_log", "журнал аудита", "audit_page")]

WHERE = {"buggy": ("created_at > ?", "after[0], limit"),
         "good": ("(created_at, id) > (?, ?)", "after[0], after[1], limit"),
         "ge": ("created_at >= ?", "after[0], limit"),
         "and_ids": ("created_at >= ? AND id > ?", "after[0], after[1], limit"),
         "id_only": ("id > ?", "after[1], limit"),
         "swapped": ("(id, created_at) > (?, ?)", "after[1], after[0], limit")}


def _code(kind: str, table: str, fn: str) -> str:
    cond, params = WHERE[kind]
    return dedent(f'''
        def {fn}(con, after, limit):
            """Страница по курсору after = (created_at, id) последней строки или None."""
            if after is None:
                sql, args = "SELECT id, created_at FROM {table} ORDER BY created_at, id LIMIT ?", (limit,)
            else:
                sql = "SELECT id, created_at FROM {table} WHERE {cond} ORDER BY created_at, id LIMIT ?"
                args = ({params})
            rows = con.execute(sql, args).fetchall()
            return rows, ((rows[-1][1], rows[-1][0]) if rows else None)''')


def _sim(kind: str, rows: list[tuple[int, str]], limit: int) -> list[int] | None:
    """Модель выдачи по страницам; None — зацикливание (больше 40 страниц)."""
    ordered = sorted(rows, key=lambda r: (r[1], r[0]))
    pred = {"buggy": lambda r, a: r[1] > a[0],
            "good": lambda r, a: (r[1], r[0]) > (a[0], a[1]),
            "ge": lambda r, a: r[1] >= a[0],
            "and_ids": lambda r, a: r[1] >= a[0] and r[0] > a[1],
            "id_only": lambda r, a: r[0] > a[1],
            "swapped": lambda r, a: (r[0], r[1]) > (a[1], a[0])}[kind]
    out, after = [], None
    for _ in range(40):
        page = ordered[:limit] if after is None else [r for r in ordered if pred(r, after)][:limit]
        if not page:
            return out
        out += [r[0] for r in page]
        after = (page[-1][1], page[-1][0])
    return None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    table, ctx, fn = rng.choice(CONTEXTS)
    chosen = rng.sample(["ge", "and_ids", "id_only", "swapped"], 3)
    for _ in range(2000):
        day = rng.randint(1, 28)
        times = sorted(rng.sample(range(8 * 60, 20 * 60, 5), rng.randint(4, 6)))
        stamps = [f"2026-09-{day:02d} {t // 60:02d}:{t % 60:02d}" for t in times]
        groups = [rng.randint(1, 3) for _ in stamps]
        n = sum(groups)
        ids = rng.sample(range(1, 80), n)
        rows, k = [], 0
        for ts, g in zip(stamps, groups):
            for _ in range(g):
                rows.append((ids[k], ts))
                k += 1
        limit = rng.randint(2, 4)
        good = _sim("good", rows, limit)
        if good != [r[0] for r in sorted(rows, key=lambda r: (r[1], r[0]))]:
            continue
        if all(_sim(kd, rows, limit) != good for kd in chosen + ["buggy"]):
            break
    else:
        raise RuntimeError("не подобраны данные")
    expected = good
    shuffled = rows[:]
    rng.shuffle(shuffled)
    tests = dedent(f"""
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE {table} (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL)")
        con.executemany("INSERT INTO {table} VALUES (?, ?)", {shuffled!r})
        seen, after = [], None
        for _ in range(40):
            rows, after = {fn}(con, after, {limit})
            if not rows:
                break
            seen += [r[0] for r in rows]
        assert seen == {expected!r}, seen
        """)
    code = _code("buggy", table, fn)
    opts, key = make_options(rng, ("Заменить функцию на:", _code("good", table, fn)),
                             [("Заменить функцию на:", _code(k, table, fn)) for k in chosen])
    checks = [Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False)
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, tests),
                        expect="fail"))
    lost = [i for i in expected if i not in (_sim("buggy", rows, limit) or [])]
    stem = (f"API отдаёт {ctx} (таблица `{table}`) страницами по {limit} строки с курсором вместо "
            f"OFFSET. Порядок выдачи — по `created_at`, при равенстве — по `id`; `id` не "
            f"монотонен по времени (часть записей импортирована задним числом), и у нескольких "
            f"записей одинаковое `created_at`. При обходе всех страниц клиент не получает записи "
            f"с id {', '.join(map(str, lost))}. Какое исправление гарантирует, что обход всех "
            f"страниц выдаст каждую запись ровно один раз в требуемом порядке?")
    why = {"ge": "`>=` повторяет строки с меткой курсора, а на группе одинаковых меток больше "
                 "страницы курсор не сдвигается — обход зацикливается",
           "and_ids": "`created_at >= ? AND id > ?` теряет более поздние записи с меньшим id",
           "id_only": "`id > ?` не согласован с сортировкой по времени: id не монотонен",
           "swapped": "пара (id, created_at) сравнивает сначала id, а сортировка идёт по времени"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: условие на пару `(created_at, id) > (?, ?)` совпадает с "
                               "порядком сортировки ORDER BY created_at, id (эквивалент — "
                               "`created_at > ? OR (created_at = ? AND id > ?)`); нужен индекс "
                               "(created_at, id). Дистракторы: " + "; ".join(why[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="keyset_tiebreak",
                         params={"distractors": chosen, "limit": limit, "rows": rows})
