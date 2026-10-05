"""data_ml.ab.sample_size_mcq — mcq_concept: размер выборки и длительность A/B-теста для конверсии.

Двусторонний тест разности долей, уровень значимости α, мощность 1 − β, минимальный
детектируемый эффект (MDE) задан относительно базовой конверсии:
n на группу = (z(1 − α/2) + z(1 − β))² · (p1(1 − p1) + p2(1 − p2)) / (p2 − p1)².

Вопрос двух видов: размер каждой группы или число полных дней теста при заданном трафике.
Дистракторы — типичные ошибки планирования: односторонний z, забытая мощность (z(1 − β) = 0),
итог на обе группы вместо одной, при расчёте дней — трафик только на одну группу или двойной
учёт деления на группы. Ключ проверяется исполнением: программа считает n через
statistics.NormalDist по двум формулам (с объединённой и раздельной дисперсией) и печатает
ближайший вариант — он должен совпасть с ключом для обеих формул.
"""
from __future__ import annotations

import math
from statistics import NormalDist

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options, check_lengths

FAMILY_ID = "data_ml.ab.sample_size_mcq"

CONTEXTS = [("конверсия в покупку", "новая карточка товара", "посетителей"),
            ("конверсия в регистрацию", "упрощённая форма регистрации", "посетителей"),
            ("доля оплативших подписку", "новый пейволл", "пользователей"),
            ("CTR блока рекомендаций", "новая модель ранжирования", "пользователей"),
            ("доля откликов на вакансию", "новая выдача вакансий", "соискателей"),
            ("доля продлений тарифа", "напоминание о продлении", "клиентов")]

Z = NormalDist().inv_cdf


def _n(p1, mde, alpha, power, kind="good"):
    p2 = p1 * (1 + mde)
    za = Z(1 - alpha) if kind == "one_sided" else Z(1 - alpha / 2)
    zb = {"no_power": 0.0, "power80": Z(0.8)}.get(kind, Z(power))
    return (za + zb) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2


def _fmt_n(n):
    r = int(math.ceil(n / 100.0)) * 100
    return f"{r:,}".replace(",", " ")


def _days_word(d):
    if d % 10 == 1 and d % 100 != 11:
        return "день"
    if d % 10 in (2, 3, 4) and d % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def _pct(x):
    s = f"{x * 100:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " %"


