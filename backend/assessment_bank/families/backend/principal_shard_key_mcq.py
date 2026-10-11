"""backend.strategy.principal_shard_key_mcq — mcq_concept (Principal, короткое): ключ шардирования по полной цене.

Таблицу делят на N шардов. Даны пять типов запросов (доля трафика и поле фильтра) и четыре кандидата в ключ:
сущность (клиент), арендатор (магазин, филиал…), идентификатор записи и география. Запрос с фильтром по ключу
идёт в один шард, остальные — во все N. Распределение ключа неравномерно: у самого крупного значения доля s
(у арендатора и географии — заметная, у клиента — ничтожная, идентификатор — равномерный). Шарды одинаковые и
рассчитаны на самый нагруженный: его доля ≈ s + (1 − s) / N.
Годовая цена = обращения к шардам (Q · Σ доля · число шардов · цена обращения) + N шардов по мощности самого
нагруженного (N · доля самого нагруженного · B).

Ловушки: «по самому частому запросу» (только локальность, без перекоса), «самый равномерный ключ» (только перекос,
без рассылки по шардам), «ключ, по которому фильтрует больше всего типов запросов» (число типов вместо доли трафика).
Верный ключ распределён поровну по четырём кандидатам и отличается хотя бы от двух ловушек.
Ключ проверяется исполнением: программа раскладывает нагрузку по шардам явно (самое крупное значение — в шард 0,
остальное поровну), маршрутизирует каждый тип запроса и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.strategy.principal_shard_key_mcq"

# контекст: таблица, подписи ключей (сущность, арендатор, идентификатор, география), типы запросов по ключам
CONTEXTS = {
    "маркетплейс": ("заказы", {"entity": "покупатель", "tenant": "продавец", "id": "номер заказа", "geo": "регион доставки"},
                    {"entity": ["история заказов покупателя", "корзина и активные заказы покупателя"],
                     "tenant": ["заказы продавца на сборку", "отчёт продавца за месяц"],
                     "id": ["статус заказа по номеру", "трекинг по номеру заказа"],
                     "geo": ["план доставки по региону", "загрузка складов региона"]}),
    "банк": ("операции", {"entity": "клиент", "tenant": "юрлицо-партнёр", "id": "номер операции", "geo": "филиал"},
             {"entity": ["выписка клиента", "лимиты клиента"],
              "tenant": ["реестр платежей партнёра", "сверка с партнёром"],
              "id": ["статус операции по номеру", "оспаривание операции"],
              "geo": ["кассовый отчёт филиала", "инкассация филиала"]}),
    "сервис доставки еды": ("заказы", {"entity": "клиент", "tenant": "ресторан", "id": "номер заказа", "geo": "город"},
                            {"entity": ["история заказов клиента", "повтор заказа"],
                             "tenant": ["очередь заказов ресторана", "выручка ресторана"],
                             "id": ["статус заказа по номеру", "чек по номеру заказа"],
                             "geo": ["карта курьеров города", "спрос по городу"]}),
    "SaaS для бухгалтерии": ("документы", {"entity": "пользователь", "tenant": "организация", "id": "номер документа",
                                           "geo": "налоговая инспекция"},
                             {"entity": ["черновики пользователя", "задачи пользователя"],
                              "tenant": ["документы организации за период", "отчётность организации"],
                              "id": ["документ по номеру", "подпись документа"],
                              "geo": ["выгрузка по инспекции", "сроки сдачи по инспекции"]}),
    "онлайн-кинотеатр": ("просмотры", {"entity": "зритель", "tenant": "правообладатель", "id": "номер сеанса",
                                       "geo": "страна"},
                         {"entity": ["продолжить просмотр", "история зрителя"],
                          "tenant": ["роялти правообладателю", "отчёт правообладателя"],
                          "id": ["сеанс по номеру", "качество сеанса"],
                          "geo": ["лицензии по стране", "нагрузка по стране"]}),
    "платформа такси": ("поездки", {"entity": "пассажир", "tenant": "таксопарк", "id": "номер поездки", "geo": "город"},
                        {"entity": ["поездки пассажира", "способы оплаты пассажира"],
                         "tenant": ["поездки таксопарка за смену", "выплаты таксопарку"],
                         "id": ["поездка по номеру", "жалоба по поездке"],
                         "geo": ["тепловая карта спроса города", "тарифы города"]}),
}
KEYS = ["entity", "tenant", "id", "geo"]

PROGRAM = """opts = __OPTS__
N, Q, c_req, B = {N}, {Q}, {c_req}, {B}
queries = {queries!r}     # (доля трафика, поле фильтра)
top = {top!r}             # ключ -> доля самого крупного значения
labels = {labels!r}
cost = {{}}
for key, label in labels.items():
    shards = [0.0] * N
    shards[0] += top[key]                     # самое крупное значение целиком в одном шарде
    for i in range(N):
        shards[i] += (1 - top[key]) / N       # остальное — поровну
    hot = max(shards)
    touched = sum(share * (1 if field == key else N) for share, field in queries)
    cost[label] = Q * touched * c_req + N * hot * B
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _parts(key, queries, top, N):
    touched = sum(sh * (1 if f == key else N) for sh, f in queries)
    hot = top[key] + (1 - top[key]) / N
    return touched, hot


