"""frontend.strategy.principal_api_layer_mcq — mcq_concept (Principal, короткое): как клиент получает данные страницы.

Главная страница собирает данные по цепочке из d зависимых запросов (каждый следующий нуждается в ответе
предыдущего). Доля m просмотров — с мобильных сетей (задержка r_m мс на круг), остальные — с проводных (r_d мс).
Внутри дата-центра круг стоит r_in мс. Четыре варианта:
  * прямые запросы клиента к сервисам — d кругов по сети клиента, без доплаты;
  * слой агрегации для фронтенда (BFF) — один круг клиента + d внутренних кругов; сопровождение C_bff;
  * общий шлюз GraphQL — один круг клиента + d внутренних кругов + накладные расходы разбора g мс; платформа C_gql;
  * данные собираются на сервере вместе с HTML — кругов клиента за данными нет, но HTML приходит позже на d
    внутренних кругов + рендер s мс; серверы C_ssr.
Каждые 100 мс LCP стоят x % выручки W; добавка усредняется по просмотрам. Годовая цена = доплата + потеря выручки.

Ловушки: «меньше всего кругов клиента» (сборка на сервере), «без нового слоя» (прямые запросы) и расчёт по проводной
сети (без мобильной доли). Верный вариант распределён поровну по четырём и отличается хотя бы от двух ловушек (если
верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа проходит цепочку запросов для
каждого варианта и каждого типа сети (кто делает очередной круг — клиент или сервер), суммирует задержку и печатает
букву минимума цены.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "frontend.strategy.principal_api_layer_mcq"

CONTEXTS = [("главная маркетплейса", "профиль → рекомендации → цены и остатки"),
            ("карточка заказа", "заказ → доставка → курьер на карте"),
            ("лента новостей", "подписки → посты → реакции"),
            ("страница бронирования", "отель → номера → тарифы"),
            ("личный кабинет банка", "клиент → счета → последние операции"),
            ("страница курса", "ученик → программа → прогресс по урокам")]
NAMES = {"direct": "прямые запросы клиента к сервисам", "bff": "слой агрегации для фронтенда (BFF)",
         "gql": "общий шлюз GraphQL", "ssr": "сборка данных на сервере вместе с HTML"}
ORDER = ["direct", "bff", "gql", "ssr"]

PROGRAM = """opts = __OPTS__
d, m, r_m, r_d, r_in = {d}, {m}, {r_m}, {r_d}, {r_in}
g, s, W, x = {g}, {s}, {W}, {x}
plans = {plans!r}     # подпись -> (вариант, доплата млн ₽ в год)
cost = {{}}
for label, (plan, price) in plans.items():
    avg = 0.0
    for share, rtt in ((m, r_m), (1 - m, r_d)):
        t = 0.0
        if plan in ("bff", "gql"):
            t += rtt                                   # один круг клиента до слоя
        for step in range(d):                          # цепочка зависимых запросов
            t += rtt if plan == "direct" else r_in     # круг делает клиент или сервер
        if plan == "gql":
            t += g
        if plan == "ssr":
            t += s
        avg += share * t
    cost[label] = price + W * x / 100 * avg / 100
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(v, rel=0.04):
    o = sorted(v.values())
    return min(v, key=v.get) if o[1] - o[0] >= rel * o[1] else None


