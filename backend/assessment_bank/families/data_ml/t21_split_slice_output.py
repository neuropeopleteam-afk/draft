"""data_ml.splits.t21_split_slice_output — predict_output (набор t21, порог Стажёра): разбиение временного ряда
на обучающую и тестовую части срезами по индексу int(len * доля).

Ряд упорядочен по времени, поэтому без перемешивания: train — первые cut значений, test — остальные. Ловушки
чтения: int() отбрасывает дробную часть, а не округляет (9 * 0.8 = 7.2 → 7, 7 * 0.8 = 5.6 → 5), срез [:cut]
не включает элемент с индексом cut, срез [cut:] начинается с него. Ключ — независимый расчёт в генераторе
(точные дроби); проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from fractions import Fraction
import math

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.splits.t21_split_slice_output"

CTX = [("продажи магазина по дням", "sales", (40, 99)),
       ("заявки на кредит по неделям", "requests", (10, 60)),
       ("показы рекламы по часам", "shows", (100, 400)),
       ("активные пользователи по дням", "dau", (200, 900)),
       ("замеры датчика по сменам", "readings", (10, 99))]
FRACS = ["0.7", "0.75", "0.8", "0.9"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, (lo, hi) = rng.choice(CTX)
    want_frac_part = rng.random() < 0.8          # чаще — с дробной частью (ловушка int)
    for _ in range(500):
        frac_s = rng.choice(FRACS)
        n = rng.randint(6, 12)
        exact = n * Fraction(frac_s)
        cut = math.floor(exact)
        if (exact.denominator != 1) != want_frac_part:
            continue
        if not 1 <= n - cut <= 4 or cut < 3:
            continue
        if int(n * float(frac_s)) != cut:     # страховка от погрешности float у границы
            continue
        break
    else:
        raise RuntimeError("t21_split_slice: не собралось разбиение")
    vals = [rng.randint(lo, hi) for _ in range(n)]
    train, test = vals[:cut], vals[cut:]
    code = (f"{var} = {vals}\n"
            f"cut = int(len({var}) * {frac_s})\n"
            f"train = {var}[:cut]\n"
            f"test = {var}[cut:]\n"
            "print(len(train), len(test))\n"
            "print(test)")
    out = f"{len(train)} {len(test)}\n{test}"
    if exact.denominator != 1:
        prod = f"{n} * {frac_s} = {float(exact):g}, int() отбрасывает дробную часть → {cut}"
    else:
        prod = f"{n} * {frac_s} = {cut}.0, int() → {cut}"
    expl = (f"В списке {n} значений: {prod}. Срез [:{cut}] — элементы с индексами 0…{cut - 1} ({len(train)} шт.), "
            f"срез [{cut}:] — с индекса {cut} до конца: {test}. Ловушка — округлить вместо отбрасывания дробной "
            f"части или включить элемент с индексом cut в обучающую часть.")
    stem = (f"Ряд «{ctx}» упорядочен по времени; программа отделяет последние значения в тестовую часть "
            f"без перемешивания.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "frac": frac_s, "cut": cut}, language="python")
