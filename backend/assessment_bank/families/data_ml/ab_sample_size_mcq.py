"""data_ml.ab.sample_size_mcq — mcq_concept: размер выборки и длительность A/B-теста для конверсии.

Двусторонний тест разности долей, уровень значимости α, мощность 1 − β, минимальный
детектируемый эффект (MDE) задан относительно базовой конверсии:
n на группу = (z(1 − α/2) + z(1 − β))² · (p1(1 − p1) + p2(1 − p2)) / (p2 − p1)².

Вопрос двух видов: размер каждой группы или число полных дней теста при заданном трафике.
Дистракторы — типичные ошибки планирования. Дают меньше верного: односторонний z, забытая мощность
(z(1 − β) = 0), сумма квантилей без квадрата, при расчёте дней — размер только одной группы. Дают больше:
мощность как двусторонняя (z(1 − β/2)), квантиль мощности приравнен к квантилю значимости, итог на обе группы
вместо одной, при расчёте дней — двойной учёт деления на группы. Сколько ловушек ниже ключа (0–3), задаётся
по seed до подбора чисел, поэтому ранг ключа равномерен (аудит 21.10: раньше ключ почти всегда был медианой). Ключ проверяется исполнением: программа считает n через
statistics.NormalDist по двум формулам (с объединённой и раздельной дисперсией) и печатает
ближайший вариант — он должен совпасть с ключом для обеих формул.
"""
from __future__ import annotations

import itertools
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
    zb = {"no_power": 0.0, "beta_two_sided": Z(1 - (1 - power) / 2), "za_twice": za}.get(kind, Z(power))
    zz = (za + zb) if kind == "no_square" else (za + zb) ** 2
    return zz * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2


# Типовые ошибки планирования и их сторона относительно верного ответа (сторона не зависит от чисел):
# ниже — односторонний квантиль, забытая мощность, сумма квантилей без квадрата, (дни) трафик только одной группы;
# выше — мощность как двусторонняя (z(1 − β/2)), квантиль мощности приравнен к квантилю значимости,
# итог на обе группы (размер) или двойной учёт деления на группы (дни).
BELOW = {"n": ["one_sided", "no_power", "no_square"], "days": ["one_sided", "no_power", "no_square", "one_group"]}
ABOVE = {"n": ["beta_two_sided", "za_twice", "double"], "days": ["beta_two_sided", "za_twice", "double_count"]}


def _spread(vals):
    """Неравномерность набора в логарифмической шкале: наибольший зазор / наименьший."""
    v = sorted(math.log(x) for x in vals)
    g = [b - a for a, b in zip(v, v[1:])]
    return max(g) / min(g) if min(g) > 0 else float("inf")


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


PROGRAM = '''import itertools
import math
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
    # ранг ключа среди 4 вариантов задаётся ДО подбора чисел (аудит 21.10: раньше ключ почти всегда был медианой)
    n_below = make_rng(FAMILY_ID, seed // 4, "rank").sample(range(4), 4)[seed % 4]
    gap = 1.12 if ask == "n" else 1.2
    best = None
    for _ in range(800):
        p1 = rng.choice([0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15, 0.2])
        mde = rng.choice([0.05, 0.08, 0.1, 0.15, 0.2])
        alpha = rng.choice([0.05, 0.05, 0.01])
        power = rng.choice([0.8, 0.9])
        good = _n(p1, mde, alpha, power)
        traffic = None
        if ask == "n":
            if not 3000 <= good <= 400000:
                continue
            vals = {"good": good, "double": 2 * good}
            for k in ("one_sided", "no_power", "no_square", "beta_two_sided", "za_twice"):
                vals[k] = _n(p1, mde, alpha, power, k)
            nums = {k: int(math.ceil(v / 100.0)) * 100 for k, v in vals.items()}
        else:
            traffic = rng.choice([1000, 1500, 2000, 3000, 5000, 8000, 12000, 20000])
            dg = 2 * good / traffic
            if not 10 <= dg <= 60:
                continue
            vals = {"good": dg, "one_group": good / traffic, "double_count": 4 * good / traffic}
            for k in ("one_sided", "no_power", "no_square", "beta_two_sided", "za_twice"):
                vals[k] = 2 * _n(p1, mde, alpha, power, k) / traffic
            nums = {k: int(math.ceil(v)) for k, v in vals.items()}
        below = [k for k in BELOW[ask] if nums[k] < nums["good"]]
        above = [k for k in ABOVE[ask] if nums[k] > nums["good"]]
        if len(below) < n_below or len(above) < 3 - n_below:
            continue
        for cb in itertools.combinations(below, n_below):
            for ca in itertools.combinations(above, 3 - n_below):
                ks = list(cb) + list(ca)
                ordered = sorted([nums["good"]] + [nums[k] for k in ks])
                if len(set(ordered)) != 4 or not all(b / a >= gap for a, b in zip(ordered, ordered[1:])):
                    continue
                if ask == "days" and not (10 <= ordered[0] and ordered[-1] <= 99):
                    continue  # все варианты двузначные: длина подписи не выдаёт ключ (он всегда 10–60 дней)
                # разное число цифр — подсказка «самый длинный»: штраф, если у ключа не то же число цифр, что у всех
                digits = {len(str(x)) for x in ordered}
                sc = _spread(ordered) + rng.random() * 0.3 + (1.5 if len(digits) > 1 else 0.0)
                if best is None or sc < best[0]:
                    best = (sc, ks, (p1, mde, alpha, power, good, traffic, dict(nums)))
        if best is not None and best[0] <= 2.5:
            break
    if best is None:
        raise RuntimeError("не удалось подобрать параметры")
    _, kinds, (p1, mde, alpha, power, good, traffic, nums) = best
    if ask == "n":
        texts = {k: f"≈ {_fmt_n(v)} {who} в каждой группе" for k, v in nums.items()}
    else:
        texts = {k: f"{v} {_days_word(v)}" for k, v in nums.items()}
    rng.shuffle(kinds)
    check_lengths(list(texts.values()))
    opts, key = balanced_options(FAMILY_ID, seed, rng, (texts["good"], None),
                                 [(texts[k], None) for k in kinds])
    options = [(o.text, next(nums[k] for k in ["good", *kinds] if texts[k] == o.text)) for o in opts]
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
           "one_group": "учтён размер только одной группы, хотя трафик делится на две — дней вдвое меньше нужного",
           "no_square": "сумма квантилей не возведена в квадрат",
           "beta_two_sided": "квантиль мощности взят как двусторонний: z(1 − β/2) вместо z(1 − β)",
           "za_twice": "квантиль мощности приравнен к квантилю значимости: z(1 − α/2) вместо z(1 − β)"}
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
                                 "power": power, "traffic": traffic, "kinds": kinds,
                                 "n_below": n_below})
