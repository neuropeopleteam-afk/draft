"""qa.design.boundary_values_mcq — mcq_concept: минимальный набор граничных значений.

Требование задаёт допустимый диапазон (закрытый, полуоткрытый «не включая верхнюю границу»
или денежный с шагом 0,01). Нужно выбрать наименьший набор значений, который обнаружит
любой сдвиг границы на один шаг, в том числе перепутанные «<» и «≤». Это двухточечный
анализ граничных значений: для каждой границы — последнее допустимое и первое недопустимое
значение. Ключ проверяется исполнением: программа строит четыре мутанта проверки диапазона
(каждая граница сдвинута на шаг внутрь и наружу) и печатает тот набор из вариантов, который
обнаруживает все мутанты (каждый мутант отличается от требования ровно в одной точке).
"""
from __future__ import annotations

from decimal import Decimal

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options, check_lengths

FAMILY_ID = "qa.design.boundary_values_mcq"

# (контекст, что вводится, единица, lo, hi, допустимые виды диапазона)
CONTEXTS = [
    ("регистрация на сервисе", "возраст пользователя", "лет", [(14, 99), (18, 75), (16, 120), (12, 90), (21, 65)], ["closed", "half"]),
    ("смена пароля", "длина пароля", "символов", [(8, 64), (10, 128), (12, 40), (6, 32), (14, 72)], ["closed"]),
    ("корзина интернет-магазина", "количество единиц товара в позиции", "шт.", [(1, 50), (1, 99), (2, 20), (1, 30), (5, 200)], ["closed", "half"]),
    ("перевод между счетами", "сумма перевода", "₽", [(100, 150000), (10, 600000), (50, 75000), (200, 300000), (20, 99000)], ["closed", "money"]),
    ("служба доставки", "вес посылки", "г", [(50, 30000), (100, 20000), (10, 5000), (20, 15000), (200, 40000)], ["closed", "half"]),
    ("программа лояльности", "сумма покупки для начисления бонусов", "₽", [(300, 50000), (1000, 99999), (500, 20000), (700, 30000), (1500, 80000)], ["half", "money"]),
]


def _fmt(v: Decimal, money: bool) -> str:
    if money:
        s = f"{v:.2f}".replace(".", ",")
    else:
        s = str(int(v))
    return s


def _sets(lo, hi_eff, step):
    s = step
    return {
        "good": (lo - s, lo, hi_eff, hi_eff + s),
        "inside": (lo, lo + s, hi_eff - s, hi_eff),
        "skip": (lo - s, lo + s, hi_eff - s, hi_eff + s),
        "upper_shift": (lo - s, lo, hi_eff - s, hi_eff),
        "lower_shift": (lo, lo + s, hi_eff, hi_eff + s),
        "outer": (lo - s, lo, hi_eff + s, hi_eff + 2 * s),
    }


PROGRAM = '''from decimal import Decimal as D

LO, HI_EFF, STEP = D({lo!r}), D({hi!r}), D({step!r})


def valid(x):
    return LO <= x <= HI_EFF


MUTANTS = [lambda x: LO - STEP <= x <= HI_EFF, lambda x: LO + STEP <= x <= HI_EFF,
           lambda x: LO <= x <= HI_EFF + STEP, lambda x: LO <= x <= HI_EFF - STEP]
OPTIONS = {options!r}
best = []
for text, values in OPTIONS:
    xs = [D(v) for v in values]
    if all(any(m(x) != valid(x) for x in xs) for m in MUTANTS):
        best.append((len(xs), text))
best.sort()
print(best[0][1] if best and (len(best) == 1 or best[0][0] < best[1][0]) else "NONE")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, what, unit, ranges, kinds = rng.choice(CONTEXTS)
    lo_i, hi_i = rng.choice(ranges)
    kind = rng.choice(kinds)
    money = kind == "money"
    step = Decimal("0.01") if money else Decimal(1)
    lo, hi = Decimal(lo_i), Decimal(hi_i)
    hi_eff = hi - step if kind == "half" else hi
    sets = _sets(lo, hi_eff, step)
    pool = ["inside", "skip", "upper_shift", "lower_shift", "outer"]
    if money:
        pool.append("int_step")
        sets["int_step"] = (lo - 1, lo, hi, hi + 1)
    # Калибровка 05.10: разброс объяснялся составом дистракторов (с inside 0,29, без него 0,43;
    # со skip 0,42, без него 0,26). Состав зафиксирован: inside всегда, skip (очевидно неполный набор) — нет.
    chosen = ["inside"] + rng.sample([k for k in pool if k not in ("inside", "skip")], 2)
    text = {k: "; ".join(_fmt(v, money) for v in vals) for k, vals in sets.items()}
    check_lengths([text["good"]] + [text[k] for k in chosen])
    opts, key = balanced_options(FAMILY_ID, seed, rng, (text["good"], None),
                                 [(text[k], None) for k in chosen])
    options = [(o.text, [str(v) for v in sets[next(k for k in sets if text[k] == o.text)]])
               for o in opts]
    program = PROGRAM.format(lo=str(lo), hi=str(hi_eff), step=str(step), options=options)
    lo_t, hi_t = _fmt(lo, money), _fmt(hi, money)
    if kind == "closed":
        rule = f"допустимо значение от {lo_t} до {hi_t} {unit} включительно; вводятся целые числа"
    elif kind == "half":
        rule = (f"допустимо значение от {lo_t} {unit} включительно до {hi_t} {unit}, не включая "
                f"{hi_t}; вводятся целые числа")
    else:
        rule = (f"допустима сумма от {lo_t} до {hi_t} {unit} включительно; сумма вводится с "
                f"точностью до копейки")
    stem = (f"Требование ({ctx}): {what} — {rule}; остальные значения поле отклоняет. Какой "
            f"набор тестовых значений — наименьший из тех, что обнаружат любой сдвиг границы на "
            f"один шаг ввода в любую сторону (в том числе перепутанные «<» и «≤»)?")
    why = {"inside": "только допустимые значения — не видно, что граница сдвинута наружу",
           "skip": "пропущены сами границы — не видно сдвига границы внутрь",
           "upper_shift": "у верхней границы взяты два допустимых значения, а не допустимое и "
                          "первое недопустимое",
           "lower_shift": "у нижней границы взяты два допустимых значения, а не первое "
                          "недопустимое и допустимое",
           "outer": "у верхней границы взяты два недопустимых значения, последнее допустимое "
                    "не проверено",
           "int_step": "шаг ввода — копейка, а не рубль: сдвиг границы на 0,01 ₽ не обнаружится"}
    edge = "последнее допустимое значение верхней границы — " + _fmt(hi_eff, money)
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Двухточечный анализ граничных значений: у каждой границы — "
                                f"последнее допустимое и первое недопустимое значение; {edge}. "
                                "Дистракторы: " + "; ".join(why[k] for k in chosen) + "."))
    checks = [Check(name="mutants", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=text["good"], embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Кода в задании нет: программа проверяет наборы "
                                           "значений на мутантах проверки диапазона.",
                         params={"kind": kind, "lo": str(lo), "hi": str(hi), "distractors": chosen})
