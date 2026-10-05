"""data_ml.stats.ztest_fix — choose_fix: двусторонний z-тест разности долей в A/B-тесте.

Функция считает p-value z-теста для двух долей с объединённой оценкой дисперсии под H0, но
возвращает одностороннюю вероятность P(Z > z). Из четырёх исправлений ровно одно даёт
двусторонний p-value для любых знаков эффекта. Дистракторы: нет модуля (p > 1 при
ухудшении), нет деления на √2 в erfc, удвоенная двусторонняя вероятность, неверная
стандартная ошибка (общий n вместо 1/n_a + 1/n_b).
"""
from __future__ import annotations

import math
from statistics import NormalDist

from assessment_bank.gen_utils import build_variant, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options

FAMILY_ID = "data_ml.stats.ztest_fix"

CONTEXTS = [("конверсия в покупку", "orders"), ("CTR баннера", "clicks"),
            ("доля продлений подписки", "renewals"), ("конверсия в регистрацию", "signups"),
            ("доля успешных оплат", "payments")]
DISTRACTORS = ["no_abs", "no_sqrt2", "doubled", "se_total"]


def _func(kind, fn, x):
    se = "    se = math.sqrt(p * (1 - p) * (1 / n_a + 1 / n_b))"
    if kind == "se_total":
        se = "    se = math.sqrt(p * (1 - p) / (n_a + n_b))"
    ret = {"good": "    return math.erfc(abs(z) / math.sqrt(2))",
           "buggy": "    return 0.5 * math.erfc(z / math.sqrt(2))",
           "no_abs": "    return math.erfc(z / math.sqrt(2))",
           "no_sqrt2": "    return math.erfc(abs(z))",
           "doubled": "    return 2 * math.erfc(abs(z) / math.sqrt(2))",
           "se_total": "    return math.erfc(abs(z) / math.sqrt(2))"}[kind]
    return "\n".join([f"def {fn}({x}_a, n_a, {x}_b, n_b):",
                      f"    p_a, p_b = {x}_a / n_a, {x}_b / n_b",
                      f"    p = ({x}_a + {x}_b) / (n_a + n_b)",
                      se,
                      "    z = (p_b - p_a) / se",
                      ret])


def _ref(xa, na, xb, nb):
    pa, pb = xa / na, xb / nb
    p = (xa + xb) / (na + nb)
    z = (pb - pa) / math.sqrt(p * (1 - p) * (1 / na + 1 / nb))
    return 2 * (1 - NormalDist().cdf(abs(z)))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, x = rng.choice(CONTEXTS)
    fn = rng.choice(["ab_pvalue", "two_prop_pvalue", "ztest_pvalue"])
    for _ in range(1000):
        n = rng.choice([4000, 5000, 8000, 10000, 12000])
        base = rng.uniform(0.03, 0.2)
        xa = int(n * base)
        xb = xa + rng.choice([-1, 1]) * rng.randint(int(0.06 * xa) + 1, int(0.18 * xa) + 2)
        p_two = _ref(xa, n, xb, n)
        if 0.005 < p_two < 0.2 and xb > xa:
            break
    p_one = p_two / 2
    buggy = "import math\n\n\n" + _func("buggy", fn, x)
    chosen = rng.sample(DISTRACTORS, 3)
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить функцию на:", _func("good", fn, x)),
                             [("Заменить функцию на:", _func(d, fn, x)) for d in chosen])
    cases = [(xa, n, xb, n), (xb, n, xa, n), (120, 3000, 150, 3100), (400, 9000, 330, 8800),
             (50, 1000, 50, 1000)]
    tests = "\n".join(f"assert abs({fn}{c!r} - {_ref(*c)!r}) < 1e-9" for c in cases)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, tests), expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python",
                            program=py_harness("import math\n\n\n" + o.code, tests),
                            embeds_display_code=False,
                            expect="pass" if o.id == key else "fail"))
    stem = (f"Метрика A/B-теста — {ctx}. Аналитик написал функцию p-value для двустороннего "
            f"z-теста разности долей (дисперсия оценивается по объединённой доле, как под H0). "
            f"Для A: {xa} из {n}, B: {xb} из {n} функция вернула {p_one:.4f}, а проверенный "
            f"калькулятор — {p_two:.4f}; если поменять группы местами, функция выдаёт "
            f"{1 - p_one:.4f}. Какое исправление функции верно для любых данных?")
    why = {"no_abs": "без модуля при отрицательном z получается значение больше 1",
           "no_sqrt2": "erfc(x/√2) = 2·(1 − Φ(x)); без деления на √2 считается другая величина",
           "doubled": "2·erfc(|z|/√2) — это удвоенный двусторонний p-value",
           "se_total": "стандартная ошибка разности долей — √(p(1−p)(1/n_a + 1/n_b)), а не √(p(1−p)/(n_a + n_b))"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Исходная функция возвращает одностороннюю вероятность 1 − Φ(z). "
                               "Двусторонний p-value = 2·(1 − Φ(|z|)) = erfc(|z|/√2). Ошибки "
                               "дистракторов: " + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="one_sided_pvalue",
                         params={"distractors": chosen, "xa": xa, "xb": xb, "n": n})