PROGRAM = '''import math
from statistics import NormalDist

Z = NormalDist().inv_cdf
P1, MDE, ALPHA, POWER = {p1!r}, {mde!r}, {alpha!r}, {power!r}
ASK, TRAFFIC = {ask!r}, {traffic!r}
OPTIONS = {options!r}   # (текст варианта, число в варианте)
p2 = P1 * (1 + MDE)
z = Z(1 - ALPHA / 2) + Z(POWER)
n_unpooled = z ** 2 * (P1 * (1 - P1) + p2 * (1 - p2)) / (p2 - P1) ** 2
pbar = (P1 + p2) / 2
n_pooled = (Z(1 - ALPHA / 2) * math.sqrt(2 * pbar * (1 - pbar))
            + Z(POWER) * math.sqrt(P1 * (1 - P1) + p2 * (1 - p2))) ** 2 / (p2 - P1) ** 2
picked = set()
for n in (n_unpooled, n_pooled):
    value = n if ASK == "n" else math.ceil(2 * n / TRAFFIC)
    best = min(OPTIONS, key=lambda o: abs(math.log(o[1] / value)))
    picked.add(best[0])
print(" | ".join(sorted(picked)))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    metric, change, who = rng.choice(CONTEXTS)
    ask = rng.choice(["n", "days"])
    for _ in range(500):
        p1 = rng.choice([0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15, 0.2])
        mde = rng.choice([0.05, 0.08, 0.1, 0.15, 0.2])
        alpha = rng.choice([0.05, 0.05, 0.01])
        power = rng.choice([0.8, 0.9])
        good = _n(p1, mde, alpha, power)
        if ask == "n":
            kinds = ["one_sided", "no_power", "double"]
            if not 3000 <= good <= 400000:
                continue
            vals = {"good": good, "double": 2 * good,
                    "one_sided": _n(p1, mde, alpha, power, "one_sided"),
                    "no_power": _n(p1, mde, alpha, power, "no_power")}
            nums = {k: int(math.ceil(v / 100.0)) * 100 for k, v in vals.items()}
            texts = {k: f"≈ {_fmt_n(v)} {who} в каждой группе" for k, v in vals.items()}
            traffic = None
        else:
            kinds = (["one_sided", "no_power", "one_group"] if power == 0.9
                     else ["one_sided", "one_group", "double_count"])
            traffic = rng.choice([1000, 1500, 2000, 3000, 5000, 8000, 12000, 20000])
            dg = 2 * good / traffic
            if not 10 <= dg <= 60:
                continue
            vals = {"good": dg, "one_group": good / traffic, "double_count": 4 * good / traffic,
                    "one_sided": 2 * _n(p1, mde, alpha, power, "one_sided") / traffic,
                    "no_power": 2 * _n(p1, mde, alpha, power, "no_power") / traffic}
            vals = {k: v for k, v in vals.items() if k == "good" or k in kinds}
            nums = {k: int(math.ceil(v)) for k, v in vals.items()}
            texts = {k: f"{v} {_days_word(v)}" for k, v in nums.items()}
        ordered = sorted(nums.values())
        # варианты различимы: соседние отличаются не меньше чем на 12 % (дни — на 20 %)
        gap = 1.12 if ask == "n" else 1.2
        if len(set(ordered)) == 4 and all(b / a >= gap for a, b in zip(ordered, ordered[1:])):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    check_lengths(list(texts.values()))
    opts, key = balanced_options(FAMILY_ID, seed, rng, (texts["good"], None),
                                 [(texts[k], None) for k in kinds])
    options = [(o.text, next(nums[k] for k in nums if texts[k] == o.text)) for o in opts]
    program = PROGRAM.format(p1=p1, mde=mde, alpha=alpha, power=power, ask=ask,
                             traffic=traffic, options=options)
    p2 = p1 * (1 + mde)
    if ask == "n":
        task = f"Сколько {who} нужно в каждую группу (округление вверх до сотен)?"
    else:
        task = (f"В эксперимент попадает {_fmt_n(traffic)} {who} в день, они делятся поровну "
                f"между A и B. Сколько полных дней нужно держать тест?")
    stem = (f"Метрика A/B-теста — {metric}, изменение — {change}. Базовое значение {_pct(p1)}; "
            f"хотим обнаружить относительный рост на {round(mde * 100)} % (до {_pct(p2)}). Тест "
            f"двусторонний, α = {str(alpha).replace('.', ',')}, мощность {round(power * 100)} %, "
            f"группы равные. Квантили N(0, 1): z(0,995) = 2,576; z(0,99) = 2,326; "
            f"z(0,975) = 1,960; z(0,95) = 1,645; z(0,90) = 1,282; z(0,80) = 0,842. {task}")
    why = {"one_sided": "взят односторонний квантиль z(1 − α) вместо z(1 − α/2)",
           "no_power": "забыта мощность: z(1 − β) = 0 соответствует мощности 50 %",
           "double_count": "трафик поделён на группы, а размер ещё раз умножен на две группы — "
                           "двойной учёт",
           "double": "это суммарный размер обеих групп, а не одной",
           "one_group": "учтён размер только одной группы, а трафик делится на две — дней вдвое больше"}
    calc = f"n на группу = (z(1 − α/2) + z(1 − β))² · (p1(1 − p1) + p2(1 − p2)) / (p2 − p1)² ≈ {good:.0f}"
    if ask == "days":
        calc += (f"; дней = 2n / {traffic} ≈ {2 * good / traffic:.1f}".replace(".", ",")
                 + f" → {nums['good']}")
    ak = AnswerKey(kind="option", value=key,
                   explanation=calc + ". Дистракторы: " + "; ".join(why[k] for k in kinds) + ".")
    checks = [Check(name="sample_size", runner="python", program=program,
                    expect="stdout_equals", expected_stdout=texts["good"],
                    embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak,
                         context=metric, verification="execution", checks=checks,
                         language="text",
                         display_code_note="Кода в задании нет: программа пересчитывает размер "
                                           "выборки по двум формулам и выбирает ближайший вариант.",
                         params={"ask": ask, "p1": p1, "mde": mde, "alpha": alpha,
                                 "power": power, "traffic": traffic, "kinds": kinds})