def _costs(d, m, r_m, r_d, r_in, g, s, W, x, price):
    def ms(rtt):
        return {"direct": d * rtt, "bff": rtt + d * r_in, "gql": rtt + d * r_in + g, "ssr": d * r_in + s}
    a, b = ms(r_m), ms(r_d)
    return {k: price[k] + W * x / 100 * (m * a[k] + (1 - m) * b[k]) / 100 for k in ORDER}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, chain = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    d = len(chain.split(" → "))
    for _ in range(80000):
        m = rng.choice([0.3, 0.5, 0.7, 0.85])
        r_m, r_d = rng.choice([100, 150, 250]), rng.choice([20, 30, 50])
        r_in = rng.choice([2, 5, 10])
        g, s = rng.choice([10, 20, 40]), rng.choice([80, 150, 250])
        W, x = rng.choice([300, 1000, 3000]), rng.choice([0.5, 1.0])
        price = {"direct": 0, "bff": rng.choice([3, 6, 10]), "gql": rng.choice([2, 4, 8]),
                 "ssr": rng.choice([5, 10, 20])}
        full = _costs(d, m, r_m, r_d, r_in, g, s, W, x, price)
        good = _argmin(full)
        if good != target:
            continue
        wired = _argmin(_costs(d, 0.0, r_m, r_d, r_in, g, s, W, x, price))
        if wired is None:
            continue
        traps = ("ssr", "direct", wired)
        if sum(t != good for t in traps) >= (1 if good in ("ssr", "direct") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    dw = plural(d, "запрос", "запроса", "запросов")
    rows = [f"• {cap(NAMES['direct'])}: каждый запрос цепочки — круг по сети клиента; без доплаты.",
            f"• {cap(NAMES['bff'])}: клиент делает один круг до слоя, цепочку слой проходит внутри дата-центра; "
            f"сопровождение — {price['bff']} млн ₽ в год.",
            f"• {cap(NAMES['gql'])}: один круг клиента, цепочка — внутри, плюс {g} мс на разбор и планирование "
            f"запроса; платформа — {price['gql']} млн ₽ в год.",
            f"• {cap(NAMES['ssr'])}: клиенту не нужны круги за данными, но HTML приходит позже — на цепочку внутри "
            f"дата-центра и {s} мс рендера; серверы — {price['ssr']} млн ₽ в год."]
    intro = rng.choice([
        f"Вы — главный инженер фронтенда. Страница «{ctx}» медленно показывает главное, и нужно выбрать, как клиент "
        f"получает её данные.",
        f"Для страницы «{ctx}» архитектурный совет выбирает схему получения данных; решение — за вами как за главным "
        f"инженером фронтенда.",
        f"Страница «{ctx}» теряет выручку на медленной загрузке; главному инженеру фронтенда нужно выбрать схему "
        f"запросов за данными.",
    ])
    stem = (f"{intro} Данные собираются цепочкой из {d} зависимых {dw} ({chain}): каждый следующий нуждается в ответе "
            f"предыдущего. {fmt_num(100 * m, 0)} % просмотров — с мобильных сетей (круг ≈ {r_m} мс), остальные — с "
            f"проводных (≈ {r_d} мс); круг внутри дата-центра ≈ {r_in} мс. Выручка ≈ {fmt_num(W, 0)} млн ₽ в год, "
            f"каждые 100 мс LCP стоят {fmt_num(x, 1)} % выручки (добавка усредняется по просмотрам). Варианты:\n" +
            "\n".join(rows) + "\n\nКакой вариант даёт минимальную годовую цену (доплата и потеря выручки от LCP)?")
    expl = (f"Задержка: прямые — {d} × круг клиента; BFF — круг клиента + {d} × {r_in} мс; GraphQL — то же + {g} мс; "
            f"сборка на сервере — {d} × {r_in} мс + {s} мс. Средняя по долям сетей, цена = доплата + W × x % × "
            f"задержка / 100 мс. Итоги: " + "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. По проводной сети вышло бы: {NAMES[wired]}.")
    program = PROGRAM.format(d=d, m=m, r_m=r_m, r_d=r_d, r_in=r_in, g=g, s=s, W=W, x=x,
                             plans={NAMES[k]: (k, price[k]) for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"d": d, "m": m, "r_m": r_m, "r_d": r_d, "r_in": r_in, "g": g, "s": s, "W": W, "x": x,
                               "good": good, "wired": wired, **{f"price_{k}": price[k] for k in ORDER}},
                       note="Ответ проверяется программой: проход цепочки запросов для каждого варианта и сети.")
