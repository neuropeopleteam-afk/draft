"""analyst.sql.t21_not_in_null_output — predict_output (набор t21, порог Senior): IN, NOT IN и NOT EXISTS, когда в
подзапросе может оказаться NULL.

Две таблицы: справочник (пользователи, лиды, водители, подписчики) и события со ссылкой на него, где у части строк
ссылка NULL (гостевой заказ, сделка без лида и т. п.). Запрос в одной строке считает три числа: сколько записей
справочника IN (подзапрос), NOT IN (подзапрос) и NOT EXISTS (коррелированный подзапрос); подзапрос фильтрует события
по статусу. Ловушка: если NULL проходит фильтр подзапроса, `id NOT IN (…)` ни для кого не истинно (сравнение с NULL
даёт «неизвестно») и NOT IN = 0, а NOT EXISTS считает честно; если строка с NULL отфильтрована статусом — NOT IN и
NOT EXISTS совпадают. Ключ — независимый расчёт в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_not_in_null_output"

# (справочник, события, ссылка, статусы [нужный, прочие], сюжет, алиасы (в, не в, не существует))
CTX = [
    ("users", "orders", "user_id", ["paid", "cancelled"],
     "Пользователи и заказы интернет-магазина", ("buyers", "not_in_cnt", "not_exists_cnt")),
    ("leads", "deals", "lead_id", ["won", "lost"],
     "Лиды и сделки в CRM", ("won_leads", "not_in_cnt", "not_exists_cnt")),
    ("drivers", "complaints", "driver_id", ["confirmed", "rejected"],
     "Водители такси и жалобы пассажиров", ("with_complaints", "not_in_cnt", "not_exists_cnt")),
    ("subscribers", "unsubscribes", "subscriber_id", ["done", "pending"],
     "Подписчики рассылки и заявки на отписку", ("gone", "not_in_cnt", "not_exists_cnt")),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    P, E, fk, statuses, plot, (a_in, a_nin, a_nex) = rng.choice(CTX)
    good = statuses[0]
    null_passes = rng.random() < 0.65
    for _ in range(1000):
        n_p = rng.randint(5, 9)
        pids = sorted(rng.sample(range(1, 40), n_p))
        m = rng.randint(6, 9)
        ev = []
        eid = rng.randint(100, 160)
        for _k in range(m):
            eid += rng.randint(1, 4)
            ref = rng.choice(pids) if rng.random() < 0.85 else None
            ev.append([eid, ref, good if rng.random() < 0.6 else rng.choice(statuses[1:])])
        nulls = [e for e in ev if e[1] is None]
        if not nulls:
            continue
        for e in nulls:            # статус строк с NULL — по выбранной ветке
            e[2] = good if null_passes else rng.choice(statuses[1:])
        if null_passes and len(nulls) > 1:
            nulls[-1][2] = rng.choice(statuses)
        sub = [e[1] for e in ev if e[2] == good]
        has_null = any(r is None for r in sub)
        if has_null != null_passes:
            continue
        hit = {r for r in sub if r is not None}
        n_in = sum(1 for p in pids if p in hit)
        n_nex = sum(1 for p in pids if p not in hit)
        # есть записи только с «не теми» статусами — чтобы фильтр в подзапросе был важен
        only_other = [p for p in pids if p not in hit and any(e[1] == p for e in ev)]
        if n_in >= 1 and n_nex >= 2 and only_other:
            break
    else:
        raise RuntimeError("t21_not_in_null: не собрались данные")
    n_nin = 0 if has_null else n_nex
    ev = [tuple(e) for e in ev]
    code = (f"SELECT\n"
            f"  (SELECT COUNT(*) FROM {P}\n"
            f"    WHERE id IN (SELECT {fk} FROM {E} WHERE status = '{good}')) AS {a_in},\n"
            f"  (SELECT COUNT(*) FROM {P}\n"
            f"    WHERE id NOT IN (SELECT {fk} FROM {E} WHERE status = '{good}')) AS {a_nin},\n"
            f"  (SELECT COUNT(*) FROM {P} p\n"
            f"    WHERE NOT EXISTS (SELECT 1 FROM {E} e\n"
            f"                      WHERE e.{fk} = p.id AND e.status = '{good}')) AS {a_nex};")
    out = f"{n_in}|{n_nin}|{n_nex}"
    setup = (f"CREATE TABLE {P} (id INTEGER PRIMARY KEY);\n"
             f"CREATE TABLE {E} (id INTEGER PRIMARY KEY, {fk} INTEGER, status TEXT NOT NULL);\n"
             + sql_inserts(P, ["id"], [(p,) for p in pids]) + "\n"
             + sql_inserts(E, ["id", fk, "status"], ev) + "\n")
    stem = (f"{plot}: запрос тремя способами считает записи {P} с событием '{good}' и без него.\n\n"
            f"{P}: id = {', '.join(str(p) for p in pids)}\n\n"
            f"{E}\n{text_table(['id', fk, 'status'], ev)}")
    hit_txt = ", ".join(str(p) for p in pids if p in hit)
    if has_null:
        trap = (f"подзапрос со статусом '{good}' возвращает и NULL, поэтому для каждого id условие id NOT IN (…) "
                f"даёт «неизвестно», а не «истина», и {a_nin} = 0; NOT EXISTS сравнивает построчно и NULL не мешает: "
                f"{a_nex} = {n_nex}")
    else:
        trap = (f"строки с пустым {fk} имеют другой статус и отбрасываются фильтром подзапроса, NULL в список не "
                f"попадает, поэтому NOT IN и NOT EXISTS совпадают: {n_nex}")
    expl = (f"В подзапросе только события '{good}'; с ними связаны id {hit_txt} — {a_in} = {n_in} (IN находит "
            f"совпадения и при NULL в списке). Дальше: {trap}. Ответ: «{out}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"pids": pids, "events": ev, "null_passes": null_passes}, language="sql",
                          files={"setup.sql": setup})
