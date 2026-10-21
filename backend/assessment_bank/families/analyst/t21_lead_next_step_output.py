"""analyst.sql.t21_lead_next_step_output — predict_output (набор t21, порог Senior): LEAD по партиции пользователя —
конверсия «шаг A → сразу шаг B за N дней».

Лог событий нескольких пользователей вперемешку и запрос: CTE добавляет к каждому событию следующее событие того же
пользователя и его день (`LEAD(...) OVER (PARTITION BY user_id ORDER BY day)`), внешний запрос считает пары
«A, затем сразу B не позже чем через N дней» по пользователям. Ловушки: LEAD смотрит только на соседнюю следующую
строку (A → другое событие → B не считается), у последнего события пользователя LEAD = NULL, переход «слишком
поздно» отсекается условием на дни, пользователи без конверсий в результат не попадают вовсе. Ключ — независимый
расчёт в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_lead_next_step_output"

# (таблица, сюжет, шаг A, шаг B, прочие события)
CTX = [
    ("events", "Воронка интернет-магазина", "cart", "purchase", ["view", "search"]),
    ("app_events", "Онбординг мобильного приложения", "trial", "payment", ["open", "settings"]),
    ("crm_events", "Воронка B2B-продаж", "demo", "contract", ["call", "email"]),
    ("travel_events", "Сервис бронирования поездок", "quote", "booking", ["search", "review"]),
]


def _model(rows, a, b, w):
    users = sorted({r[1] for r in rows})
    conv, notes = {}, {"gap": [], "other": [], "last": []}
    for u in users:
        ev = sorted((r for r in rows if r[1] == u), key=lambda r: r[2])
        for i, r in enumerate(ev):
            if r[3] != a:
                continue
            if i + 1 == len(ev):
                notes["last"].append(r)
                continue
            nx = ev[i + 1]
            if nx[3] == b and nx[2] - r[2] <= w:
                conv[u] = conv.get(u, 0) + 1
            elif nx[3] == b:
                notes["gap"].append(r)
            else:
                notes["other"].append(r)
    return conv, notes


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, a, b, others = rng.choice(CTX)
    w = rng.choice([2, 3])
    for _ in range(2000):
        n_u = rng.randint(3, 4)
        users = sorted(rng.sample(range(11, 60), n_u))
        rows = []
        for u in users:
            k = rng.randint(2, 4)
            days = sorted(rng.sample(range(1, 15), k))
            evs = [rng.choice([a, a, b, b] + others) for _ in range(k)]
            rows += [[None, u, d, e] for d, e in zip(days, evs)]
        if not 9 <= len(rows) <= 12:
            continue
        rng.shuffle(rows)
        rows.sort(key=lambda r: r[2])      # лог в хронологическом порядке, пользователи вперемешку
        eid = rng.randint(1, 20)
        for r in rows:
            eid += rng.randint(1, 2)
            r[0] = eid
        rows = [tuple(r) for r in rows]
        conv, notes = _model(rows, a, b, w)
        a_users = {r[1] for r in rows if r[3] == a}
        absent = [u for u in a_users if u not in conv]
        traps = sum(1 for k in ("gap", "other", "last") if notes[k])
        if conv and absent and traps >= 2 and (notes["gap"] or notes["other"]):
            break
    else:
        raise RuntimeError("t21_lead_next_step: не собрались данные")
    code = (f"WITH ev AS (\n"
            f"  SELECT user_id, day, event,\n"
            f"         LEAD(event) OVER w AS next_event,\n"
            f"         LEAD(day) OVER w AS next_day\n"
            f"  FROM {T}\n"
            f"  WINDOW w AS (PARTITION BY user_id ORDER BY day)\n"
            f")\n"
            f"SELECT user_id, COUNT(*) AS conversions\n"
            f"FROM ev\n"
            f"WHERE event = '{a}'\n"
            f"  AND next_event = '{b}'\n"
            f"  AND next_day - day <= {w}\n"
            f"GROUP BY user_id\n"
            f"ORDER BY user_id;")
    out = "\n".join(f"{u}|{c}" for u, c in sorted(conv.items()))
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day INTEGER NOT NULL, "
             f"event TEXT NOT NULL);\n" + sql_inserts(T, ["id", "user_id", "day", "event"], rows) + "\n")
    stem = (f"{plot}: события пользователей (day — номер дня), запрос считает переходы «{a} → {b}» не дольше "
            f"{w} дней по каждому пользователю.\n\n{T}\n{text_table(['id', 'user_id', 'day', 'event'], rows)}")
    parts = []
    if notes["other"]:
        parts.append("после " + ", ".join(f"«{a}» пользователя {r[1]} в день {r[2]}" for r in notes["other"])
                     + " следующим идёт другое событие — LEAD видит только соседнюю строку")
    if notes["gap"]:
        parts.append(", ".join(f"у пользователя {r[1]} от дня {r[2]}" for r in notes["gap"])
                     + f" до «{b}» больше {w} дней")
    if notes["last"]:
        parts.append(", ".join(f"«{a}» пользователя {r[1]} в день {r[2]}" for r in notes["last"])
                     + " — последнее событие, LEAD = NULL")
    expl = (f"LEAD берёт следующее событие того же user_id в порядке day. Засчитываются только пары «{a}», за "
            f"которым сразу «{b}» не позже чем через {w} дн. Не считаются: " + "; ".join(parts) + ". "
            f"Пользователи без засчитанных пар ({', '.join(str(u) for u in sorted(absent))}) в результат не "
            f"попадают — WHERE отсекает их строки до GROUP BY. Ответ: " + "; ".join(out.splitlines()) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "w": w}, language="sql", files={"setup.sql": setup})
