"""frontend.strategy.principal_rendering_mix_mcq — mcq_concept (Principal, короткое): способ отрисовки страницы по цене.

Для одного типа страниц выбирают способ отрисовки: клиентский (CSR), серверный на каждый запрос (SSR), статическую
генерацию с периодическим обновлением (ISR, обновление раз в T минут) или серверный на краю сети (edge SSR).
У каждого — LCP (p75) и цена обслуживания за 1 млн просмотров. Каждые 100 мс LCP сверх 1,0 с стоят x % выручки
страниц. У ISR страница устаревает: данные меняются раз в U минут, обновление — раз в T минут (T ≤ U), доля
просмотров устаревшей версии = T / (2U); каждый такой просмотр стоит s ₽ (неверная цена или наличие — отмены).
Годовая цена = обслуживание + потеря выручки от LCP + цена устаревших просмотров.

Ловушки: «самый быстрый LCP», «самое дешёвое обслуживание», ISR без цены устаревания. Верный способ распределён
поровну по четырём и отличается хотя бы от двух ловушек.
Ключ проверяется исполнением: программа проигрывает период изменения данных по минутам для каждого сдвига фазы
обновления (доля устаревших просмотров считается, а не берётся из формулы) и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "frontend.strategy.principal_rendering_mix_mcq"

CONTEXTS = [("карточка товара", "цены и остатки"), ("страница рейса", "цены и наличие мест"),
            ("карточка отеля", "цены и свободные номера"), ("страница мероприятия", "наличие билетов"),
            ("карточка автомобиля", "цена и статус объявления"), ("страница тарифа", "условия и цены"),
            ("карточка квартиры", "цена и статус брони")]
NAMES = {"csr": "клиентская отрисовка (CSR)", "ssr": "серверная отрисовка на каждый запрос (SSR)",
         "isr": "статическая генерация с обновлением (ISR)", "edge": "серверная отрисовка на краю сети (edge SSR)"}
ORDER = ["csr", "ssr", "isr", "edge"]

PROGRAM = """opts = __OPTS__
plans = {plans!r}        # подпись -> (LCP мс, цена за 1 млн просмотров, млн ₽; обновление ISR, мин или None)
PV, W, x, s, U = {PV}, {W}, {x}, {s}, {U}
cost = {{}}
for label, (lcp, price, T) in plans.items():
    stale = 0.0
    if T:
        total = 0.0
        for j in range(T):                      # сдвиг первого обновления после изменения данных
            first_regen = j + 0.5               # данные изменились в минуту 0; обновления — first_regen, +T, …
            minutes_stale = 0.0
            for minute in range(U):             # сколько каждой минуты периода показывалась старая версия
                minutes_stale += min(1.0, max(0.0, first_regen - minute))
            total += minutes_stale / U
        stale = total / T
    loss_lcp = W * x / 100 * max(0, lcp - 1000) / 100
    cost[label] = PV * price + loss_lcp + PV * 1e6 * stale * s / 1e6
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _cost(lcp, price, T, PV, W, x, s, U, stale_on=True):
    stale = T / (2 * U) if (T and stale_on) else 0.0
    return PV * price + W * x / 100 * max(0, lcp - 1000) / 100 + PV * stale * s


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    page, data = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        PV = rng.choice([50, 100, 200, 400])                    # млн просмотров в год
        W = rng.choice([500, 1000, 2000, 4000])                 # млн ₽ выручки этих страниц в год
        x = rng.choice([0.5, 1.0, 1.5])                         # % выручки за 100 мс сверх 1,0 с
        s = rng.choice([0.5, 1, 2, 4])                          # ₽ за просмотр устаревшей версии
        U = rng.choice([30, 60, 120, 240])                      # данные меняются раз в U минут
        T = rng.choice([t for t in (5, 10, 15, 30, 60) if 2 * t <= U])
        lcp = {"csr": rng.choice([2200, 2600, 3000]), "ssr": rng.choice([1500, 1700, 1900]),
               "isr": rng.choice([1000, 1100, 1200]), "edge": rng.choice([1200, 1300, 1400])}
        price = {"csr": rng.choice([0.02, 0.04]), "ssr": rng.choice([0.3, 0.5, 0.8]),
                 "isr": rng.choice([0.03, 0.05]), "edge": rng.choice([0.6, 1.0, 1.5])}
        Tm = {"csr": None, "ssr": None, "isr": T, "edge": None}
        a = (PV, W, x, s, U)
        full = {k: _cost(lcp[k], price[k], Tm[k], *a) for k in ORDER}
        good = _argmin(full)
        if good != target:
            continue
        no_stale = _argmin({k: _cost(lcp[k], price[k], Tm[k], *a, stale_on=False) for k in ORDER})
        cheapest = min(ORDER, key=lambda k: (price[k], ORDER.index(k)))
        fastest = min(ORDER, key=lambda k: lcp[k])
        if no_stale is None:
            continue
        need = 1 if good in (cheapest, fastest) else 2
        if sum(t != good for t in (cheapest, fastest, no_stale)) >= need:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    rows = "\n".join(f"• {NAMES[k][0].upper() + NAMES[k][1:]}: LCP (p75) {fmt_num(lcp[k] / 1000, 1)} с, обслуживание "
                     f"{fmt_num(price[k], 2)} млн ₽ за 1 млн просмотров" +
                     (f"; страница обновляется раз в {T} {plural(T, 'минуту', 'минуты', 'минут')}" if k == "isr" else "")
                     for k in ORDER)
    intro = rng.choice([
        f"Вы — главный инженер фронтенда. Для страниц «{page}» нужно выбрать способ отрисовки на год.",
        f"Страницы «{page}» дают заметную долю выручки, и спор о способе отрисовки дошёл до вас как до главного "
        f"инженера фронтенда.",
        f"Архитектурный совет поручил главному инженеру фронтенда выбрать способ отрисовки страниц «{page}».",
    ])
    stem = (f"{intro} Просмотров ≈ {PV} млн в год, выручка этих страниц ≈ {fmt_num(W, 0)} млн ₽ в год; по "
            f"экспериментам каждые 100 мс LCP сверх 1,0 с стоят {fmt_num(x, 1)} % этой выручки. На странице — "
            f"{data}; они меняются в среднем раз в {U} {plural(U, 'минуту', 'минуты', 'минут')}, просмотр устаревшей "
            f"версии обходится в {fmt_num(s, 1)} ₽ (отмены и обращения в поддержку). "
            f"Моменты обновления статической версии с моментами изменения данных не связаны. Варианты:\n{rows}\n\n"
            "Какой способ отрисовки даёт минимальную годовую цену (обслуживание, потеря выручки от LCP и устаревшие "
            "просмотры)?")
    expl = (f"Цена = просмотры × цена обслуживания + выручка × {fmt_num(x, 1)} % × (LCP − 1,0 с) / 100 мс + у ISR "
            f"просмотры × T / (2U) × s (доля устаревших — {fmt_num(100 * T / (2 * U), 1)} %). Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Ловушки: самый быстрый — {NAMES[fastest]}, самый дешёвый — {NAMES[cheapest]}, "
            f"без цены устаревания — {NAMES[no_stale]}.")
    program = PROGRAM.format(plans={NAMES[k]: (lcp[k], price[k], Tm[k]) for k in ORDER}, PV=PV, W=W, x=x, s=s, U=U)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=page, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"PV": PV, "W": W, "x": x, "s": s, "U": U, "T": T, "good": good, "no_stale": no_stale,
                               **{f"lcp_{k}": lcp[k] for k in ORDER}, **{f"p_{k}": price[k] for k in ORDER}},
                       note="Ответ проверяется программой: поминутный проигрыш устаревания при всех сдвигах фазы.")
