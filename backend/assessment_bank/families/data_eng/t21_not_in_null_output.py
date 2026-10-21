"""data_eng.etl.t21_not_in_null_output — predict_output (набор t21, порог Senior): поиск новых ключей для
загрузки — NOT IN против NOT EXISTS при NULL в целевой и в промежуточной таблице.

Запрос помечает «новые» строки staging двумя способами (значение условия в SELECT: 1 / 0 / NULL).
`x NOT IN (подзапрос)` при NULL в подзапросе никогда не даёт TRUE (сравнение с NULL — UNKNOWN), а NULL в самом x
тоже даёт UNKNOWN; NOT EXISTS с равенством пропускает NULL-ключ как «нет пары». NULL есть в каждом варианте:
в target, в staging или в обеих таблицах.
Ключ — независимая трёхзначная логика в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.etl.t21_not_in_null_output"

CTX = [("заказы из учётной системы", "ext_order_id"), ("клиенты из CRM-выгрузки", "ext_client_id"),
       ("товары от поставщиков", "supplier_sku"), ("устройства из реестра", "device_code"),
       ("договоры из архива", "contract_no")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, col = rng.choice(CTX)
    # NULL есть всегда — в target, в staging или в обеих таблицах
    t_null, s_null = rng.choice([(True, False), (True, False), (False, True), (True, True), (True, True)])
    for _ in range(500):
        pool = rng.sample(range(100, 160), 9)
        n_t = rng.randint(3, 4)
        t_keys = pool[:n_t]
        n_match = rng.randint(1, 2)
        n_new = rng.randint(1, 2)
        s_keys = rng.sample(t_keys, n_match) + pool[n_t:n_t + n_new]
        target = list(t_keys) + ([None] if t_null else [])
        staging = list(s_keys) + ([None] if s_null else [])
        rng.shuffle(target)
        rng.shuffle(staging)
        if len(staging) >= 3:
            break
    t_set = [k for k in target if k is not None]

    def not_in(k):  # трёхзначная логика: 1 / 0 / NULL
        if k is None:
            return None
        if k in t_set:
            return 0
        return None if t_null else 1

    res = [(i + 1, not_in(k), 1 if (k is None or k not in t_set) else 0) for i, k in enumerate(staging)]
    t_rows = [(i + 1, k) for i, k in enumerate(target)]
    s_rows = [(i + 1, k) for i, k in enumerate(staging)]
    code = ("SELECT\n"
            "  s.id,\n"
            f"  s.{col} NOT IN (SELECT {col} FROM target) AS by_not_in,\n"
            "  NOT EXISTS (\n"
            f"    SELECT 1 FROM target t WHERE t.{col} = s.{col}\n"
            "  ) AS by_not_exists\n"
            "FROM staging s\n"
            "ORDER BY s.id;")
    setup = (f"CREATE TABLE target (id INTEGER PRIMARY KEY, {col} INTEGER);\n"
             f"CREATE TABLE staging (id INTEGER PRIMARY KEY, {col} INTEGER);\n"
             + sql_inserts("target", ["id", col], t_rows) + "\n" + sql_inserts("staging", ["id", col], s_rows) + "\n")
    fmt = lambda v: "NULL" if v is None else str(v)
    out = "\n".join(f"{i}|{fmt(a)}|{b}" for i, a, b in res)
    parts = []
    if t_null:
        parts.append("в target есть NULL: для ключа, которого нет среди значений, k NOT IN (…, NULL) — это "
                     "k <> … AND k <> NULL, то есть UNKNOWN (NULL), а для найденного ключа — 0")
    else:
        parts.append("в target нет NULL: NOT IN даёт 1 для отсутствующего ключа и 0 для найденного")
    if s_null:
        parts.append("строка staging с NULL-ключом в NOT IN даёт NULL, а в NOT EXISTS — 1: равенство с NULL никогда "
                     "не TRUE, пары нет")
    parts.append("NOT EXISTS всегда двузначен: 1 — пары нет, 0 — есть")
    expl = "; ".join(parts)
    expl = expl[0].upper() + expl[1:] + ". Итог: " + "; ".join(f"{i}|{fmt(a)}|{b}" for i, a, b in res) + "."
    stem = (f"Инкрементальная загрузка ({ctx}): запрос двумя способами помечает строки staging, ключа которых ещё нет "
            f"в target.\n\ntarget\n{text_table(['id', col], t_rows)}\n\nstaging\n{text_table(['id', col], s_rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"target_null": t_null, "staging_null": s_null}, language="sql",
                          files={"setup.sql": setup})
