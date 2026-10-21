"""data_eng.sql.t21_lag_change_output — predict_output (набор t21, порог Senior): выделение изменений из
ежедневных снимков через LAG по партиции и сравнение с NULL (`<>` против `IS NOT`).

Снимки статусов по счетам; запрос оставляет строки, где статус отличается от предыдущего снимка того же счёта
(`LAG(status) OVER (PARTITION BY account ORDER BY snap_date)`). Ловушки: у первого снимка счёта prev = NULL, и
`status <> prev` даёт UNKNOWN — первая версия теряется; переход в NULL и из NULL при `<>` тоже теряется, а
null-безопасное `IS NOT` их сохраняет. Ключ — независимая модель в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_lag_change_output"

CTX = [("статусы банковских счетов", "account_snapshots", "account", ["A-11", "A-27", "A-35", "A-48"],
        ["active", "blocked", "closed"]),
       ("статусы подписок", "subscription_snapshots", "account", ["S-03", "S-19", "S-22", "S-40"],
        ["trial", "paid", "paused"]),
       ("статусы карточек товаров", "product_snapshots", "account", ["P-105", "P-212", "P-318", "P-427"],
        ["draft", "listed", "hidden"]),
       ("статусы договоров", "contract_snapshots", "account", ["C-7", "C-14", "C-21", "C-28"],
        ["signed", "active", "ended"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, key, accounts, statuses = rng.choice(CTX)
    cond = rng.choice(["status <> prev_status", "status <> prev_status", "status IS NOT prev_status"])
    use_null = rng.random() < 0.5
    base = dt.date(2026, rng.randint(1, 12), rng.randint(1, 25))
    for _ in range(500):
        accs = rng.sample(accounts, rng.randint(2, 3))
        snaps = []
        for a in accs:
            k = rng.randint(3, 4)
            st = [rng.choice(statuses) for _ in range(k)]
            if use_null and rng.random() < 0.6:
                st[rng.randint(1, k - 1)] = None
            for i, s in enumerate(st):
                snaps.append((a, (base + dt.timedelta(days=i)).isoformat(), s))
        res = []
        for a in accs:
            rows = [r for r in snaps if r[0] == a]
            prev = None
            for i, (aa, d, s) in enumerate(rows):
                p = rows[i - 1][2] if i else None
                if cond.startswith("status <>"):
                    keep = s is not None and p is not None and s != p
                else:
                    keep = s != p  # IS NOT: NULL IS NOT NULL — ложь, значение IS NOT NULL — истина
                if keep:
                    res.append((aa, d, s))
                prev = s
        has_eq = any(snaps[i][0] == snaps[i - 1][0] and snaps[i][2] == snaps[i - 1][2] for i in range(1, len(snaps)))
        has_null = any(s is None for _, _, s in snaps)
        if 2 <= len(res) <= 5 and has_eq and (has_null == use_null):
            break
    else:
        raise RuntimeError("t21_lag_change: не собрались снимки")
    order = sorted(range(len(snaps)), key=lambda i: (snaps[i][1], rng.random()))
    shown = [snaps[i] for i in order]
    data = [(i + 1, a, d, s) for i, (a, d, s) in enumerate(shown)]
    res.sort(key=lambda r: (r[0], r[1]))
    code = ("SELECT account, snap_date, status\n"
            "FROM (\n"
            "  SELECT\n"
            "    account,\n"
            "    snap_date,\n"
            "    status,\n"
            "    LAG(status) OVER (\n"
            "      PARTITION BY account\n"
            "      ORDER BY snap_date\n"
            "    ) AS prev_status\n"
            f"  FROM {table}\n"
            ")\n"
            f"WHERE {cond}\n"
            "ORDER BY account, snap_date;")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, account TEXT NOT NULL, snap_date TEXT NOT NULL, "
             "status TEXT);\n" + sql_inserts(table, ["id", "account", "snap_date", "status"], data) + "\n")
    fmt = lambda v: "NULL" if v is None else v
    out = "\n".join(f"{a}|{d}|{fmt(s)}" for a, d, s in res)
    if cond.startswith("status <>"):
        why = ("у первого снимка каждого счёта prev_status = NULL, и status <> NULL — UNKNOWN: первая версия "
               "в результат не попадает"
               + ("; переходы в NULL и из NULL тоже дают UNKNOWN и теряются" if use_null else ""))
    else:
        why = ("IS NOT сравнивает NULL как значение: первый снимок (prev = NULL) попадает в результат"
               + ("; переходы в NULL и из NULL — тоже, а NULL после NULL — нет" if use_null else "")
               + "; одинаковые соседние статусы отбрасываются")
    expl = (f"LAG берёт статус предыдущего по дате снимка того же счёта. {why[0].upper() + why[1:]}. Итог: "
            + "; ".join(f"{a}|{d}|{fmt(s)}" for a, d, s in res) + ".")
    stem = (f"Хранилище получает ежедневные снимки ({ctx}); запрос выделяет из них изменения статуса для загрузки "
            f"истории.\n\n{table}\n{text_table(['id', 'account', 'snap_date', 'status'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"cond": cond, "nulls": use_null, "snapshots": len(data)}, language="sql",
                          files={"setup.sql": setup})
