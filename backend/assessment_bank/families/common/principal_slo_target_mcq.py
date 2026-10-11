"""common.reliability.principal_slo_target_mcq — mcq_concept (Principal, короткое): какую цель доступности выбрать.

Сервис выбирает цель доступности (SLO) из четырёх уровней: 99,5 / 99,9 / 99,95 / 99,99 %. У каждого — годовая цена
обеспечения (дежурства, резервирование, процессы выкладки). Команда в среднем расходует долю u бюджета ошибок, то
есть фактический простой самого сервиса ≈ u · (1 − SLO) · 525 600 мин в год. Сервис последовательно зависит от
внешней системы с доступностью A_up (её простой пользователи видят как простой сервиса). Минута простоя для
пользователей стоит V тыс. ₽; если итоговая доступность для пользователей ниже договорной A_c — штраф P млн ₽ в год.
Вопрос — какая цель даёт минимальную ожидаемую годовую цену (обеспечение + простой + штраф).

Ловушки: «максимальная цель», «самая дешёвая», расчёт без внешней зависимости (тогда штраф кажется
недостижимым или наоборот), расчёт так, будто бюджет расходуется полностью (u = 1). Генератор подбирает числа так,
что верный уровень меняется между вариантами (поровну по четырём уровням) и отличается хотя бы от двух ловушек.
Ключ проверяется исполнением: программа помесячно (12 месяцев) накапливает простой обеих систем, сравнивает
итоговую доступность с договорной и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.reliability.principal_slo_target_mcq"

LEVELS = [0.995, 0.999, 0.9995, 0.9999]
LABEL = {0.995: "99,5 %", 0.999: "99,9 %", 0.9995: "99,95 %", 0.9999: "99,99 %"}
YEAR_MIN = 525_600

CONTEXTS = ["приём платежей", "личный кабинет клиента", "API партнёров", "поиск по каталогу", "выдача кредитов",
            "бронирование билетов", "диспетчерская такси", "электронный документооборот"]

PROGRAM = """opts = __OPTS__
levels = {levels!r}     # подпись -> (цель, цена обеспечения, млн ₽ в год)
u, a_up, a_c, V, P = {u}, {a_up}, {a_c}, {V}, {P}
cost = {{}}
for label, (slo, price) in levels.items():
    own = up = 0.0
    for month in range(12):
        minutes = 525600 / 12
        own += u * (1 - slo) * minutes
        up += (1 - a_up) * minutes
    down = own + up                         # последовательная зависимость: простои складываются
    avail = 1 - down / 525600
    cost[label] = price + down * V / 1000 + (P if avail < a_c else 0)
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t.startswith(best)]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _pct(x):
    t = f"{100 * x:.2f}".rstrip("0").rstrip(".")
    return t.replace(".", ",")


def _cost(slo, price, u, a_up, a_c, V, P, with_up=True):
    down = u * (1 - slo) * YEAR_MIN + ((1 - a_up) * YEAR_MIN if with_up else 0)
    return price + down * V / 1000 + (P if 1 - down / YEAR_MIN < a_c else 0)


def _argmin(d, rel=0.04):
    s = sorted(d.values())
    return min(d, key=d.get) if s[1] - s[0] >= rel * s[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(LEVELS)
    for _ in range(40000):
        base = rng.choice([4, 6, 8, 12])
        steps = [rng.choice([1.5, 2.0, 2.5]), rng.choice([1.3, 1.5, 2.0]), rng.choice([1.3, 1.6, 2.0, 2.5])]
        prices = [base]
        for k in steps:
            prices.append(round(prices[-1] * k, 1))
        price = dict(zip(LEVELS, prices))
        u = rng.choice([0.4, 0.5, 0.6, 0.7, 0.8])
        a_up = rng.choice([0.999, 0.9995, 0.9998, 0.9999])
        a_c = rng.choice([0.995, 0.998, 0.999, 0.9993])
        V = rng.choice([2, 5, 10, 20, 40, 80, 150])                # тыс. ₽ за минуту простоя
        P = rng.choice([10, 20, 40, 80])                    # млн ₽ в год
        a = (u, a_up, a_c, V, P)
        full = {s: _cost(s, price[s], *a) for s in LEVELS}
        good = _argmin(full)
        if good != target:
            continue
        no_up = _argmin({s: _cost(s, price[s], u, a_up, a_c, V, P, with_up=False) for s in LEVELS})
        full_budget = _argmin({s: _cost(s, price[s], 1.0, a_up, a_c, V, P) for s in LEVELS})
        if None in (no_up, full_budget):
            continue
        traps = (LEVELS[-1], LEVELS[0], no_up, full_budget)
        if sum(t != good for t in traps) >= 2:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    rows = "\n".join(f"• {LABEL[s]} — {fmt_num(price[s], 1)} млн ₽ в год" for s in LEVELS)
    intro = rng.choice([
        f"Вы — главный инженер; сервис «{ctx}» пересматривает цель доступности (SLO) на год.",
        f"Для сервиса «{ctx}» нужно утвердить цель доступности (SLO) на следующий год; решение за вами как за "
        f"главным инженером.",
        f"Владелец продукта «{ctx}» просит главного инженера обосновать цель доступности (SLO) на год.",
    ])
    stem = (f"{intro} Цена обеспечения каждой цели (дежурства, резервирование, процессы выкладки):\n{rows}\n"
            f"Команда в среднем расходует {fmt_num(100 * u, 0)} % бюджета ошибок. Сервис последовательно зависит от "
            f"внешней системы с доступностью {_pct(a_up)} % — её простой пользователи видят как простой "
            f"сервиса. Минута простоя обходится в {V} тыс. ₽. По договору с крупными клиентами итоговая доступность "
            f"для пользователей должна быть не ниже {_pct(a_c)} %, иначе штраф {P} млн ₽ в год.\n\n"
            "Какая цель доступности даёт минимальную ожидаемую годовую цену (обеспечение, простой и штраф)?")
    order = LEVELS
    expl = ("Простой за год = доля расхода бюджета × (1 − SLO) × 525 600 мин + (1 − A внешней) × 525 600 мин; цена = "
            "обеспечение + простой × цена минуты + штраф, если итоговая доступность ниже договорной. Итоги: " +
            "; ".join(f"{LABEL[s]} — {fmt_num(full[s], 1)} млн ₽" for s in order) +
            f". Минимум — {LABEL[good]}. Без внешней зависимости вышло бы {LABEL[no_up]}, при полном расходе бюджета — "
            f"{LABEL[full_budget]}.")
    program = PROGRAM.format(levels={LABEL[s]: (s, price[s]) for s in LEVELS}, u=u, a_up=a_up, a_c=a_c, V=V, P=P)
    txt = {s: f"{LABEL[s]}" for s in LEVELS}
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=txt[good],
                       distractors=[txt[s] for s in LEVELS if s != good], program=program, explanation=expl,
                       params={"u": u, "a_up": a_up, "a_c": a_c, "V": V, "P": P, "good": good, "no_up": no_up,
                               "full_budget": full_budget, "prices": "/".join(map(str, prices))},
                       note="Ответ проверяется программой: помесячное накопление простоя обеих систем.")
