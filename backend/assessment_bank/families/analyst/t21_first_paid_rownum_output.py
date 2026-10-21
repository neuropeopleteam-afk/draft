"""analyst.sql.t21_first_paid_rownum_output — predict_output (набор t21, порог Senior): ROW_NUMBER в CTE и фильтр
по статусу — до окна или после него.

Таблица заказов / платежей / поездок / бронирований нескольких пользователей вперемешку. CTE нумерует строки
каждого пользователя по времени (`ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at)`), внешний запрос
берёт `rn = 1`. В одних вариантах фильтр статуса стоит снаружи (`WHERE rn = 1 AND status = '…'`) — тогда номер 1
получает самая ранняя строка любого статуса, и пользователь, у которого она «не та», выпадает целиком; в других —
внутри CTE (WHERE выполняется до оконной функции) — тогда rn = 1 у первой строки нужного статуса. Ключ —
независимый расчёт в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_first_paid_rownum_output"

# (таблица, сюжет, статусы [нужный, прочие], числовая колонка, сетка)
CTX = [
    ("orders", "Первая оплаченная покупка клиента", ["paid", "cancelled"], "amount", list(range(300, 5001, 100))),
    ("payments", "Первый успешный платёж подписчика", ["success", "failed"], "amount", list(range(199, 1000, 100))),
    ("rides", "Первая завершённая поездка нового пассажира", ["done", "cancelled"], "price",
     list(range(250, 1501, 50))),
    ("bookings", "Первое подтверждённое бронирование гостя", ["confirmed", "cancelled"], "nights",
     list(range(1, 11))),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, statuses, num, grid = rng.choice(CTX)
    good = statuses[0]
    inner = rng.random() < 0.4
    for _ in range(2000):
        n_u = rng.randint(3, 4)
        users = sorted(rng.sample(range(101, 160), n_u))
        rows = []
        for u in users:
            k = rng.randint(2, 3)
            days = sorted(rng.sample(range(1, 29), k))
            for d in days:
                st = good if rng.random() < 0.55 else rng.choice(statuses[1:])
                rows.append([None, u, f"2026-10-{d:02d}", st, rng.choice(grid)])
        if not 7 <= len(rows) <= 10:
            continue
        per_user = {u: sorted((r for r in rows if r[1] == u), key=lambda r: r[2]) for u in users}
        first_any = {u: per_user[u][0] for u in users}
        first_good = {u: next((r for r in per_user[u] if r[3] == good), None) for u in users}
        bad_first = [u for u in users if first_any[u][3] != good and first_good[u] is not None]
        good_first = [u for u in users if first_any[u][3] == good]
        if not bad_first or not good_first:
            continue
        # в первой строке «не того» статуса сумма отличается от первой «нужной»
        if any(first_any[u][4] == first_good[u][4] for u in bad_first):
            continue
        break
    else:
        raise RuntimeError("t21_first_paid_rownum: не собрались данные")
    rng.shuffle(rows)
    eid = rng.randint(1, 30)
    for r in rows:
        eid += rng.randint(1, 3)
        r[0] = eid
    rows = [tuple(r) for r in rows]
    if inner:
        res = [(u, first_good[u][4]) for u in users if first_good[u] is not None]
        cte_where, outer_where = f"\n  WHERE status = '{good}'", "WHERE rn = 1"
    else:
        res = [(u, first_any[u][4]) for u in users if first_any[u][3] == good]
        cte_where, outer_where = "", f"WHERE rn = 1 AND status = '{good}'"
    code = (f"WITH ranked AS (\n"
            f"  SELECT user_id, status, {num},\n"
            f"         ROW_NUMBER() OVER (\n"
            f"           PARTITION BY user_id ORDER BY created_at\n"
            f"         ) AS rn\n"
            f"  FROM {T}{cte_where}\n"
            f")\n"
            f"SELECT user_id, {num}\n"
            f"FROM ranked\n"
            f"{outer_where}\n"
            f"ORDER BY user_id;")
    out = "\n".join(f"{u}|{v}" for u, v in res)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, "
             f"status TEXT NOT NULL, {num} INTEGER NOT NULL);\n"
             + sql_inserts(T, ["id", "user_id", "created_at", "status", num], rows) + "\n")
    stem = (f"{plot}: запрос нумерует строки каждого пользователя по времени и берёт первую.\n\n"
            f"{T}\n{text_table(['id', 'user_id', 'created_at', 'status', num], rows)}")
    if inner:
        why = (f"WHERE status = '{good}' стоит внутри CTE и выполняется раньше ROW_NUMBER, поэтому нумеруются только "
               f"строки '{good}' и rn = 1 — первая такая строка пользователя (у user_id "
               + ", ".join(str(u) for u in bad_first) + " она не самая ранняя среди всех его строк)")
    else:
        why = (f"ROW_NUMBER считается по всем строкам, а фильтр status = '{good}' применяется снаружи, уже после "
               f"нумерации: у user_id " + ", ".join(str(u) for u in bad_first)
               + f" самая ранняя строка не '{good}' — такие пользователи выпадают из результата, хотя позже "
                 f"строки '{good}' у них есть")
    expl = f"{why}. Ответ: " + ("; ".join(out.splitlines()) if out else "пусто") + "."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "inner": inner}, language="sql", files={"setup.sql": setup})
