"""common.stats.stats_sample_margin_mcq — mcq_concept (Senior/Lead, статистика): размер выборки для оценки доли.

Нужно оценить долю (конверсию, долю дефектов) с погрешностью ±E процентных пунктов при доверии 1 − α; ожидаемая
доля p. n = z²·p(1 − p)/E², z = z_{1−α/2}; с поправкой на конечную совокупность N: n' = n / (1 + (n − 1)/N).
Ловушки: односторонний z, E как относительная погрешность, без поправки на конечную совокупность, p = 0,5
(консервативная оценка при известном p), E без квадрата.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.stats.stats_sample_margin_mcq"
CONTEXTS = ["доля заказов с ошибкой адреса", "конверсия в оплату", "доля обращений с повтором", "доля брака в партии",
            "доля пользователей с тёмной темой", "доля отказов на шаге регистрации", "доля писем в спаме",
            "доля сессий с ошибкой приложения"]

MODEL = '''
from math import ceil
from statistics import NormalDist

def n(P, two=True, rel=False, fpc=True, half=False, no_square=False):
    z = NormalDist().inv_cdf(1 - P["alpha"] / 100 / (2 if two else 1))
    p = 0.5 if half else P["p"] / 100
    E = P["E"] / 100 * (p if rel else 1)
    n0 = z ** 2 * p * (1 - p) / (E if no_square else E ** 2)
    if fpc:
        n0 = n0 / (1 + (n0 - 1) / P["N"])
    return ceil(n0)

def answer(P):
    return n(P)

def traps(P):
    return {"one_sided": n(P, two=False), "relative": n(P, rel=True), "no_fpc": n(P, fpc=False), "half": n(P, half=True),
            "no_square": n(P, no_square=True), "one_sided_no_fpc": n(P, two=False, fpc=False)}

def fmt(x):
    return f"{x:,}".replace(",", "\\u00a0")
'''


def _sample(rng):
    return {"p": rng.choice([5, 8, 10, 15, 20, 30]), "E": rng.choice([1, 1.5, 2, 3]), "alpha": rng.choice([5, 10, 1]),
            "N": rng.choice([3000, 5000, 8000, 12000, 20000])}


def _accept(P, ns):
    return ns["answer"](P) >= 100


def _stem(P, ctx):
    return (f"Нужно оценить «{ctx}» по случайной выборке без возвращения из {num(P['N'])} объектов за месяц. Ожидаемая "
            f"доля — около {P['p']} % (по прошлым месяцам), требуемая точность — ±{num(P['E'], 1)} процентного пункта "
            f"при доверии {100 - P['alpha']} % (двусторонний интервал, нормальное приближение).\n\n"
            "Сколько объектов нужно в выборке (с поправкой на конечную совокупность, округление вверх)?")


def _explain(P, a, traps):
    return (f"n₀ = z²·p(1 − p)/E² с z = z_(1−α/2) для {100 - P['alpha']} % и E = {num(P['E'] / 100, 3)} (процентные "
            f"пункты, не доля от p); поправка на конечную совокупность: n = n₀ / (1 + (n₀ − 1)/{num(P['N'])}) → "
            f"{num(a)}. p = 0,5 — консервативная оценка, когда p неизвестно; здесь оно известно.")


TRAP_DESC = {"one_sided": "односторонний z", "relative": "±E принято за относительную погрешность",
             "no_fpc": "без поправки на конечную совокупность", "half": "p = 0,5 при известном p",
             "no_square": "E без квадрата", "one_sided_no_fpc": "односторонний z без поправки"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.08, abs_min=5, trap_first="no_fpc",
                           trap_desc=TRAP_DESC)
