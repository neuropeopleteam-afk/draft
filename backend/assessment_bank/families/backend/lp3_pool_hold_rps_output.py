"""backend.capacity.lp3_pool_hold_rps_output — predict_output: потолок RPS сервиса из-за удержания соединений БД.

Инцидент-классика старших грейдов: часть обработчиков держит соединение из пула, пока ждёт внешний вызов внутри
транзакции. По закону Литтла занятых соединений в среднем = RPS · время удержания. Время удержания на запрос —
сумма по типам запросов: доля · (время SQL + [внешний вызов, если он внутри транзакции]). Потолок — меньшее из
(экземпляры · размер пула) и (max_connections БД − резерв под миграции и администрирование), делённое на среднее
удержание, с целевой загрузкой пула. Наивные ловушки (в условии не названы): не учесть внешний вызов внутри
транзакции; забыть, что суммарный пул всех экземпляров упирается в max_connections БД; не учесть целевую загрузку.
Ключ — целая часть RPS; программа-модель разбирает показанную конфигурацию.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.capacity.lp3_pool_hold_rps_output"

CTX = [("сервис заказов", [("создание заказа", "проверка лимита в антифроде"), ("оплата", "запрос в платёжный шлюз"),
                            ("просмотр заказа", None), ("список заказов", None)]),
       ("сервис бронирования", [("бронирование", "резерв у поставщика"), ("отмена", "уведомление партнёра"),
                                ("карточка брони", None), ("поиск свободных мест", None)]),
       ("сервис выплат", [("заявка на выплату", "проверка реквизитов в банке"), ("статус выплаты", None),
                          ("история выплат", None), ("подтверждение", "запрос в KYC-провайдер")]),
       ("сервис подписок", [("продление", "списание через эквайринг"), ("смена тарифа", None),
                            ("карточка подписки", None), ("отмена", "возврат через эквайринг")])]

CALC = r'''
import re
cfg = {}
rows = []
for l in DATA.splitlines():
    m = re.match(r"^([^|:]+):\s*(\d+)", l)
    if m and "|" not in l:
        cfg[m.group(1).strip()] = int(m.group(2))
    if l.count("|") >= 4 and not l.startswith("тип"):
        p = [x.strip() for x in l.split("|")]
        rows.append((int(p[1].rstrip(" %")), int(p[2]), int(p[3]) if p[3] != "—" else 0, p[4]))
hold = sum(sh / 100 * (sql + (ext if where == "внутри транзакции" else 0)) for sh, sql, ext, where in rows) / 1000
conns = min(cfg["экземпляров сервиса"] * cfg["размер пула на экземпляр"],
            cfg["max_connections БД"] - cfg["резерв соединений БД"])
print(int(conns * cfg["целевая загрузка пула, %"] / 100 / hold))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc, kinds = rng.choice(CTX)
    for _ in range(4000):
        inst = rng.randint(4, 16)
        pool = rng.choice([10, 15, 20, 25, 30, 40])
        maxc = rng.choice([200, 300, 400, 500])
        reserve = rng.choice([10, 20, 30])
        target = rng.choice([60, 70, 75, 80])
        shares = [rng.randint(5, 40) for _ in kinds]
        tot = sum(shares)
        shares = [round(s * 100 / tot) for s in shares]
        shares[-1] = 100 - sum(shares[:-1])
        if min(shares) < 3:
            continue
        rows = []
        for (name, ext_name), sh in zip(kinds, shares):
            sql = rng.choice([3, 4, 5, 6, 8, 10, 12, 15])
            if ext_name:
                ext = rng.choice([40, 60, 80, 120, 150, 200, 250])
                where = rng.choice(["внутри транзакции", "после фиксации"])
            else:
                ext, where = 0, "—"
            rows.append((name, sh, sql, ext, where, ext_name))
        if not any(r[4] == "внутри транзакции" for r in rows):
            continue
        hold = sum(sh / 100 * (sql + (ext if where == "внутри транзакции" else 0)) for _, sh, sql, ext, where, _ in rows) / 1000
        naive_hold = sum(sh / 100 * sql for _, sh, sql, _, _, _ in rows) / 1000
        conns = min(inst * pool, maxc - reserve)
        good = int(conns * target / 100 / hold)
        n1 = int(conns * target / 100 / naive_hold)          # внешний вызов не учтён
        n2 = int(inst * pool * target / 100 / hold)          # потолок БД не учтён
        n3 = int(conns / hold)                               # целевая загрузка не учтена
        if not (50 <= good <= 20000) or len({good, n1, n2, n3}) < 3:
            continue
        if rng.random() < 0.6 and inst * pool <= maxc - reserve:
            continue  # в большинстве вариантов суммарный пул упирается в max_connections БД
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"экземпляров сервиса: {inst}", f"размер пула на экземпляр: {pool}", f"max_connections БД: {maxc}",
             f"резерв соединений БД: {reserve}", f"целевая загрузка пула, %: {target}", "",
             "тип запроса | доля | SQL, мс | внешний вызов, мс | где внешний вызов"]
    for name, sh, sql, ext, where, ext_name in rows:
        lines.append(f"{name} | {sh} % | {sql} | {ext if ext else '—'} | {where}")
    block = "\n".join(lines)
    calls = "; ".join(f"{name} — {ext_name}" for name, _, _, _, _, ext_name in rows if ext_name)
    stem = (f"{svc.capitalize()} на PostgreSQL. После инцидента «запросы висят в ожидании соединения» команда "
            f"просит оценить потолок нагрузки. Конфигурация и профиль запросов — ниже (внешние вызовы: {calls}). "
            "Соединение берётся из пула в начале обработки и возвращается после фиксации транзакции; время "
            "обработки вне SQL и внешних вызовов пренебрежимо. Сколько запросов в секунду сервис выдержит при "
            "целевой загрузке пула, если нагрузка распределена между экземплярами равномерно? Ответ — целое число "
            "(целая часть).")
    traps = [(n1, "не учесть внешний вызов внутри транзакции"), (n2, "не учесть потолок max_connections БД"),
             (n3, "не учесть целевую загрузку")]
    tr = "; ".join(f"{t} — {why}" for t, why in traps if t != good)
    f2 = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
    expl = (f"Удержание соединения на запрос: Σ доля · (SQL + внешний вызов, если он внутри транзакции) = "
            f"{f2(hold * 1000)} мс. Доступно соединений: min({inst} · {pool}, {maxc} − {reserve}) = {conns}. "
            f"По закону Литтла RPS = соединения · загрузка / удержание = {conns} · {target} % / {f2(hold * 1000)} мс "
            f"= {good}. Типичные ошибки: {tr}. Вывод для команды: вынести внешний вызов за транзакцию.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=svc,
                         accept=num_accept(good, ("rps", "RPS", "запросов/с")),
                         params={"inst": inst, "pool": pool, "maxc": maxc, "reserve": reserve, "target": target,
                                 "rows": [list(r[:5]) for r in rows]})