def _argmin(d, rel=0.04):
    s = sorted(d.values())
    return min(d, key=d.get) if s[1] - s[0] >= rel * s[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CONTEXTS))
    table, labels, qnames = CONTEXTS[ctx]
    target = rng.choice(KEYS)
    for _ in range(80000):
        N = rng.choice([6, 8, 12, 16])
        fields = rng.sample(KEYS, 4) + [rng.choice(KEYS)]
        cuts = sorted(rng.sample(range(1, 20), 4))
        shares = [b - a for a, b in zip([0] + cuts, cuts + [20])]
        queries = [(5 * sh / 100, f) for sh, f in zip(shares, fields)]
        top = {"entity": 0.0, "tenant": rng.choice([0.02, 0.04, 0.06, 0.08]), "id": 0.0,
               "geo": rng.choice([0.05, 0.1, 0.15, 0.2])}
        Q = rng.choice([2, 5, 10, 20])               # млрд запросов в год
        c_req = rng.choice([0.05, 0.1, 0.2])         # млн ₽ за 1 млрд обращений к шарду
        B = rng.choice([20, 40, 80, 160])          # млн ₽ в год: все шарды при равномерной нагрузке
        full, loc, cnt = {}, {}, {}
        for k in KEYS:
            t, h = _parts(k, queries, top, N)
            full[k] = Q * t * c_req + N * h * B
            loc[k] = t
            cnt[k] = sum(1 for _s, f in queries if f == k)
        good = _argmin(full)
        if good != target:
            continue
        by_loc = _argmin(loc, rel=0.01)
        if by_loc is None:
            continue
        cmax = max(cnt.values())
        if list(cnt.values()).count(cmax) != 1:
            continue
        by_cnt = max(cnt, key=cnt.get)
        uniform = "id"
        if sum(t != good for t in (by_loc, by_cnt, uniform)) >= 2 and len({shares[i] for i in range(5)}) >= 3:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    used = {k: 0 for k in KEYS}
    rows = []
    for (sh, f) in queries:
        name = qnames[f][used[f] % len(qnames[f])]
        used[f] += 1
        rows.append(f"• «{name}» — {fmt_num(100 * sh, 0)} % запросов, фильтр по полю «{labels[f]}»")
    skew = (f"у самого крупного значения «{labels['tenant']}» — {fmt_num(100 * top['tenant'], 0)} % строк и "
            f"запросов, у самого крупного значения «{labels['geo']}» — {fmt_num(100 * top['geo'], 0)} %; "
            f"«{labels['entity']}» и «{labels['id']}» распределены равномерно")
    intro = rng.choice([
        f"Вы — главный инженер; продукт — {ctx}. Таблицу «{table}» делят на {N} шардов, нужно выбрать ключ.",
        f"В продукте «{ctx}» таблица «{table}» перестала помещаться в один узел; решено делить её на {N} шардов, "
        f"ключ выбираете вы как главный инженер.",
        f"Архитектурный совет продукта «{ctx}» поручил главному инженеру выбрать ключ шардирования таблицы "
        f"«{table}» на {N} шардов.",
    ])
    stem = (f"{intro} Типы запросов (≈ {Q} млрд в год):\n" + "\n".join(rows) +
            f"\nРаспределение: {skew}. Запрос с фильтром по ключу шардирования идёт в один шард, остальные — во все "
            f"{N}; каждое обращение к шарду стоит {fmt_num(c_req, 2)} млн ₽ за 1 млрд. Шарды одинаковые и "
            f"рассчитаны на самый нагруженный: при равномерной нагрузке все шарды вместе стоят {B} млн ₽ в год, "
            f"цена растёт пропорционально доле самого нагруженного шарда (≈ доля крупнейшего значения + остаток, "
            f"поделённый на {N}).\n\nКакой ключ шардирования даёт минимальную годовую цену (обращения к шардам и "
            f"мощность шардов)?")
    expl = ("Цена = Q × Σ доля × (1 или N шардов) × цена обращения + N × доля самого нагруженного шарда × B. Итоги: " +
            "; ".join(f"«{labels[k]}» — {fmt_num(full[k], 1)} млн ₽" for k in KEYS) +
            f". Минимум — «{labels[good]}». Ловушки: по локальности без перекоса — «{labels[by_loc]}», самый "
            f"равномерный — «{labels['id']}», по числу типов запросов — «{labels[by_cnt]}».")
    program = PROGRAM.format(N=N, Q=Q, c_req=c_req, B=B, queries=queries, top=top,
                             labels={k: f"ключ «{labels[k]}»" for k in KEYS})
    txt = {k: f"ключ «{labels[k]}»" for k in KEYS}
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=txt[good],
                       distractors=[txt[k] for k in KEYS if k != good], program=program, explanation=expl,
                       params={"N": N, "Q": Q, "c_req": c_req, "B": B, "good": good, "by_loc": by_loc,
                               "by_cnt": by_cnt, "fields": ",".join(fields), "shares": "/".join(map(str, shares))},
                       note="Ответ проверяется программой: явная раскладка нагрузки по шардам и маршрутизация запросов.")
