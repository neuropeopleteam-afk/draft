"""common.stats.principal_ab_duration_mcq — mcq_concept (Principal): сколько недель идти A/B-тесту.

Базовая конверсия p, минимальный детектируемый эффект — относительный δ (p2 = p·(1 + δ)), двусторонний α, мощность
1 − β, в эксперимент попадает доля s дневного трафика T, деление 50/50. Размер группы — n = (z_{1−α/2} + z_{1−β})² ·
(p1(1 − p1) + p2(1 − p2)) / (p2 − p1)²; длительность — 2n / (T·s) дней, округлённо вверх до целых недель
(недельная сезонность). Ловушки: односторонний z, δ как абсолютный эффект в процентных пунктах, одна группа вместо
двух, весь трафик вместо доли s, без округления до недель (дни/7).
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.stats.principal_ab_duration_mcq"
CONTEXTS = ["новая кнопка оформления заказа", "другой порядок тарифов", "упрощённая регистрация", "новый экран оплаты",
            "рекомендации в корзине", "бесплатная доставка от порога", "новый онбординг", "пуш о брошенной корзине"]

MODEL = '''
from math import ceil
from statistics import NormalDist

def weeks(P, two_sided=True, relative=True, groups=2, share=True, round_weeks=True):
    p1 = P["p"] / 100
    p2 = p1 * (1 + P["d"] / 100) if relative else p1 + P["d"] / 100
    z = NormalDist().inv_cdf(1 - P["alpha"] / 100 / (2 if two_sided else 1)) + NormalDist().inv_cdf(P["power"] / 100)
    n = ceil(z ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2)
    days = ceil(groups * n / (P["T"] * (P["s"] / 100 if share else 1)))
    return ceil(days / 7) if round_weeks else round(days / 7, 1)

def answer(P):
    return weeks(P)

def traps(P):
    return {"one_sided": weeks(P, two_sided=False), "absolute": weeks(P, relative=False), "one_group": weeks(P, groups=1),
            "all_traffic": weeks(P, share=False), "four_groups": weeks(P, groups=4),
            "half_mde": weeks(P, relative=True) * 4}

def fmt(x):
    return f"{x} нед."
'''


def _sample(rng):
    return {"p": rng.choice([2, 3, 4, 5, 8, 10, 12]), "d": rng.choice([5, 8, 10, 15, 20]), "alpha": rng.choice([5, 1]),
            "power": rng.choice([80, 90]), "T": rng.choice([4000, 6000, 8000, 12000, 20000, 30000]),
            "s": rng.choice([10, 20, 30, 50])}


def _accept(P, ns):
    a = ns["answer"](P)
    return 2 <= a <= 40 and ns["traps"](P)["absolute"] >= 1


def _stem(P, ctx):
    return (f"A/B-тест «{ctx}»: базовая конверсия — {P['p']} %, хотим заметить относительный рост не меньше "
            f"{P['d']} % (то есть до {num(P['p'] * (1 + P['d'] / 100), 2)} %), двусторонний критерий для долей, "
            f"α = {num(P['alpha'] / 100, 2)}, мощность {P['power']} %. Деление 50/50 между контролем и тестом, в "
            f"эксперимент попадает {P['s']} % трафика, это ≈ {num(P['T'] * P['s'] / 100)} пользователей в сутки из "
            f"{num(P['T'])}. Из-за недельной сезонности тест идёт целое число недель.\n\n"
            "Сколько недель нужно держать тест?")


def _explain(P, a, traps):
    return (f"n на группу = (z_(1−α/2) + z_(1−β))² · (p1(1 − p1) + p2(1 − p2)) / (p2 − p1)² при p2 = p1·(1 + "
            f"{num(P['d'] / 100, 2)}); две группы делят {num(P['T'] * P['s'] / 100)} пользователей в сутки; дни "
            f"округляются вверх до целых недель — {a}.")


TRAP_DESC = {"one_sided": "односторонний критерий", "absolute": "эффект принят за абсолютный (процентные пункты)",
             "one_group": "размер одной группы вместо двух", "all_traffic": "весь трафик вместо доли эксперимента",
             "four_groups": "размер группы удвоен дважды", "half_mde": "эффект вдвое меньше заявленного"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.15, abs_min=1, trap_first="one_group",
                           trap_desc=TRAP_DESC)
