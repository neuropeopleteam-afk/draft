"""security.audit.t21_sql_failed_logins_output — predict_output (набор t21, порог Стажёра): неудачные входы из
журнала — `WHERE ok = 0 AND ts >= '<дата>' ORDER BY ts DESC LIMIT n` (SQLite).

Журнал входов (id, учётная запись, время ГГГГ-ММ-ДД ЧЧ:ММ строкой, признак успеха 0/1) показан в условии. Запрос
для отчёта SOC отбирает неудачные входы начиная с границы, ставит новые первыми и берёт n строк. Ловушки чтения:
граница `>=` на строке ISO — при границе-дате «2026-10-14» входят ВСЕ записи этого дня (строка «2026-10-14 00:20»
длиннее и потому больше), запись накануне в 23:5x — нет; при границе-времени запись ровно на границе входит;
успешные входы (ok = 1) отсеиваются; ORDER BY ts DESC — от новых к старым, LIMIT n применяется после фильтра и
сортировки (в части вариантов строк меньше n — LIMIT ничего не отрезает). Ключ — независимая модель (сравнение
кортежей «день, минута» и сортировка в генераторе); проверка — исполнение показанного запроса в песочнице sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "security.audit.t21_sql_failed_logins_output"

CTX = [("онлайн-банк", "Аналитик SOC готовит отчёт по журналу входов в онлайн-банк: запрос отбирает неудачные входы.",
        ["anna.k", "admin", "ivan77", "olga", "petrov", "kate_m"]),
       ("VPN-шлюз", "Дежурный инженер по безопасности разбирает журнал VPN-шлюза: запрос отбирает неудачные "
                    "подключения сотрудников.",
        ["s.orlov", "vpn_svc", "m.ivanova", "admin", "d.popov", "guest"]),
       ("админка CMS", "После жалобы на подбор пароля к админке сайта аналитик смотрит журнал входов: запрос "
                       "отбирает неудачные попытки.",
        ["admin", "editor", "root", "seo_team", "manager", "test"]),
       ("SSH-бастион", "Журнал входов на SSH-бастион выгружен в базу; для разбора инцидента запрос отбирает "
                       "неудачные входы.",
        ["root", "deploy", "backup", "ubuntu", "oracle", "git"]),
       ("почтовый сервер", "Почтовый сервер пишет входы по IMAP в журнал; для отчёта о подборе паролей запрос "
                           "отбирает неудачные входы.",
        ["info", "hr", "buh", "director", "sales", "noreply"])]
TABLES = [("logins", "login", "ok"), ("auth_log", "account", "success"), ("sign_in_log", "username", "ok"),
          ("login_events", "user_name", "ok")]


def _ts(month: int, day: int, minute: int) -> str:
    return f"2026-{month:02d}-{day:02d} {minute // 60:02d}:{minute % 60:02d}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem0, users = rng.choice(CTX)
    T, ucol, okcol = rng.choice(TABLES)
    month = rng.choice([9, 10])                      # журнал за прошедшие дни: сентябрь или начало октября
    D = rng.randint(4, 28) if month == 9 else rng.randint(4, 19)
    by_date = rng.random() < 0.6
    cut = rng.random() < 0.55
    for _ in range(500):
        if cut:
            n = rng.choice([2, 3])
            m = n + rng.choice([1, 2])
        else:
            n = rng.choice([3, 4])
            m = n - 1
        s_after = rng.choice([1, 2])
        p = rng.choice([2, 3])
        if not 8 <= p + m + s_after <= 10:
            continue
        # граница и пограничные записи
        if by_date:
            bound_key = (D, 0)
            bound_txt = f"2026-{month:02d}-{D:02d}"
            edge_in = (D, rng.randint(0, 6 * 60 + 59))                   # тот же день, раннее утро — входит
            edge_out = (D - 1, rng.randint(22 * 60 + 30, 23 * 60 + 59))  # накануне поздно вечером — нет
        else:
            hm = rng.randint(8 * 60, 15 * 60) // 5 * 5
            bound_key = (D, hm)
            bound_txt = _ts(month, D, hm)
            edge_in = (D, hm)                                            # ровно на границе — входит
            edge_out = (D, hm - rng.randint(3, 40))                      # чуть раньше границы — нет
        # раньше границы: p записей, последняя — неудача edge_out
        before = sorted({(D - 1, rng.randint(6 * 60, 21 * 60)) for _k in range(p - 1)})
        if len(before) != p - 1:
            continue
        before.append(edge_out)
        # после границы: edge_in (неудача) + ещё m - 1 неудач и s_after успехов
        hi = (D + 1, 23 * 60 + 59)
        after = set()
        while len(after) < m - 1 + s_after:
            day = rng.choice([D, D + 1, D + 1]) if by_date else rng.choice([D, D + 1])
            k = (day, rng.randint(0, 23 * 60 + 59))
            if edge_in < k <= hi:
                after.add(k)
        after = sorted(after)
        ok_pos = set(rng.sample(range(len(after)), s_after))
        fails_after = [edge_in] + [k for i, k in enumerate(after) if i not in ok_pos]
        newest_fail = sorted(fails_after, reverse=True)
        if cut:
            # хотя бы один успешный вход новее n-й выбранной неудачи — без ok = 0 ответ другой
            nth = newest_fail[n - 1]
            if not any(k > nth for i, k in enumerate(after) if i in ok_pos):
                continue
        # неудача накануне/до границы и хотя бы один успех до границы
        ok_before = rng.sample(range(p - 1), rng.choice([0, 1])) if p > 1 else []
        break
    else:
        raise RuntimeError("t21_sql_failed_logins: не собрался журнал")
    events = ([(k, 0 if i not in ok_before else 1) for i, k in enumerate(before[:-1])] + [(before[-1], 0)]
              + [(edge_in, 0)] + [(k, 1 if i in ok_pos else 0) for i, k in enumerate(after)])
    events.sort(key=lambda e: e[0])
    rid = rng.randint(100, 900)
    rows = []
    target = rng.choice(users)
    for (day, minute), ok in events:
        rid += rng.randint(1, 3)
        user = target if (not ok and rng.random() < 0.5) else rng.choice(users)
        rows.append((rid, user, _ts(month, day, minute), ok))
    # независимая модель: фильтр по кортежу (день, минута), сортировка по убыванию, первые n
    keyed = [(r, ev[0]) for r, ev in zip(rows, events)]
    sel = [r for r, k in keyed if r[3] == 0 and k >= bound_key]
    sel_sorted = [r for r, _k in sorted(((r, k) for r, k in keyed if r[3] == 0 and k >= bound_key),
                                        key=lambda x: x[1], reverse=True)]
    res = sel_sorted[:n]
    cols_kind = rng.choice(["user_ts", "user_ts", "id_user"])
    sel_cols = f"{ucol}, ts" if cols_kind == "user_ts" else f"id, {ucol}"
    conds = [f"{okcol} = 0", f"ts >= '{bound_txt}'"]
    if rng.random() < 0.4:
        conds.reverse()
    if rng.random() < 0.5:
        where = f"WHERE {conds[0]} AND {conds[1]}\n"
    else:
        where = f"WHERE {conds[0]}\n  AND {conds[1]}\n"
    code = (f"SELECT {sel_cols}\n"
            f"FROM {T}\n"
            + where +
            "ORDER BY ts DESC\n"
            f"LIMIT {n};")
    if cols_kind == "user_ts":
        out = "\n".join(f"{r[1]}|{r[2]}" for r in res)
    else:
        out = "\n".join(f"{r[0]}|{r[1]}" for r in res)
    headers = ["id", ucol, "ts", okcol]
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {ucol} TEXT NOT NULL, ts TEXT NOT NULL, "
             f"{okcol} INTEGER NOT NULL);\n" + sql_inserts(T, headers, rows) + "\n")
    stem = f"{stem0}\n\n{T}\n{text_table(headers, rows)}"
    r_in = next(r for r, k in keyed if k == edge_in)
    r_out = next(r for r, k in keyed if k == edge_out)
    if by_date:
        edge_txt = (f"граница — дата '{bound_txt}': запись id {r_in[0]} ({r_in[2]}) входит — строка с той же датой "
                    f"и временем длиннее и потому «больше» границы, а id {r_out[0]} ({r_out[2]}) накануне — нет")
    else:
        edge_txt = (f"граница — момент '{bound_txt}': запись id {r_in[0]} ровно на границе входит (>=), а id "
                    f"{r_out[0]} ({r_out[2]}) раньше границы — нет")
    n_ok = sum(1 for r, k in keyed if r[3] == 1 and k >= bound_key)
    lim_txt = (f"LIMIT {n} оставляет первые {n} из {len(sel)} строк — уже после фильтра и сортировки, то есть "
               f"самые новые" if len(sel) > n else
               f"подходящих строк {len(sel)} — меньше {n}, и LIMIT ничего не отрезает")
    expl = (f"Отбор: {okcol} = 0 и ts >= '{bound_txt}' — id {', '.join(str(r[0]) for r in sel)}; {edge_txt}; "
            f"успешные входы после границы ({n_ok}) отсеивает условие {okcol} = 0. ORDER BY ts DESC ставит новые "
            f"записи первыми, {lim_txt}. Ответ:\n{out}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"rows": rows, "bound": bound_txt, "limit": n, "cut": cut}, language="sql",
                          files={"setup.sql": setup})
