"""common.sql.revenue_report_ob3 — открытая книга: «размножение» строк при JOIN (fan-out)."""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from, sql_inserts)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.sql.revenue_report_ob3"

# P — субъект, O — документ с суммой, X — частичные поступления по документу
CONTEXTS = [
    dict(P="customers", p="c", O="orders", o="o", ofk="customer_id", X="payments", x="p",
         xfk="order_id", what="заказов", got="оплат", c1="ordered", c2="paid", ctx="магазин",
         who="клиенту", docs="заказы"),
    dict(P="tenants", p="t", O="invoices", o="i", ofk="tenant_id", X="transfers", x="tr",
         xfk="invoice_id", what="выставленных счетов", got="поступивших платежей", c1="billed",
         c2="received", ctx="аренда", who="арендатору", docs="выставленные счета"),
    dict(P="students", p="s", O="contracts", o="k", ofk="student_id", X="installments", x="n",
         xfk="contract_id", what="договоров", got="внесённых взносов", c1="contracted",
         c2="collected", ctx="образование", who="студенту", docs="договоры"),
    dict(P="partners", p="pr", O="deals", o="d", ofk="partner_id", X="settlements", x="st",
         xfk="deal_id", what="сделок", got="расчётов", c1="deal_total", c2="settled",
         ctx="B2B-продажи", who="партнёру", docs="сделки"),
]
NAMES = ["Анна", "Борис", "Вера", "Глеб", "Дина", "Егор", "Жанна", "Илья"]
DISTRACTORS = ["distinct", "inner_join", "max_amount", "avg_trick"]
NEAR_MISSES = ["agg_inner", "agg_by_parent", "agg_no_group"]


def _query(C, kind="buggy"):
    p, o, x = C["p"], C["o"], C["x"]
    s1 = f"SUM({o}.amount)"
    if kind == "distinct":
        s1 = f"SUM(DISTINCT {o}.amount)"
    elif kind == "max_amount":
        s1 = f"MAX({o}.amount)"
    elif kind == "avg_trick":
        s1 = f"COUNT(DISTINCT {o}.id) * AVG({o}.amount)"
    if kind in ("agg_inner", "agg_by_parent", "agg_no_group"):
        # почти верные варианты с подзапросом (версия 2): ключ больше не единственный с агрегацией
        if kind == "agg_by_parent":
            sub = (f"  SELECT o2.{C['ofk']}, SUM({x}.amount) AS total\n  FROM {C['X']} {x}\n"
                   f"  JOIN {C['O']} o2 ON o2.id = {x}.{C['xfk']}\n  GROUP BY o2.{C['ofk']}\n"
                   f") agg ON agg.{C['ofk']} = {p}.id\n")
        else:
            grp = "" if kind == "agg_no_group" else f"  GROUP BY {C['xfk']}\n"
            sub = (f"  SELECT {C['xfk']}, SUM(amount) AS total\n  FROM {C['X']}\n{grp}"
                   f") agg ON agg.{C['xfk']} = {o}.id\n")
        join = "JOIN" if kind == "agg_inner" else "LEFT JOIN"
        return (f"SELECT {p}.id, {p}.name, SUM({o}.amount) AS {C['c1']}, SUM(agg.total) AS {C['c2']}\n"
                f"FROM {C['P']} {p}\nJOIN {C['O']} {o} ON {o}.{C['ofk']} = {p}.id\n"
                f"{join} (\n{sub}"
                f"GROUP BY {p}.id, {p}.name\nORDER BY {p}.id;")
    if kind == "good":
        return (f"SELECT {p}.id, {p}.name, SUM({o}.amount) AS {C['c1']}, SUM(agg.total) AS {C['c2']}\n"
                f"FROM {C['P']} {p}\nJOIN {C['O']} {o} ON {o}.{C['ofk']} = {p}.id\n"
                f"LEFT JOIN (\n  SELECT {C['xfk']}, SUM(amount) AS total\n  FROM {C['X']}\n"
                f"  GROUP BY {C['xfk']}\n) agg ON agg.{C['xfk']} = {o}.id\n"
                f"GROUP BY {p}.id, {p}.name\nORDER BY {p}.id;")
    join = "JOIN" if kind == "inner_join" else "LEFT JOIN"
    return (f"SELECT {p}.id, {p}.name, {s1} AS {C['c1']}, SUM({x}.amount) AS {C['c2']}\n"
            f"FROM {C['P']} {p}\nJOIN {C['O']} {o} ON {o}.{C['ofk']} = {p}.id\n"
            f"{join} {C['X']} {x} ON {x}.{C['xfk']} = {o}.id\n"
            f"GROUP BY {p}.id, {p}.name\nORDER BY {p}.id;")


