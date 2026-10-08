"""data_ml.stats.mean_median_output — predict_output: среднее и медиана ряда с выбросом.

Лёгкое семейство у порога Junior (грейд «Стажёр»): 5–7 целых значений, одно из них — выброс; программа
печатает среднее и медиану через `statistics`. Единственная ловушка — медиана не реагирует на выброс
(и для чётного числа значений равна полусумме двух средних), среднее сдвигается. Значения подобраны так,
что среднее — целое или .5. Исполняется Python; ключ — независимый расчёт в генераторе.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.stats.mean_median_output"

CONTEXTS = [("время ответа API, мс", "latency_ms", (20, 60), (400, 900)),
            ("зарплаты в отделе, тыс.", "salaries", (40, 90), (300, 600)),
            ("чеки за день, евро", "receipts", (10, 50), (300, 700)),
            ("длительность звонков, мин", "durations", (2, 9), (60, 120)),
            ("оценки за тест", "scores", (60, 95), (0, 5))]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, (lo, hi), (olo, ohi) = rng.choice(CONTEXTS)
    while True:
        n = rng.randint(5, 7)
        vals = [rng.randint(lo, hi) for _ in range(n - 1)] + [rng.randint(olo, ohi)]
        rng.shuffle(vals)
        s = sum(vals)
        mean = Fraction(s, n)
        if mean.denominator in (1, 2):
            break
    srt = sorted(vals)
    median = Fraction(srt[n // 2]) if n % 2 else Fraction(srt[n // 2 - 1] + srt[n // 2], 2)
    fmt = lambda f: str(int(f)) if f.denominator == 1 else f"{float(f):.1f}"
    # statistics.mean для int даёт int при целом результате, иначе float; median при чётном n — всегда float
    mean_s = fmt(mean)
    med_s = f"{float(median):.1f}" if n % 2 == 0 else str(int(median))
    code = "\n".join(["import statistics", "", f"{var} = {vals!r}",
                      f'print("mean", statistics.mean({var}))', f'print("median", statistics.median({var}))']) + "\n"
    expected = f"mean {mean_s}\nmedian {med_s}"
    stem = (f"Python ({ctx}). Что напечатает программа? Запишите две строки, как печатает `print` "
            f"(дробные значения — как печатает Python, например `12.5` или `80.0`).")
    why = (f"Сумма {s}, значений {n}: среднее {mean_s}. Отсортированный ряд: {srt}; медиана — "
           + (f"средний элемент {med_s}." if n % 2 else f"полусумма двух средних ({srt[n // 2 - 1]} и {srt[n // 2]}) = {med_s}.")
           + " Выброс сдвигает среднее, но не медиану.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    checks = [Check(name="run", runner="python", program=code, expect="stdout_equals", expected_stdout=expected)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"n": n, "mean": mean_s, "median": med_s})
