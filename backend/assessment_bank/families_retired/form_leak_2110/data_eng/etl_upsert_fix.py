"""data_eng.etl.upsert_fix — choose_fix: загрузка изменений в целевую таблицу затирает created_at.

Ежедневная загрузка из staging в целевую таблицу сделана через `INSERT OR REPLACE`: при конфликте ключа SQLite
удаляет старую строку и вставляет новую, поэтому created_at существующих записей сбрасывается на дату
загрузки. Нужно: новые записи вставить, у существующих обновить изменяемые поля и updated_at, created_at
сохранить. Верно — `INSERT … SELECT … WHERE true ON CONFLICT(id) DO UPDATE SET` только изменяемых полей.
Дистракторы — фиксированный состав: `INSERT OR IGNORE` (существующие не обновляются), `UPDATE … FROM`
(новые не вставляются), upsert, который обновляет и created_at. Проверка — исполнение каждого варианта
в sqlite3 (обвязка на Python) и сверка всей целевой таблицы с эталоном.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._sqlh import insert

FAMILY_ID = "data_eng.etl.upsert_fix"

CTX = [("клиенты CRM", "customers", ["email", "city"]), ("товары каталога", "products", ["title", "price"]),
       ("сотрудники", "employees", ["position", "department"]), ("договоры", "contracts", ["status", "amount"])]

HARNESS = '''import sqlite3

con = sqlite3.connect(":memory:")
con.executescript({setup!r})
con.executescript(r"""
{sql}
""")
got = con.execute("SELECT * FROM {t} ORDER BY id").fetchall()
print("RESULT: PASS" if got == {expected!r} else "RESULT: FAIL")
'''


def _sqls(t, cols):
    c1, c2 = cols
    ins = f"INSERT INTO {t} (id, {c1}, {c2}, created_at, updated_at)"
    sel = f"SELECT id, {c1}, {c2}, loaded_at, loaded_at FROM staging_{t}"
    return {
        "replace": f"INSERT OR REPLACE INTO {t} (id, {c1}, {c2}, created_at, updated_at)\n{sel};",
        "upsert": f"{ins}\n{sel}\nWHERE true\nON CONFLICT(id) DO UPDATE SET\n  {c1} = excluded.{c1},\n"
                  f"  {c2} = excluded.{c2},\n  updated_at = excluded.updated_at;",
        "ignore": f"INSERT OR IGNORE INTO {t} (id, {c1}, {c2}, created_at, updated_at)\n{sel};",
        "update_from": f"UPDATE {t}\nSET {c1} = s.{c1}, {c2} = s.{c2}, updated_at = s.loaded_at\n"
                       f"FROM staging_{t} AS s\nWHERE {t}.id = s.id;",
        "upsert_all": f"{ins}\n{sel}\nWHERE true\nON CONFLICT(id) DO UPDATE SET\n  {c1} = excluded.{c1},\n"
                      f"  {c2} = excluded.{c2},\n  created_at = excluded.created_at,\n"
                      "  updated_at = excluded.updated_at;",
    }


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, t, cols = rng.choice(CTX)
    c1, c2 = cols
    load = rng.choice(["2026-10-09", "2026-10-10", "2026-10-11"])
    vals = {"email": lambda i: f"user{i}@mail.example", "city": lambda i: rng.choice(["Омск", "Тула", "Сочи"]),
            "title": lambda i: f"товар {i}", "price": lambda i: rng.choice([990, 1490, 2990]),
            "position": lambda i: rng.choice(["аналитик", "инженер", "менеджер"]),
            "department": lambda i: rng.choice(["ИТ", "продажи", "финансы"]),
            "status": lambda i: rng.choice(["active", "paused", "closed"]),
            "amount": lambda i: rng.choice([10000, 25000, 70000])}
    n_old = rng.randint(3, 5)
    target = [(i, vals[c1](i), vals[c2](i), f"2026-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}", "2026-10-01")
              for i in range(1, n_old + 1)]
    upd_ids = sorted(rng.sample(range(1, n_old + 1), 2))
    new_ids = list(range(n_old + 1, n_old + 1 + rng.randint(1, 2)))
    staging = [(i, vals[c1](i + 7), vals[c2](i + 7), load) for i in upd_ids + new_ids]
    setup = (f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, {c1}, {c2}, created_at TEXT, updated_at TEXT);\n"
             f"CREATE TABLE staging_{t} (id INTEGER PRIMARY KEY, {c1}, {c2}, loaded_at TEXT);\n"
             + insert(t, ["id", c1, c2, "created_at", "updated_at"], target) + "\n"
             + insert(f"staging_{t}", ["id", c1, c2, "loaded_at"], staging))
    exp = {r[0]: r for r in target}
    for i, a, b, ld in staging:
        exp[i] = (i, a, b, exp[i][3] if i in exp else ld, ld)
    expected = [exp[k] for k in sorted(exp)]
    S = _sqls(t, cols)
    code = S["replace"]
    texts = {"upsert": "Заменить на upsert с обновлением изменяемых полей:",
             "ignore": "Заменить на INSERT OR IGNORE:", "update_from": "Заменить на UPDATE … FROM staging:",
             "upsert_all": "Заменить на upsert с обновлением всех полей из staging:"}
    opts, key = make_options(rng, (texts["upsert"], S["upsert"]),
                             [(texts[k], S[k]) for k in ("ignore", "update_from", "upsert_all")])
    by_code = {S[k]: k for k in texts}
    checks = [Check(name=f"option:{o.id}", runner="python",
                    program=HARNESS.format(setup=setup, sql=o.code, t=t, expected=expected),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False) for o in opts]
    checks.append(Check(name="original_fails", runner="python",
                        program=HARNESS.format(setup=setup, sql=code, t=t, expected=expected), expect="fail"))
    _ = by_code
    t_tbl = "\n".join(" | ".join(map(str, r)) for r in target)
    s_tbl = "\n".join(" | ".join(map(str, r)) for r in staging)
    stem = (f"Ежедневная загрузка ({ctx}) переносит изменения из `staging_{t}` в `{t}` (SQLite). Требование: новые "
            f"записи вставить, у существующих обновить `{c1}`, `{c2}` и `updated_at`, а `created_at` сохранить. "
            "После перехода на запрос ниже аналитики заметили, что `created_at` старых записей стал равен дате "
            f"загрузки. Пример: до загрузки `{t}` (id | {c1} | {c2} | created_at | updated_at):\n{t_tbl}\n"
            f"`staging_{t}` (id | {c1} | {c2} | loaded_at):\n{s_tbl}\nКакое исправление верное?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="INSERT OR REPLACE при конфликте удаляет строку и вставляет новую — created_at "
                               "теряется. ON CONFLICT(id) DO UPDATE обновляет только перечисленные поля. OR IGNORE не "
                               "обновляет существующие, UPDATE … FROM не вставляет новые, upsert с created_at = "
                               "excluded.created_at снова затирает дату создания.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="sql",
                         params={"n_old": n_old, "load": load})