def _ref(parents, docs, parts):
    out = []
    for pid, name in parents:
        ds = [d for d in docs if d[1] == pid]
        if not ds:
            continue
        got = [x[2] for x in parts if any(x[1] == d[0] for d in ds)]
        out.append(f"{pid}|{name}|{sum(d[2] for d in ds)}|{sum(got) if got else 'NULL'}")
    return "\n".join(out)


def _setup(C, parents, docs, parts):
    return (f"CREATE TABLE {C['P']} (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n"
            f"CREATE TABLE {C['O']} (id INTEGER PRIMARY KEY, {C['ofk']} INTEGER NOT NULL, amount INTEGER NOT NULL);\n"
            f"CREATE TABLE {C['X']} (id INTEGER PRIMARY KEY, {C['xfk']} INTEGER NOT NULL, amount INTEGER NOT NULL);\n"
            + sql_inserts(C["P"], ["id", "name"], parents) + "\n"
            + sql_inserts(C["O"], ["id", C["ofk"], "amount"], docs) + "\n"
            + sql_inserts(C["X"], ["id", C["xfk"], "amount"], parts) + "\n")


def _dataset(rng, n_par, fanout: bool):
    docs, parts, did, xid = [], [], 10 * rng.randint(1, 9), 100 * rng.randint(1, 9)
    for pid in range(1, n_par + 1):
        for _ in range(rng.randint(1, 2)):
            did += 1
            docs.append((did, pid, rng.randint(2, 30) * 100))
    for d in docs:
        n = rng.choice([0, 1, 1])
        for _ in range(n):
            xid += 1
            parts.append((xid, d[0], rng.randint(1, d[2] // 100) * 100))
    if fanout:
        d = rng.choice(docs)
        for _ in range(2 - sum(1 for x in parts if x[1] == d[0])):
            xid += 1
            parts.append((xid, d[0], rng.randint(1, max(1, d[2] // 200)) * 100))
    return docs, parts


def _describe(C, docs, parts):
    d = ", ".join(f"({a}, {b}, {c})" for a, b, c in docs)
    x = ", ".join(f"({a}, {b}, {c})" for a, b, c in parts) or "нет строк"
    return f"{C['O']}(id, {C['ofk']}, amount): {d}; {C['X']}(id, {C['xfk']}, amount): {x}"


CONDITIONS = {
    "refunds": dict(
        text=("Добавили таблицу возвратов refunds(id, {xfk}, amount): по одному документу может "
              "быть несколько возвратов, в отчёт нужен столбец refunded. Что произойдёт, если "
              "просто добавить ещё один LEFT JOIN к исправленному запросу, как правильно "
              "построить запрос и как вы это проверите?"),
        criteria=[("multiplication", "Объясняет, что два независимых «один-ко-многим» соединения "
                                     "перемножают строки: m оплат × k возвратов, суммы раздуваются", 0.4),
                  ("preaggregate", "Агрегирует каждую ветку отдельно (подзапрос/CTE по ключу "
                                   "документа) и только потом соединяет; альтернатива — "
                                   "коррелированные подзапросы или UNION ALL с разметкой", 0.35),
                  ("tests", "Проверка: документ с 2 оплатами и 2 возвратами, документ без "
                            "возвратов; сверка итогов с отдельными SUM по каждой таблице", 0.25)],
        strong="""Второй LEFT JOIN к возвратам даёт для документа с m оплатами и k возвратами
            m × k строк: и оплаты, и возвраты, и сумма документа будут умножены. Правильно —
            агрегировать каждую ветку отдельно до соединения: CTE pay = SELECT {xfk},
            SUM(amount) FROM … GROUP BY {xfk}; CTE ref — то же для refunds; затем документы
            LEFT JOIN pay LEFT JOIN ref по ключу документа и группировка по субъекту. Каждая
            таблица после агрегации даёт не больше одной строки на документ, поэтому
            размножения нет. Проверяю на наборе, где у документа 2 оплаты и 2 возврата, а у
            другого возвратов нет; и контрольной сверкой: итог по столбцу refunded равен
            SELECT SUM(amount) FROM refunds, итог paid — сумме по таблице оплат.""",
        medium="""Если добавить ещё один JOIN, строки размножатся и суммы будут неправильными.
            Нужно сначала посчитать сумму возвратов по документу в подзапросе, а потом
            присоединить. Проверить на примере с несколькими возвратами.""",
        weak="""Нужно добавить LEFT JOIN refunds и SUM(refunds.amount), а потом поставить
            DISTINCT, чтобы убрать дубликаты."""),
    "by_month": dict(
        text=("Отчёт нужно строить по месяцам: сумма документов — по месяцу создания документа, "
              "поступления — по месяцу поступления (появились столбцы created_at и paid_at), а "
              "документ может оплачиваться частями в разные месяцы. Почему исправленный запрос "
              "нельзя просто сгруппировать по месяцу, как вы построите отчёт и что проверите?"),
        criteria=[("two_axes", "Понимает, что у сумм разные оси времени: документ относится к "
                               "месяцу создания, каждая оплата — к своему месяцу; один GROUP BY "
                               "по соединённым строкам их смешивает", 0.4),
                  ("construction", "Строит два агрегата по (субъект, месяц) отдельно и соединяет "
                                   "их FULL OUTER JOIN или UNION ALL + GROUP BY; месяцы "
                                   "полуоткрытыми интервалами / date_trunc", 0.35),
                  ("checks", "Проверяет: оплата частями в разные месяцы, месяц без документов, "
                             "но с оплатами, граница месяца и часовой пояс", 0.25)],
        strong="""Сумма документа и поступления живут на разных осях времени: документ, созданный
            в марте, может оплачиваться в марте и апреле. Если сгруппировать соединённые
            строки по месяцу создания, апрельская оплата попадёт в март; если по месяцу
            оплаты — сумма документа размажется по месяцам и задублируется. Поэтому строю два
            независимых агрегата: docs_m = (субъект, date_trunc('month', created_at),
            SUM(amount)) и pays_m = (субъект, date_trunc('month', paid_at), SUM(amount)) — и
            соединяю их FULL OUTER JOIN по (субъект, месяц) с COALESCE, либо UNION ALL с
            последующим GROUP BY. Месяц считаю в часовом поясе бизнеса, границы —
            полуоткрытые. Проверяю: оплата частями в два месяца, месяц только с оплатами,
            платёж 31-го числа в 23:30 по Москве (в UTC это уже другой день).""",
        medium="""Сумма документа и оплаты относятся к разным месяцам, поэтому группировать
            вместе нельзя. Нужно посчитать по месяцам отдельно документы и отдельно оплаты, а
            потом объединить. Проверить на документе, оплаченном в два приёма.""",
        weak="""Достаточно добавить в GROUP BY месяц от created_at, и отчёт будет помесячным."""),
    "big_data": dict(
        text=("Таблицы выросли: 200 млн поступлений и 30 млн документов, отчёт строится 40 минут "
              "и нагружает основную базу. Что вы проверите и что измените, чтобы отчёт "
              "строился быстро и не мешал рабочей нагрузке, не потеряв корректности?"),
        criteria=[("diagnosis", "Начинает с плана выполнения (EXPLAIN ANALYZE): полные сканы, "
                                "сортировки/хеш-агрегаты на диске, отсутствие индекса по ключу "
                                "соединения", 0.3),
                  ("measures", "Предлагает меры: индекс по внешнему ключу поступлений, "
                               "инкрементальные/предагрегированные таблицы или "
                               "материализованное представление, партиционирование по дате, "
                               "расчёт на реплике", 0.45),
                  ("correctness", "Сохраняет корректность: сверка с исходным запросом на "
                                  "срезе данных, контроль свежести предагрегатов и повторных "
                                  "загрузок", 0.25)],
        strong="""Сначала EXPLAIN (ANALYZE, BUFFERS) на реплике: ожидаю последовательные сканы
            200 млн строк, хеш-агрегат с выгрузкой на диск и, возможно, отсутствие индекса по
            {xfk}. Меры по возрастанию стоимости: индекс по ({xfk}) INCLUDE (amount) для
            предагрегации; перенос отчёта на реплику для чтения; ежедневная инкрементальная
            таблица агрегатов по документу (обновляется по новым поступлениям, идемпотентно —
            по id или по водяному знаку времени) или материализованное представление с
            REFRESH CONCURRENTLY; партиционирование поступлений по месяцу, чтобы отчёт за
            период читал только нужные секции. Корректность контролирую сверкой нового отчёта
            со старым запросом на выборке клиентов и периодов и проверкой, что повторная
            загрузка не удваивает суммы.""",
        medium="""Нужно посмотреть EXPLAIN, добавить индекс на внешний ключ в таблице
            поступлений и запускать отчёт на реплике. Можно заранее посчитать суммы по
            документам в отдельной таблице.""",
        weak="""Нужно добавить больше памяти и процессоров серверу базы данных."""),
    "currency": dict(
        text=("Поступления теперь в разных валютах: добавлены столбцы currency и paid_at, курсы "
              "лежат в таблице rates(currency, rate_date, rate). Отчёт нужен в рублях по курсу "
              "на дату поступления. Какие ошибки здесь легко допустить, как вы построите запрос "
              "и как проверите результат?"),
        criteria=[("rate_join", "Соединяет курс по (валюта, дата поступления) и следит, чтобы "
                                "на дату была ровно одна строка курса (иначе снова "
                                "размножение); обрабатывает выходные — последний курс не позже "
                                "даты", 0.4),
                  ("numeric", "Считает в NUMERIC/DECIMAL, округляет в одном месте по "
                              "договорённому правилу, не во float", 0.3),
                  ("tests", "Проверки: уникальность курса на дату, поступление в выходной, "
                            "рубли с курсом 1, сверка с ручным расчётом", 0.3)],
        strong="""Главная ловушка — соединение с rates: если на дату есть два курса (повторная
            загрузка, разные источники), поступление размножится, как и в исходном дефекте;
            если курса на дату нет (выходной), строка потеряется или станет NULL. Поэтому беру
            курс через LATERAL-подзапрос «последний rate_date ≤ дата поступления» с ORDER BY
            rate_date DESC LIMIT 1, а на таблицу rates ставлю уникальный ключ (currency,
            rate_date). Сумму в рублях считаю в NUMERIC и округляю до копеек один раз — после
            суммирования по документу, по согласованному правилу. Рубль либо храню в rates с
            курсом 1, либо обрабатываю COALESCE. Проверяю: дубль курса (должен падать на
            уникальности), поступление в субботу, смешанные валюты по одному документу и
            сверку с ручным расчётом на нескольких записях.""",
        medium="""Нужно присоединить таблицу курсов по валюте и дате и умножить сумму на курс.
            Важно, чтобы курс на дату был один, иначе строки задвоятся. Считать лучше в
            DECIMAL.""",
        weak="""Можно взять средний курс за месяц и умножить на него итоговую сумму."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    C = rng.choice(CONTEXTS)
    n_par = rng.randint(2, 3)
    parents = [(i + 1, n) for i, n in enumerate(rng.sample(NAMES, n_par))]
    code = _query(C)
    repro = _dataset(rng, n_par, True)
    clean = []
    while len(clean) < 3:
        ds = _dataset(rng, n_par, False)
        if any(x for x in ds[1]) and ds not in clean:
            clean.append(ds)
    texts = [_describe(C, *repro)] + [_describe(C, *c) for c in clean]
    if len(set(texts)) < 4:
        raise RuntimeError("совпали описания наборов данных")
    opts1, key1 = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]], step=1)
    # Версия 2 (калибровка 05.10: шаг 2 решался малыми моделями — только верный вариант содержал
    # подзапрос с предагрегацией). Теперь два дистрактора — почти верные подзапросы (INNER JOIN к
    # агрегату, агрегат по субъекту, агрегат без GROUP BY), третий — из прежнего набора.
    chosen = rng.sample(NEAR_MISSES, 2) + [rng.choice(DISTRACTORS)]
    opts2, key2 = make_options(rng, ("Переписать запрос так:", _query(C, "good")),
                               [("Переписать запрос так:", _query(C, d)) for d in chosen], step=2)
    # тестовый набор для шага 2: размножение, равные суммы, документ без поступлений
    t_docs = [(1, 1, 500), (2, 1, 500), (3, 2, 1200), (4, 2, 300), (5, 3, 700)]
    t_parts = [(11, 1, 200), (12, 1, 300), (13, 3, 1200), (14, 5, 100), (15, 5, 100), (16, 5, 500)]
    t_par = [(1, "Анна"), (2, "Борис"), (3, "Вера"), (4, "Глеб")]
    t_setup = _setup(C, t_par, t_docs, t_parts)
    t_ref = _ref(t_par, t_docs, t_parts)
    checks = []
    data_by_text = {texts[0]: repro, **{t: c for t, c in zip(texts[1:], clean)}}
    for o in opts1:
        docs, parts = data_by_text[o.text]
        ref = _ref(parents, docs, parts)
        checks.append(Check(name=f"step1:{o.id}", runner="sqlite", program=code,
                            files={"setup.sql": _setup(C, parents, docs, parts)},
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=ref))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="sqlite", program=o.code,
                            files={"setup.sql": t_setup}, embeds_display_code=False,
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=t_ref))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = {k: (v.format(xfk=C["xfk"]) if isinstance(v, str) else v)
            for k, v in CONDITIONS[cond_name].items()}
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    names = ", ".join(f"{i} — {n}" for i, n in parents)
    stem = (f"Отчёт для финансового отдела ({C['ctx']}) должен показывать по каждому {C['who']}, "
            f"у которого есть {C['docs']}, сумму {C['what']} (`{C['c1']}`) и сумму {C['got']} "
            f"(`{C['c2']}`; если поступлений нет — NULL). Таблицы: `{C['P']}(id, name)`, "
            f"`{C['O']}(id, {C['ofk']}, amount)`, `{C['X']}(id, {C['xfk']}, amount)` — по одному "
            f"документу может быть несколько поступлений. Субъекты в примерах: {names}. "
            f"Пользователи жалуются, что суммы иногда завышены.")
    steps = ob3_steps(
        "Шаг 1. Воспроизведите дефект: на каком наборе данных запрос вернёт неверный отчёт?",
        "Шаг 2. Выберите исправленный запрос, который верен на любых данных.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"distinct": "SUM(DISTINCT) склеит разные документы с равной суммой",
           "inner_join": "JOIN выбросит документы без поступлений и не уберёт размножение",
           "max_amount": "MAX вместо SUM потеряет остальные документы",
           "avg_trick": "AVG по размноженным строкам взвешен числом поступлений",
           "agg_inner": "внутренний JOIN к агрегату выбросит документы без поступлений из суммы документов",
           "agg_by_parent": "агрегат по субъекту присоединён к каждому его документу — поступления "
                            "умножаются на число документов",
           "agg_no_group": "подзапрос без GROUP BY даёт одну строку на всю таблицу — поступления "
                           "достаются одному документу"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation="Дефект: документ с несколькими поступлениями даёт несколько строк "
                               "после LEFT JOIN, и его сумма учитывается многократно. Исправление "
                               "— агрегировать поступления до соединения. Дистракторы: "
                               + "; ".join(why[d] for d in chosen) + f". Шаг 3 — «{cond_name}».")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=C["ctx"], verification="execution",
                         checks=checks, steps=steps, defect_type="join_fanout",
                         params={"distractors": chosen, "condition": cond_name})
