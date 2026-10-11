"""data_eng.dq.uniqueness_check_bug — find_bug: проверка уникальности по части составного ключа.

Проверка качества данных ищет дубли строк по зерну таблицы, а зерно составное (например, заказ и номер
позиции). Ключ в проверке собран не из всех столбцов зерна — разные позиции одного заказа считаются дублями.
Ловушки-«не ошибки»: нормализация строк (strip/lower) и подсчёт через Counter верны. Исправление — кортеж из
всех столбцов зерна в той же строке. Проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.dq.uniqueness_check_bug"

CTX = [("позиции заказов", ["order_id", "line_no"], "sku"), ("остатки по складам за день", ["warehouse", "sku", "day"], "qty"),
       ("показы рекламы", ["campaign_id", "day"], "views"), ("оценки студентов", ["student_id", "course", "term"], "grade"),
       ("тарифы по регионам", ["region", "tariff"], "price"), ("курсы валют за день", ["currency", "day"], "rate"),
       ("смены сотрудников", ["employee_id", "day", "shift"], "hours")]
FN = ["duplicate_keys", "find_duplicates", "check_unique", "grain_violations"]
VALS = {"order_id": [101, 102, 103, 104], "line_no": [1, 2, 3], "warehouse": ["msk", "spb", "kzn"],
        "sku": ["A1", "B2", "C3", "D4"], "day": ["2026-10-07", "2026-10-08", "2026-10-09"], "campaign_id": [7, 8, 9],
        "student_id": [11, 12, 13], "course": ["sql", "etl", "dwh"], "term": ["autumn", "spring"],
        "region": ["north", "south", "west"], "tariff": ["base", "pro", "max"], "currency": ["USD", "EUR", "CNY"],
        "employee_id": [21, 22, 23], "shift": ["day", "night"]}


def _code(fn, grain, fixed, norm, drop, doc):
    cols = grain if fixed else [c for c in grain if c != drop]
    parts = ", ".join(f'norm(r["{c}"])' if norm else f'r["{c}"]' for c in cols)
    key_line = f"        key = ({parts},)" if len(cols) == 1 else f"        key = ({parts})"
    lines = ["from collections import Counter", ""]
    if norm:
        lines += ["", "def norm(v):", "    return str(v).strip().lower()", ""]
    lines += ["", f"def {fn}(rows):"]
    if doc:
        lines += ['    """Ключи зерна, которые встречаются больше одного раза."""']
    lines += ["    counts = Counter()", "    for r in rows:", key_line,
              "        counts[key] += 1", "    return sorted(k for k, n in counts.items() if n > 1)"]
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, grain, extra = rng.choice(CTX)
    fn = rng.choice(FN)
    norm = rng.random() < 0.5
    doc = rng.random() < 0.5
    drop = rng.choice(grain)
    code = _code(fn, grain, False, norm, drop, doc)
    fixed = _code(fn, grain, True, norm, drop, doc)
    ch = changed_lines(code, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    n_rows = rng.randint(4, 5)
    while True:
        rows, seen = [], set()
        while len(rows) < n_rows:
            r = {c: rng.choice(VALS[c]) for c in grain}
            t = tuple(r[c] for c in grain)
            if t in seen:
                continue
            seen.add(t)
            r[extra] = rng.randint(1, 50)
            rows.append(r)
        i_dup, i_near = rng.sample(range(n_rows), 2)
        free = [v for v in VALS[drop] if tuple(rows[i_near][c] if c != drop else v for c in grain) not in seen]
        if free:
            break
    dup = dict(rows[i_dup])
    dup[extra] = rng.randint(51, 99)
    near = dict(rows[i_near])
    near[drop] = rng.choice(free)
    near[extra] = rng.randint(1, 50)
    rows.insert(rng.randint(0, len(rows)), dup)  # ровно один настоящий дубль по зерну
    rows.insert(rng.randint(0, len(rows)), near)  # отличается только столбцом drop — не дубль
    exp = sorted([tuple((str(dup[c]).strip().lower() if norm else dup[c]) for c in grain)])
    test = (f"\n\n\nROWS = {rows!r}\nres = {fn}(ROWS)\n"
            f"print(\"RESULT: PASS\" if res == {exp!r} else \"RESULT: FAIL\")\n")
    checks = [Check(name="buggy_fails", runner="python", program=code + test, expect="fail"),
              Check(name="fixed_passes", runner="python", program=fixed + test, expect="pass",
                    embeds_display_code=False)]
    cols = grain + [extra]
    tbl = "\n".join(" | ".join(str(r[c]) for c in cols) for r in rows)
    stem = (f"Проверка качества данных для таблицы «{ctx}» должна находить дубли по зерну таблицы — "
            f"({', '.join(grain)}). На выгрузке ниже ровно один настоящий дубль, а проверка сообщает о нескольких.\n"
            f"Выгрузка ({' | '.join(cols)}):\n{tbl}\nУкажите номер строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key,
                   explanation=f"Строка {key}: ключ собран без столбца `{drop}`, поэтому строки, различающиеся только "
                               f"им, считаются дублями." + (" Нормализация значений и Counter верны." if norm
                                                            else " Подсчёт через Counter верен."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="partial_composite_key",
                         params={"fixed_code": fixed, "drop": drop, "norm": norm, "doc": doc})
