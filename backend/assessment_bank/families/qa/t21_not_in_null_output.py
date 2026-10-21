"""qa.sql.t21_not_in_null_output — predict_output (набор t21, порог Senior): сверка двух выгрузок — COUNT(*)
против COUNT(col) и NOT IN против NOT EXISTS при NULL в ключах.

Отчёт сверки — один запрос из трёх строк (UNION ALL, ORDER BY 1): для каждой выгрузки — число строк COUNT(*) и
число заполненных ключей COUNT(key); третья строка — сколько ключей первой выгрузки не нашлось во второй, двумя
способами. Ловушки: COUNT(key) не считает NULL; `key NOT IN (SELECT key FROM вторая)` при NULL в подзапросе ни для
одной строки не TRUE (сравнение с NULL — UNKNOWN) — 0 строк, а строка с NULL-ключом в первой выгрузке не проходит
NOT IN даже без NULL в подзапросе; NOT EXISTS с равенством считает и её (пары для NULL нет). Отличие от
analyst.sql.t21_not_in_null_output (IN / NOT IN / NOT EXISTS по справочнику с фильтром статуса) и
data_eng.etl.t21_not_in_null_output (флаги 1/0/NULL по строкам staging): здесь сводка сверки с COUNT(*) /
COUNT(col) по обеим выгрузкам и NULL с обеих сторон. Ключ — независимая трёхзначная логика в генераторе; проверка —
исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "qa.sql.t21_not_in_null_output"

# (сюжет, первая выгрузка, вторая выгрузка, ключ, диапазон ключей)
CTX = [("Сверка результатов автотестов, отправленных в отчёт и загруженных в хранилище", "sent", "loaded",
         "run_id", (100, 140)),
       ("Сверка тест-кейсов между системой управления тестами и репозиторием", "tms", "repo", "case_id", (10, 60)),
       ("Сверка заказов тестового стенда с выгрузкой в аналитику", "stand", "export", "order_id", (500, 560)),
       ("Сверка дефектов трекера и отчёта о регрессе", "tracker", "report", "bug_id", (300, 380)),
       ("Сверка платежей песочницы с выпиской шлюза", "sandbox", "statement", "pay_id", (700, 790))]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, A, B, key, (lo, hi) = rng.choice(CTX)
    for _ in range(500):
        na = rng.randint(5, 6)
        keys_a = rng.sample(range(lo, hi), na)
        null_a = rng.random() < 0.5
        null_b = rng.random() < 0.75
        if not (null_a or null_b):
            null_b = True
        if null_a:
            keys_a[rng.randrange(na)] = None
        nonnull_a = [k for k in keys_a if k is not None]
        n_match = rng.randint(2, len(nonnull_a) - 1)
        matched = rng.sample(nonnull_a, n_match)
        extra = [k for k in rng.sample(range(lo, hi), 4) if k not in keys_a][:rng.randint(0, 2)]
        keys_b = matched + extra + ([None] * (rng.choice([1, 1, 2]) if null_b else 0))
        rng.shuffle(keys_b)
        break
    else:
        raise RuntimeError("t21_not_in_null: не собраны данные")
    rows_a = [(i + 1, k) for i, k in enumerate(keys_a)]
    rows_b = [(i + 1, k) for i, k in enumerate(keys_b)]
    nonnull_b = {k for k in keys_b if k is not None}
    has_null_b = any(k is None for k in keys_b)
    # трёхзначная логика NOT IN: TRUE только если ключ не NULL, его нет среди значений и в подзапросе нет NULL
    not_in = 0 if has_null_b else sum(1 for k in keys_a if k is not None and k not in nonnull_b)
    not_exists = sum(1 for k in keys_a if k is None or k not in nonnull_b)
    res = {A: (len(keys_a), len(nonnull_a)), B: (len(keys_b), sum(1 for k in keys_b if k is not None)),
           "missing": (not_in, not_exists)}
    order = sorted(res)
    out = "\n".join(f"{lbl}|{res[lbl][0]}|{res[lbl][1]}" for lbl in order)
    code = (f"SELECT '{A}' AS part, COUNT(*) AS v1, COUNT({key}) AS v2 FROM {A}\n"
            "UNION ALL\n"
            f"SELECT '{B}', COUNT(*), COUNT({key}) FROM {B}\n"
            "UNION ALL\n"
            "SELECT 'missing',\n"
            f"  (SELECT COUNT(*) FROM {A} WHERE {key} NOT IN (SELECT {key} FROM {B})),\n"
            f"  (SELECT COUNT(*) FROM {A} a WHERE NOT EXISTS (SELECT 1 FROM {B} b WHERE b.{key} = a.{key}))\n"
            "ORDER BY 1;")
    setup = (f"CREATE TABLE {A} (id INTEGER PRIMARY KEY, {key} INTEGER);\n"
             f"CREATE TABLE {B} (id INTEGER PRIMARY KEY, {key} INTEGER);\n"
             + sql_inserts(A, ["id", key], rows_a) + "\n" + sql_inserts(B, ["id", key], rows_b) + "\n")
    miss_keys = [str(k) for k in keys_a if k is not None and k not in nonnull_b]
    notes = [f"{A}: строк {len(keys_a)}, COUNT({key}) без NULL — {len(nonnull_a)}",
             f"{B}: строк {len(keys_b)}, COUNT({key}) — {res[B][1]}"]
    if has_null_b:
        notes.append(f"в {B} есть NULL-ключ, поэтому `{key} NOT IN (…)` ни для одной строки не TRUE (сравнение с NULL "
                     f"даёт UNKNOWN) — 0")
    else:
        notes.append(f"в {B} NULL нет, NOT IN считает ключи {A}, которых нет в {B}: {', '.join(miss_keys) or 'нет'}"
                     + (f"; строка {A} с NULL-ключом даёт UNKNOWN и не считается" if null_a else "") +
                     f" — {not_in}")
    notes.append(f"NOT EXISTS считает строки {A} без пары: " + ", ".join(miss_keys + (["NULL"] if null_a else []))
                 + f" — {not_exists}" + (" (NULL не равен ничему, пары у него нет)" if null_a else ""))
    expl = ("; ".join(notes) + f". Строки упорядочены по первому столбцу (ORDER BY 1). Ответ: "
            + " / ".join(f"«{ln}»" for ln in out.split("\n")) + ".")
    stem = (f"{plot}: запрос строит сводку сверки двух выгрузок.\n\n{A}\n{text_table(['id', key], rows_a)}\n\n"
            f"{B}\n{text_table(['id', key], rows_b)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"a": keys_a, "b": keys_b}, language="sql", files={"setup.sql": setup})
