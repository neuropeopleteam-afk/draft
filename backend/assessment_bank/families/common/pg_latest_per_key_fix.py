"""common.pg.pg_latest_per_key_fix — choose_fix (Senior/Lead, PostgreSQL): последняя версия записи на ключ.

Таблица версий (id, ключ, статус, время обновления); нужна последняя версия на каждый ключ. Показанный запрос
сортирует окно по возрастанию (берёт первую версию). Замены: верная — ROW_NUMBER() с ORDER BY время DESC, id DESC
(у части ключей две последние версии в одну и ту же секунду — порядок по id обязателен); неверные (схема 2×2) —
при равном времени — меньший id (ORDER BY … DESC, id ASC), PARTITION BY по
статусу, оба дефекта сразу. Запросы — общий SQL,
одинаково исполняются в PostgreSQL и SQLite; проверка — исполнением в SQLite.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import codefix_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.pg.pg_latest_per_key_fix"
SCEN = [("orders_history", "order_id", "status", ["new", "paid", "shipped", "delivered", "cancelled"], "заказов"),
        ("ticket_events", "ticket_id", "state", ["open", "in_progress", "waiting", "resolved"], "тикетов"),
        ("device_status", "device_id", "mode", ["online", "offline", "sleep", "update"], "устройств"),
        ("price_versions", "sku", "price_band", ["low", "mid", "high", "promo"], "товаров"),
        ("account_flags", "account_id", "flag", ["active", "frozen", "closed", "review"], "счетов")]


ALIAS = ["t", "v", "ranked", "last_rows", "w"]   # косметика: длина варианта не подсказывает ключ
TS = ["updated_at", "changed_at", "valid_from", "recorded_at"]
IDS = ["id", "version_id", "rev", "seq"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(50):              # данные подбираются, пока каждая неверная замена не отличается от эталона
        try:
            return _gen(seed, rng)
        except RuntimeError:
            continue
    raise RuntimeError("не удалось подобрать данные")


def _gen(seed, rng):
    tbl, key, col, vals, what = SCEN[seed % len(SCEN)]
    ts, idc = rng.choice(TS), rng.choice(IDS)
    rows, rid = [], 0
    nkeys = rng.randint(4, 6)
    for k in range(1, nkeys + 1):
        t = rng.randint(0, 50)
        for j in range(rng.randint(2, 4)):
            rid += 1
            t += rng.choice([0, 0, 7, 30, 90]) if j else 0   # бывают две версии в одну секунду
            rows.append((rid, 100 + k, rng.choice(vals), f"2026-10-0{1 + t // 1440} {t // 60 % 24:02d}:{t % 60:02d}:00"))
        if k == 1 or rng.random() < 0.3:                      # две последние версии в одну секунду
            rid += 1
            rows.append((rid, 100 + k, rng.choice([x for x in vals if x != rows[-1][2]]), rows[-1][3]))
    rng.shuffle(rows)
    setup = (f"CREATE TABLE {tbl} ({idc} INTEGER PRIMARY KEY, {key} INTEGER NOT NULL, {col} TEXT NOT NULL, "
             f"{ts} TEXT NOT NULL);\n" + "\n".join(
                 f"INSERT INTO {tbl} VALUES ({r[0]}, {r[1]}, '{r[2]}', '{r[3]}');" for r in rows))

    def q(fn="ROW_NUMBER()", order=None, part=key):
        order = order or f"{ts} DESC, {idc} DESC"
        return (f"SELECT {key}, {col}, {ts} FROM (\n  SELECT {key}, {col}, {ts},\n"
                f"         {fn} OVER (PARTITION BY {part} ORDER BY {order}) AS rn\n  FROM {tbl}\n) {rng.choice(ALIAS)}\n"
                f"WHERE rn = 1\nORDER BY {key};")
    good = q()
    buggy = q(order=f"{ts}, {idc}")
    group = (f"SELECT {key}, {col}, MAX({ts}) AS {ts}\nFROM {tbl}\nGROUP BY {key}, {col}\n"
             f"ORDER BY {key};")
    # 2×2: при равном времени — больший / меньший id × окно по ключу / по статусу — все варианты одинаково «центральны»
    asc_tie = f"{ts} DESC, {idc} ASC"
    wrongs = [("tie_asc", q(order=asc_tie)), ("wrong_partition", q(part=col)),
              ("tie_asc_wrong_partition", q(order=asc_tie, part=col))]
    stem = (rng.choice([f"Таблица `{tbl}` (PostgreSQL) хранит все версии {what}.",
                        f"В PostgreSQL история {what} пишется в `{tbl}` — каждая правка новой строкой.",
                        f"Сервис аудита складывает версии {what} в таблицу `{tbl}` (PostgreSQL)."])
            + f" `{idc}` растёт с каждой вставкой, `{ts}` — с точностью до секунды, у одного ключа бывают две версии в "
            "одну и ту же секунду. " + rng.choice(["Отчёту нужна", "Витрине нужна", "Выгрузке в CRM нужна"])
            + f" ровно одна, последняя версия на каждый `{key}` (при равном времени — с большим `{idc}`). Показанный "
            "запрос возвращает не те строки. Какая замена запроса верна?")
    expl = ("Последняя версия — первая строка окна, отсортированного по убыванию времени, с id как вторым ключом "
            "сортировки (детерминизм при совпадении секунды). id ASC при равной секунде берёт более раннюю из двух версий; "
            "окно по статусу вместо ключа берёт последние версии статусов, а не ключей.")
    return codefix_variant(FAMILY_ID, seed, rng, ctx=what, stem=stem, runner="sqlite", buggy=buggy, good=good,
                           wrongs=wrongs, label="Заменить запрос на:", harness=None, setup=setup, explanation=expl,
                           defect_type="logic", params={"table": tbl, "n_rows": len(rows)}, language="sql")
