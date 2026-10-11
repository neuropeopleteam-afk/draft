"""backend.strategy.principal_integration_style_mcq — mcq_concept (Principal, короткое): стиль интеграции цепочки.

Оформление заказа синхронно вызывает k сервисов с доступностями Aᵢ; часть вызовов критична, часть — нет.
Четыре варианта:
  * синхронная цепочка как сейчас (без доплаты): заказ теряется, если недоступен любой сервис — 1 − ΠAᵢ;
  * синхронно, но некритичные вызовы — с запасным ответом: теряется, только если недоступен критичный; доплата E_fb;
  * асинхронно через очередь с компенсациями (сага): заказ принят, если доступна очередь (A_q); каждый заказ, в
    цепочке которого был отказ (1 − ΠAᵢ), требует компенсации или ручного разбора стоимостью H; доплата E_saga;
  * объединить два наименее доступных сервиса с оформлением заказа: их отказы исчезают; доплата E_merge в год.
Годовая цена = доплата + потерянные заказы × маржа (+ компенсации у саги).

Ловушки: «без доплаты», «асинхронно — лучшая практика», сага без цены компенсаций, сложение недоступностей вместо
произведения доступностей (даёт тот же ответ редко — в счёт не идёт). Генератор подбирает числа так, что верный
вариант распределён поровну по четырём и отличается хотя бы от двух ловушек (если верна сама ловушка «без доплаты»
или «сага» — хотя бы от одной).
Ключ проверяется исполнением: программа перебирает все 2^k сочетаний «сервис доступен / нет» с весами вероятностей
(а не формулу произведения), считает потери каждого варианта и печатает букву минимума.
"""
from __future__ import annotations


from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.strategy.principal_integration_style_mcq"

CONTEXTS = {
    "интернет-магазин": ["склад", "цены", "платёжный шлюз", "доставка", "рекомендации", "лояльность"],
    "сервис доставки еды": ["рестораны", "курьеры", "оплата", "промокоды", "отзывы", "геокодер"],
    "банк": ["скоринг", "лимиты", "процессинг", "антифрод", "уведомления", "кэшбэк"],
    "сервис бронирования отелей": ["наличие номеров", "тарифы", "оплата", "лояльность", "отзывы", "страховка"],
    "авиабилеты": ["расписание", "тарифы", "оплата", "места", "багаж", "страховка"],
    "аптека онлайн": ["остатки", "рецепты", "оплата", "доставка", "бонусы", "аналоги"],
}
NAMES = {"sync": "синхронная цепочка как сейчас",
         "fallback": "синхронно, некритичные вызовы с запасным ответом",
         "saga": "асинхронно через очередь с компенсациями (сага)",
         "merge": "объединить два наименее доступных сервиса с оформлением"}
ORDER = ["sync", "fallback", "saga", "merge"]

