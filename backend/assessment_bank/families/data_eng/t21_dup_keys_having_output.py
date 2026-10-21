"""data_eng.dq.t21_dup_keys_having_output — predict_output (набор t21, порог Junior): поиск дублей ключа —
GROUP BY + HAVING и COUNT(*) рядом с COUNT(DISTINCT batch_id).

Сырые события загружаются партиями (batch_id); одно и то же событие может прийти дважды в одной партии или в разных.
Запрос группирует по event_id, оставляет группы по условию HAVING (либо `COUNT(*) > 1` — любые дубли, либо
`COUNT(DISTINCT batch_id) > 1` — только дубли между партиями) и выводит число копий и число различных партий.
Ловушки: HAVING фильтрует группы после подсчёта; COUNT(DISTINCT) не равен COUNT(*), если дубль пришёл в той же
партии. Ключ — независимый подсчёт в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "data_eng.dq.t21_dup_keys_having_output"

CTX = [("события мобильного приложения", "raw_app_events"), ("клики по рекламе", "raw_clicks"),
       ("платёжные уведомления", "raw_payments"), ("изменения заказов из очереди", "raw_order_changes"),
       ("показания датчиков", "raw_sensor_readings")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    mode = rng.choice(["star", "star", "distinct"])
    having = "COUNT(*) > 1" if mode == "star" else "COUNT(DISTINCT batch_id) > 1"
    for _ in range(500):
        n_keys = rng.randint(4, 6)
        keys = sorted(rng.sample(range(5001, 5099), n_keys))
        batches = rng.sample(range(11, 40), 3)
        rows = []
        for k in keys:
            copies = rng.choice([1, 1, 2, 2, 3])
            for _ in range(copies):
                rows.append((k, rng.choice(batches)))
        rng.shuffle(rows)
        if not 8 <= len(rows) <= 11:
            continue
        stats = {}
        for k, b in rows:
            c, bs = stats.get(k, (0, []))
            stats[k] = (c + 1, bs + [b])
        res = []
        for k in sorted(stats):
            c, bs = stats[k]
            nb = len(set(bs))
            if (c > 1) if mode == "star" else (nb > 1):
                res.append((k, c, nb))
        same_batch = [k for k in sorted(stats) if stats[k][0] > 1 and len(set(stats[k][1])) == 1]
        cross = [k for k in sorted(stats) if len(set(stats[k][1])) > 1]
        uneq = [r for r in res if r[1] != r[2]]
        if 2 <= len(res) <= 3 and same_batch and cross and uneq and any(stats[k][0] == 1 for k in stats):
            break
    else:
        raise RuntimeError("t21_dup_keys_having: не собрались данные")
    data = [(i + 1, k, b) for i, (k, b) in enumerate(rows)]
    code = (f"SELECT event_id, COUNT(*) AS copies, COUNT(DISTINCT batch_id) AS batches\n"
            f"FROM {table}\n"
            f"GROUP BY event_id\n"
            f"HAVING {having}\n"
            f"ORDER BY event_id;")
    setup = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, batch_id INTEGER NOT NULL);\n"
             + sql_inserts(table, ["id", "event_id", "batch_id"], data) + "\n")
    out = "\n".join(f"{k}|{c}|{nb}" for k, c, nb in res)
    if mode == "star":
        rule = (f"HAVING COUNT(*) > 1 оставляет все события, пришедшие больше одного раза, в том числе дубли внутри "
                f"одной партии (например, {same_batch[0]}: копий {stats[same_batch[0]][0]}, партия одна)")
    else:
        rule = (f"HAVING COUNT(DISTINCT batch_id) > 1 оставляет только события из разных партий; дубль внутри одной "
                f"партии ({same_batch[0]}) отсекается, хотя COUNT(*) у него больше 1")
    def _where(k):
        bs = sorted(set(stats[k][1]))
        return ("в партии " if len(bs) == 1 else "в партиях ") + "/".join(str(b) for b in bs)
    expl = ("Группы по event_id: " + ", ".join(f"{k} — {stats[k][0]} шт. {_where(k)}" for k in sorted(stats))
            + f". {rule}. Итог: " + "; ".join(f"{k}|{c}|{nb}" for k, c, nb in res) + ".")
    stem = (f"Проверка качества сырых данных ({ctx}): запрос ищет повторяющиеся события и показывает, сколько у них "
            f"копий и в скольких партиях загрузки они встретились.\n\n{table}\n"
            f"{text_table(['id', 'event_id', 'batch_id'], data)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"having": mode, "rows": len(data), "keys": n_keys}, language="sql",
                          files={"setup.sql": setup})
