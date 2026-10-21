"""data_eng.sql.t21_rank_dedup_ties_output — predict_output (набор t21, порог Middle): дедупликация «последняя
версия по ключу» через оконную функцию с PARTITION BY и фильтром rn = 1 — RANK против ROW_NUMBER при равных временах.

Сырые версии заказов загружаются несколько раз; запрос оставляет по каждому order_id строку с наибольшим loaded_at.
Ловушки: RANK даёт 1 всем строкам с одинаковым максимальным loaded_at — дубли остаются; ROW_NUMBER с вторым ключом
`id DESC` оставляет ровно одну — с бо́льшим id. Ключ — независимая модель в генераторе; проверка — исполнение в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.sql.t21_rank_dedup_ties_output"

CTX = [("версии заказов из учётной системы", "raw_orders", "order_id", ["new", "paid", "shipped", "cancelled"]),
       ("версии доставок", "raw_deliveries", "delivery_id", ["created", "in_transit", "delivered", "returned"]),
       ("версии заявок на кредит", "raw_applications", "application_id", ["draft", "review", "approved", "denied"]),
       ("версии тикетов поддержки", "raw_tickets", "ticket_id", ["open", "pending", "solved", "closed"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, key, statuses = rng.choice(CTX)
    fn = rng.choice(["RANK()", "RANK()", "ROW_NUMBER()"])
    for _ in range(500):
        n_keys = rng.randint(3, 4)
        keys = sorted(rng.sample(range(11, 60), n_keys))
        rows = []
        tie_key = rng.choice(keys)
        for k in keys:
            m = rng.randint(2, 3)
            times = sorted(rng.sample(range(8, 20), m))
            if k == tie_key:
                times[-2] = times[-1]
            for t in times:
                rows.append((k, rng.choice(statuses), f"{t:02d}:{rng.choice(['00', '15', '30', '45'])}"
                             if k != tie_key else f"{t:02d}:30"))
        # у ключа с равенством оба последних времени совпадают и статусы различны
        tie_rows = [r for r in rows if r[0] == tie_key]
        if tie_rows[-1][1] == tie_rows[-2][1]:
            continue
        rng.shuffle(rows)
        data = [(i + 1, k, s, t) for i, (k, s, t) in enumerate(rows)]
        ok = True
        res = []
        for k in keys:
            grp = [r for r in data if r[1] == k]
            mx = max(r[3] for r in grp)
            top = [r for r in grp if r[3] == mx]
            if k != tie_key and len(top) > 1:
                ok = False
            if fn == "RANK()":
                res += [(k, r[2]) for r in top]
            else:
                res.append((k, max(top, key=lambda r: r[0])[2]))
        if ok:
            break
    else:
        raise RuntimeError("t21_rank_dedup_ties: не собрались версии")
    res.sort()
    order = "loaded_at DESC" if fn == "RANK()" else "loaded_at DESC, id DESC"
    code = (f"SELECT {key}, status\n"
            "FROM (\n"
            f"  SELECT {key}, status,\n"
            f"    {fn} OVER (PARTITION BY {key} ORDER BY {order}) AS rn\n"
            f"  FROM {table}\n"
            ")\n"
            "WHERE rn = 1\n"
            f"ORDER BY {key}, status;")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {key} INTEGER NOT NULL, status TEXT NOT NULL, "
             "loaded_at TEXT NOT NULL);\n" + sql_inserts(table, ["id", key, "status", "loaded_at"], data) + "\n")
    out = "\n".join(f"{k}|{s}" for k, s in res)
    tie = [r for r in data if r[1] == tie_key]
    mx = max(r[3] for r in tie)
    tie_top = [r for r in tie if r[3] == mx]
    if fn == "RANK()":
        ids = ", ".join(str(r[0]) for r in tie_top)
        why = (f"у {key} = {tie_key} две версии с одинаковым loaded_at {mx} (id {ids})"
               " — RANK даёт обеим 1, и обе остаются: дедупликация не сработала")
    else:
        win = max(tie_top, key=lambda r: r[0])
        why = (f"у {key} = {tie_key} две версии с loaded_at {mx}; ROW_NUMBER нумерует их по второму ключу id DESC, "
               f"и rn = 1 получает только id {win[0]} ({win[2]})")
    expl = (f"Окно нумерует версии каждого {key} от последней по loaded_at. {why[0].upper() + why[1:]}. Итог: "
            + "; ".join(f"{k}|{s}" for k, s in res) + ".")
    stem = (f"Слой очищенных данных ({ctx}): запрос оставляет последнюю загруженную версию каждой записи."
            f"\n\n{table}\n{text_table(['id', key, 'status', 'loaded_at'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"fn": fn, "rows": len(data), "keys": n_keys}, language="sql",
                          files={"setup.sql": setup})
