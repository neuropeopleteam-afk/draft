"""common.reliability.principal_region_topology_mcq — mcq_concept (Principal, короткое): топология размещения.

Сервис размещают на год. Отказы: зоны (в среднем k_z раз в год, длительность h_z часов) и региона (с вероятностью
p_r в год, длительность h_r часов). Простой стоит L млн ₽ в час. Четыре варианта:
  * одна зона — дешевле всего (I_1), простаивает при любом отказе;
  * несколько зон одного региона — I_az; переживает отказ зоны, простаивает при отказе региона;
  * резервный регион (активный–пассивный) — I_ap; при отказе региона переключение занимает R часов (вместо h_r);
  * два активных региона — I_aa и сопровождение конфликтов данных C_aa; отказ региона почти не заметен.
Ожидаемая цена = инфраструктура + ожидаемые часы простоя × L.

Ловушки: «максимальная надёжность» (два активных региона), «самое дешёвое размещение» (одна зона) и расчёт без
отказа региона (только отказы зон). Верный вариант распределён поровну по четырём и отличается хотя бы от двух
ловушек (если верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа перечисляет события
года (каждый отказ зоны, отказ региона с вероятностью), для каждого варианта решает, падает ли сервис и на сколько
часов, и печатает букву минимума ожидаемой цены.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "common.reliability.principal_region_topology_mcq"

CONTEXTS = ["платёжный шлюз", "заказ такси", "интернет-банк", "маркетплейс", "доставка еды",
            "онлайн-касса", "бронирование билетов", "запись к врачу"]
NAMES = {"one": "одна зона доступности", "az": "несколько зон одного региона",
         "ap": "резервный регион (активный–пассивный)", "aa": "два активных региона"}
ORDER = ["one", "az", "ap", "aa"]

PROGRAM = """opts = __OPTS__
k_z, h_z, p_r, h_r, R, L = {k_z}, {h_z}, {p_r}, {h_r}, {R}, {L}
infra = {infra!r}      # подпись -> (вариант, инфраструктура и сопровождение, млн ₽ в год)
events = [("зона", 1.0, h_z)] * k_z + [("регион", p_r, h_r)]   # (что отказало, вероятность за год, часы)
cost = {{}}
for label, (plan, price) in infra.items():
    down = 0.0
    for kind, prob, hours in events:
        if plan == "one":
            down += prob * hours
        elif plan == "az":
            down += prob * hours if kind == "регион" else 0
        elif plan == "ap":
            down += prob * min(hours, R) if kind == "регион" else 0
    cost[label] = price + down * L
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def _costs(k_z, h_z, p_r, h_r, R, L, price, with_region=True):
    pr = p_r if with_region else 0
    down = {"one": k_z * h_z + pr * h_r, "az": pr * h_r, "ap": pr * min(h_r, R), "aa": 0.0}
    return {k: price[k] + down[k] * L for k in ORDER}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        k_z = rng.choice([1, 2, 3])
        h_z = rng.choice([2, 4, 6])
        p_r = rng.choice([0.05, 0.1, 0.2, 0.3])
        h_r = rng.choice([12, 24, 48])
        R = rng.choice([1, 2, 4])
        L = rng.choice([0.5, 1, 2, 5, 10])
        I_1 = rng.choice([20, 30, 40])
        price = {"one": I_1, "az": I_1 + rng.choice([3, 6, 10]), "ap": 0, "aa": 0}
        price["ap"] = price["az"] + rng.choice([5, 10, 15, 25])
        C_aa = rng.choice([5, 10, 20])
        price["aa"] = price["ap"] + rng.choice([5, 10, 20]) + C_aa
        full = _costs(k_z, h_z, p_r, h_r, R, L, price)
        good = _argmin(full)
        if good != target:
            continue
        no_reg = _argmin(_costs(k_z, h_z, p_r, h_r, R, L, price, with_region=False))
        if no_reg is None:
            continue
        traps = ("aa", "one", no_reg)
        if sum(t != good for t in traps) >= (1 if good in ("aa", "one") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    hz = plural(h_z, "час", "часа", "часов")
    hr = plural(h_r, "час", "часа", "часов")
    rh = plural(R, "час", "часа", "часов")
    kz = plural(k_z, "раз", "раза", "раз")
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['one'])}: {price['one']} млн ₽ в год; простаивает при отказе зоны и региона.",
            f"• {cap(NAMES['az'])}: {price['az']} млн ₽ в год; отказ зоны переживает, при отказе региона простаивает.",
            f"• {cap(NAMES['ap'])}: {price['ap']} млн ₽ в год; при отказе региона переключение на резерв занимает "
            f"{R} {rh}.",
            f"• {cap(NAMES['aa'])}: {price['aa']} млн ₽ в год с сопровождением конфликтов данных ({C_aa} млн ₽ "
            f"из них); отказы зоны и региона почти не заметны."]
    intro = rng.choice([
        f"Вы — главный инженер; сервис «{ctx}» размещают на год, и нужно выбрать топологию.",
        f"Для сервиса «{ctx}» архитектурный совет выбирает размещение на год; решение — за вами как за главным "
        f"инженером.",
        f"Сервис «{ctx}» переезжает в облако; главному инженеру нужно выбрать топологию размещения на год.",
    ])
    stem = (f"{intro} По статистике провайдера зона доступности отказывает в среднем {k_z} {kz} в год на {h_z} "
            f"{hz}, регион целиком — с вероятностью {fmt_num(100 * p_r, 0)} % в год на {h_r} {hr}. Час простоя "
            f"стоит ≈ {fmt_num(L, 1)} млн ₽. Варианты:\n" + "\n".join(rows) +
            "\n\nКакой вариант даёт минимальную ожидаемую годовую цену (инфраструктура и ожидаемый простой)?")
    expl = ("Ожидаемая цена = инфраструктура + ожидаемые часы простоя × цена часа; одна зона — все отказы, несколько "
            "зон — только регион, резервный регион — отказ региона на время переключения, два активных — без "
            "простоя. Итоги: " + "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Без учёта отказа региона вышло бы: {NAMES[no_reg]}.")
    program = PROGRAM.format(k_z=k_z, h_z=h_z, p_r=p_r, h_r=h_r, R=R, L=L,
                             infra={NAMES[k]: (k, price[k]) for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"k_z": k_z, "h_z": h_z, "p_r": p_r, "h_r": h_r, "R": R, "L": L, "C_aa": C_aa,
                               "good": good, "no_reg": no_reg, **{f"price_{k}": price[k] for k in ORDER}},
                       note="Ответ проверяется программой: перечисление событий года и простой каждого варианта.")
