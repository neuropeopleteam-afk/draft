"""data_ml.py.iqr_outliers — predict_output: квартили через медианы половин и правило IQR.

Квартили считаются явно (медиана нижней и верхней половины отсортированных данных — без
скрытых «методов» квантилей), половина нечётной длины, поэтому квартили — элементы данных.
Ловушки: выбросы печатаются в исходном порядке, а не отсортированными; граница строгая —
значение ровно на границе выбросом не считается (в части вариантов оно есть).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.py.iqr_outliers"

CONTEXTS = [
    ("response_ms", "время ответа API, мс", (80, 200)),
    ("check_rub", "сумма чека, ₽", (300, 900)),
    ("session_min", "длительность сессии, мин", (5, 40)),
    ("delivery_h", "срок доставки, ч", (12, 60)),
    ("weight_g", "вес упаковки, г", (200, 500)),
]


def _quartiles(vals):
    data = sorted(vals)
    half = len(data) // 2
    lo, hi = data[:half], data[-half:]
    return lo[len(lo) // 2], hi[len(hi) // 2]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, descr, (a, b) = rng.choice(CONTEXTS)
    k = rng.choice([1.5, 1.5, 2, 3])
    # Калибровка 05.10: «слишком трудное» (p = 0,01); для Junior основная нагрузка была в ручной
    # сортировке 14–15 чисел, а не в правиле IQR — размер выборки 10–11 (половина нечётной
    # длины 5, квартили остаются элементами данных)
    n = rng.choice([10, 11])
    on_boundary = rng.random() < 0.4
    for _ in range(5000):
        vals = [rng.randint(a, b) for _ in range(n)]
        q1, q3 = _quartiles(vals)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo_b, hi_b = q1 - k * iqr, q3 + k * iqr
        # 1–2 выброса сверху и, иногда, снизу
        n_out = rng.randint(1, 2)
        idx = rng.sample(range(n), n_out + (1 if on_boundary else 0))
        for i in idx[:n_out]:
            vals[i] = int(hi_b) + rng.randint(5, 60)
        if rng.random() < 0.3 and lo_b > 5:
            j = idx[0]
            vals[j] = max(0, int(lo_b) - rng.randint(3, 20))
        if on_boundary:
            if hi_b != int(hi_b):
                continue
            vals[idx[-1]] = int(hi_b)
        q1n, q3n = _quartiles(vals)
        if (q1n, q3n) != (q1, q3):
            continue
        out_list = [x for x in vals if x < lo_b or x > hi_b]
        if out_list and len(set(vals)) >= n - 2:
            break
    else:
        raise RuntimeError("не удалось подобрать данные")
    kk = repr(k)
    code = "\n".join([
        "from statistics import median",
        "",
        f"{name} = {vals!r}",
        f"data = sorted({name})",
        "half = len(data) // 2",
        "q1 = median(data[:half])",
        "q3 = median(data[-half:])",
        "iqr = q3 - q1",
        f"outliers = [x for x in {name} if x < q1 - {kk} * iqr or x > q3 + {kk} * iqr]",
        "print(q1, q3, iqr)",
        "print(outliers)",
    ])
    out = f"{q1} {q3} {iqr}\n{out_list!r}"
    stem = (f"Аналитик ищет выбросы в данных ({descr}) по правилу межквартильного размаха с "
            f"коэффициентом {k}. Что напечатает программа? Запишите вывод точно в том виде, в "
            f"каком его печатает Python.")
    note = " Значение ровно на границе выбросом не считается (сравнение строгое)." if on_boundary else ""
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"Половины по {n // 2} элементов (нечётная длина) — квартили равны "
                               f"их средним элементам: Q1={q1}, Q3={q3}, IQR={iqr}; границы "
                               f"{q1 - k * iqr:g} и {q3 + k * iqr:g}. Выбросы — в исходном "
                               f"порядке.{note}")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=descr,
                         verification="execution", checks=checks,
                         params={"k": k, "n": n, "on_boundary": on_boundary})
