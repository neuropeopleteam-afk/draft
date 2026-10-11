"""qa.principal.gate_threshold_mcq — mcq_concept (Principal, короткое): порог «шлагбаума качества» по числу упавших
сквозных тестов с учётом базовой доли плохих релизов и цены ошибок обоих родов.

Даны хвосты распределения числа упавших тестов (по истории): у исправных релизов (падения — нестабильные тесты) и у
релизов с дефектом. Доля релизов с дефектом q, цена ложной остановки исправного релиза C_d (часов разбора и
задержки), цена пропущенного дефекта C_i. Ожидаемая цена порога T на релиз:
(1 − q) · P(≥ T | исправный) · C_d + q · (1 − P(≥ T | с дефектом)) · C_i. Ключ — порог с наименьшей ценой из четырёх.

Варианты — четыре порога; какой из них верный (по месту среди порогов), задаётся по seed поровну, числа подбираются
под него. Ошибки, которые ведут к другим порогам: без базовой доли (q = 1/2), только пропуски, только ложные
остановки, равная цена ошибок. Ключ проверяется исполнением: программа считает цену каждого порога по показанной
таблице точными дробями.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import choice_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.principal.gate_threshold_mcq"

CONTEXTS = ["мобильный банк", "интернет-магазин", "сервис доставки", "платформа бронирования", "страховой кабинет",
            "онлайн-кинотеатр", "маркетплейс услуг", "сервис такси", "облачная бухгалтерия", "система записи к врачу"]

PROGRAM = """from fractions import Fraction as F

GOOD = {good!r}    # порог -> P(упало не меньше порога | исправный релиз)
BAD = {bad!r}      # порог -> P(упало не меньше порога | релиз с дефектом)
q, Cd, Ci = F({qn}, 100), {Cd}, {Ci}
OPTIONS = {opts!r}
cost = {{t: (1 - q) * F(GOOD[t]) * Cd + q * (1 - F(BAD[t])) * Ci for t in OPTIONS}}
best = min(OPTIONS, key=lambda t: cost[t])
print(f"останавливать при {{best}} и более упавших")
"""


def _tail(lam: float, t: int) -> float:
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(t))


def _opt(t: int) -> str:
    return f"останавливать при {t} и более упавших"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice([0, 1, 2, 3])                     # место верного порога среди четырёх
    from fractions import Fraction as F
    for _ in range(6000):
        lam0 = rng.choice([0.5, 0.8, 1.0, 1.5, 2.0, 2.5])
        lam1 = lam0 + rng.choice([2, 3, 4, 5, 6])
        q = rng.choice([2, 5, 10, 15, 20])
        Cd = rng.choice([2, 3, 4, 6, 8])
        Ci = rng.choice([40, 60, 80, 120, 200])
        step = rng.choice([1, 1, 2])
        start = rng.choice([1, 2])
        opts = [start + step * i for i in range(4)]
        ts = range(1, max(opts) + 1)
        good = {t: f"{_tail(lam0, t):.3f}" for t in ts}
        bad = {t: f"{_tail(lam1, t):.3f}" for t in ts}

        def cost(t, qq=F(q, 100), cd=Cd, ci=Ci):
            return (1 - qq) * F(good[t]) * cd + qq * (1 - F(bad[t])) * ci
        c = {t: cost(t) for t in opts}
        order = sorted(opts, key=lambda t: c[t])
        if opts.index(order[0]) != target or c[order[1]] - c[order[0]] < F(5, 100) * c[order[0]] + F(1, 50):
            continue
        alt = {"no_base_rate": min(opts, key=lambda t: cost(t, qq=F(1, 2))),
               "equal_cost": min(opts, key=lambda t: cost(t, cd=1, ci=1))}
        if all(v == order[0] for v in alt.values()):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    best = order[0]
    rows = ["Порог T | P(упало ≥ T), исправный релиз | P(упало ≥ T), релиз с дефектом"]
    rows += [f"  {t} | {good[t].replace('.', ',')} | {bad[t].replace('.', ',')}" for t in ts]
    code = "\n".join(["Распределение числа упавших сквозных тестов по истории релизов:", *rows,
                      f"Доля релизов с дефектом: {q} %",
                      f"Ложная остановка исправного релиза: {Cd} ч (разбор и задержка выкатки)",
                      f"Пропущенный дефект в эксплуатации: {Ci} ч (инцидент, откат, исправление)"])
    stem = (f"{ctx.capitalize()}: сквозные тесты нестабильны, поэтому выкатку останавливают не по первому падению, а "
            f"по порогу. Нужно выбрать порог, при котором ожидаемая цена ошибок на один релиз (ложные остановки и "
            f"пропущенные дефекты) наименьшая. Какой порог выбрать?")
    fmt = lambda x: f"{float(x):.2f}".replace(".", ",")  # noqa: E731
    why = (f"Цена порога T на релиз: (1 − q)·P(≥ T | исправный)·{Cd} + q·P(< T | с дефектом)·{Ci}, q = {q} %. "
           + "; ".join(f"T = {t}: {fmt(c[t])} ч" for t in opts) + f". Наименьшая — при T = {best}. "
           f"Без базовой доли (q = 1/2) выбрали бы {alt['no_base_rate']}, при равной цене ошибок — "
           f"{alt['equal_cost']}. Вывод: порог шлагбаума зависит от доли плохих релизов и цене ошибок обоих родов, "
           f"а не одной «чувствительности» тестов.")
    program = PROGRAM.format(good=good, bad=bad, qn=q, Cd=Cd, Ci=Ci, opts=opts)
    return choice_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, correct=_opt(best),
                      distractors=[_opt(t) for t in opts if t != best], program=program, why=why, code=code,
                      params={"q": q, "Cd": Cd, "Ci": Ci, "options": opts, "best": best, "target": target},
                      note="Программа считает ожидаемую цену каждого порога по показанной таблице точными дробями.")