PROGRAM = """from itertools import product
opts = __OPTS__
svc = {svc!r}            # сервис -> (доступность, критичный)
merged = {merged!r}
O, M, A_q, H = {O}, {M}, {A_q}, {H}
extra = {extra!r}
lost = {{k: 0.0 for k in extra}}
names = list(svc)
for state in product([True, False], repeat=len(names)):
    w = 1.0
    for n, up in zip(names, state):
        w *= svc[n][0] if up else 1 - svc[n][0]
    down = [n for n, up in zip(names, state) if not up]
    lost["sync"] += w * (1.0 if down else 0.0) * M
    lost["fallback"] += w * (1.0 if any(svc[n][1] for n in down) else 0.0) * M
    lost["merge"] += w * (1.0 if [n for n in down if n not in merged] else 0.0) * M
    lost["saga"] += w * (1.0 if down else 0.0) * H
lost["saga"] += (1 - A_q) * M
cost = {{k: extra[k] + O * lost[k] for k in extra}}
labels = {labels!r}
best = labels[min(cost, key=cost.get)]
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _prod(xs):
    p = 1.0
    for x in xs:
        p *= x
    return p


def _costs(svc, merged, O, M, A_q, H, extra, with_comp=True):
    all_up = _prod(a for a, _c in svc.values())
    crit_up = _prod(a for a, c in svc.values() if c)
    rest_up = _prod(a for n, (a, _c) in svc.items() if n not in merged)
    return {"sync": extra["sync"] + O * (1 - all_up) * M,
            "fallback": extra["fallback"] + O * (1 - crit_up) * M,
            "saga": extra["saga"] + O * ((1 - A_q) * M + ((1 - all_up) * H if with_comp else 0)),
            "merge": extra["merge"] + O * (1 - rest_up) * M}


def _argmin(d, rel=0.04):
    s = sorted(d.values())
    return min(d, key=d.get) if s[1] - s[0] >= rel * s[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CONTEXTS))
    target = rng.choice(ORDER)
    for _ in range(60000):
        k = rng.choice([4, 5])
        names = rng.sample(CONTEXTS[ctx], k)
        svc = {n: (rng.choice([0.99, 0.995, 0.998, 0.999, 0.9995]), False) for n in names}
        crit = rng.sample(names, rng.choice([1, 2]))
        svc = {n: (a, n in crit) for n, (a, _c) in svc.items()}
        merged = sorted(names, key=lambda n: (svc[n][0], names.index(n)))[:2]
        if svc[merged[1]][0] == sorted(a for a, _c in svc.values())[2]:
            continue                                    # «два наименее доступных» должны определяться однозначно
        O = rng.choice([2, 5, 10, 20])                  # млн заказов в год
        M = rng.choice([300, 500, 800, 1200])           # ₽ маржи с заказа
        A_q = rng.choice([0.999, 0.9995, 0.9999])
        H = rng.choice([100, 200, 400, 800])            # ₽ на компенсацию или ручной разбор
        extra = {"sync": 0, "fallback": rng.choice([10, 20, 40]), "saga": rng.choice([30, 60, 90]),
                 "merge": rng.choice([20, 40, 80])}      # млн ₽ в год
        Om = O * 1e6 / 1e6                               # млн заказов × ₽ = млн ₽
        full = _costs(svc, merged, Om, M, A_q, H, extra)
        good = _argmin(full)
        if good != target:
            continue
        no_comp = _argmin(_costs(svc, merged, Om, M, A_q, H, extra, with_comp=False))
        if no_comp is None:
            continue
        traps = ("sync", "saga", no_comp)
        if sum(t != good for t in traps) >= (1 if good in ("sync", "saga") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    rows = "\n".join(f"• «{n}» — доступность {fmt_num(100 * svc[n][0], 2).rstrip('0').rstrip(',')} %, "
                     + ("критичный (без него заказ оформить нельзя)" if svc[n][1] else
                        "некритичный (можно ответить запасным значением)") for n in names)
    intro = rng.choice([
        f"Вы — главный инженер; продукт — {ctx}. Оформление заказа синхронно вызывает {k} сервисов, и потери "
        f"заказов из-за их отказов растут.",
        f"В продукте «{ctx}» оформление заказа — синхронная цепочка из {k} вызовов. Руководство просит главного "
        f"инженера выбрать, как перестроить интеграцию.",
        f"Разбор потерь продукта «{ctx}» показал: заказы теряются из-за отказов сервисов в цепочке оформления "
        f"({k} синхронных вызовов). Решение — за вами как за главным инженером.",
    ])
    stem = (f"{intro} Отказы сервисов независимы:\n{rows}\n"
            f"Заказов ≈ {O} млн в год, потерянный заказ — {M} ₽ маржи. Варианты:\n"
            f"• {NAMES['sync'].capitalize()}: без доплаты; заказ теряется при отказе любого сервиса.\n"
            f"• {NAMES['fallback'].capitalize()}: доплата {extra['fallback']} млн ₽ в год; заказ теряется только при "
            f"отказе критичного сервиса.\n"
            f"• {NAMES['saga'].capitalize()}: доплата {extra['saga']} млн ₽ в год; заказ принимается, если доступна "
            f"очередь ({fmt_num(100 * A_q, 2).rstrip('0').rstrip(',')} %); каждый заказ, в цепочке которого отказал "
            f"хотя бы один сервис, требует компенсации или ручного разбора — {H} ₽.\n"
            f"• {NAMES['merge'].capitalize()} («{merged[0]}» и «{merged[1]}»): доплата {extra['merge']} млн ₽ в год; "
            f"их отказы исчезают, остальные — как сейчас.\n\n"
            "Какой вариант даёт минимальную ожидаемую годовую цену (доплата, потерянные заказы и компенсации)?")
    expl = ("Доля заказов с отказом в цепочке = 1 − ΠAᵢ (по критичным — для запасного ответа, без объединённых — для "
            "объединения); у саги теряются только заказы при недоступной очереди, но платим компенсации. Итоги: " +
            "; ".join(f"{NAMES[x]} — {fmt_num(full[x], 1)} млн ₽" for x in ORDER) +
            f". Минимум — {NAMES[good]}. Без цены компенсаций вышло бы: {NAMES[no_comp]}.")
    program = PROGRAM.format(svc=svc, merged=merged, O=Om, M=M, A_q=A_q, H=H, extra=extra,
                             labels={x: NAMES[x] for x in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[x] for x in ORDER if x != good], program=program, explanation=expl,
                       params={"O": O, "M": M, "A_q": A_q, "H": H, "good": good, "no_comp": no_comp,
                               "crit": ",".join(crit), "merged": ",".join(merged), **{f"e_{x}": extra[x] for x in extra}},
                       note="Ответ проверяется программой: перебор всех сочетаний доступности сервисов с весами.")
