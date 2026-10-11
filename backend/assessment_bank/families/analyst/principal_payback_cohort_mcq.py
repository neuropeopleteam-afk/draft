"""analyst.principal.payback_cohort_mcq — mcq_concept (Principal, короткое): на каком месяце окупится привлечение
клиента при кривой удержания когорты «резкий отток в первый месяц, дальше — постоянный».

CAC — стоимость привлечения одного клиента, m — маржа с активного клиента в месяц. В месяц 1 активны все, в месяц 2 —
доля r1, дальше каждый месяц остаётся доля d от активных прошлого месяца. Окупаемость — первый месяц t, когда
накопленная маржа m · Σ_{i ≤ t} активные_i ≥ CAC. Ключ — t.

Ловушки: ниже ключа — ``no_churn`` (⌈CAC / m⌉: без оттока), ``d_from_start`` (удержание d с первого месяца, без
резкого оттока), ``r1_flat`` (после первого месяца больше никто не уходит); выше ключа — ``r1_compound`` (доля r1
каждый месяц), ``d_twice`` (d применяется и в месяце 2 поверх r1), ``r1_ratio`` (⌈CAC / (m · r1)⌉: «средний
активный — r1»), ``r1_first`` (отток r1 уже в месяце привлечения). Сколько ловушек меньше ключа — 1–3
равновероятно. Ключ проверяется исполнением: программа имитирует когорту из 10 000 клиентов помесячно в целых
числах (точные дроби) и считает накопленную маржу.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.principal.payback_cohort_mcq"

CONTEXTS = ["сервис доставки продуктов", "онлайн-школа", "приложение для фитнеса", "облачная бухгалтерия для ИП",
            "сервис подписки на кофе", "онлайн-кинотеатр", "сервис аренды самокатов", "приложение изучения языков"]

PROGRAM = """from fractions import Fraction as F

{fmt}
CAC, m, r1, d = {cac}, {m}, F({r1}, 100), F({d}, 100)
cohort = F(10000)                   # клиентов в когорте
active, earned, month = cohort, F(0), 0
while True:
    month += 1
    if month == 2:
        active = cohort * r1
    elif month > 2:
        active = active * d
    earned += active * m
    if earned >= CAC * cohort:
        break
    if month > 1000:
        break
print(fmt(month))
"""


def _payback(cac, m, curve, limit=1000):
    earned = 0.0
    for t in range(1, limit + 1):
        earned += m * curve(t)
        if earned >= cac - 1e-9:
            return t
    return None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([1, 2, 3])
    fmt, fmt_src = formatter("int", "мес.")
    for _ in range(6000):
        m = rng.choice([150, 200, 250, 300, 400, 500])
        cac = m * rng.choice([6, 7, 8, 9, 10, 12, 14])
        r1 = rng.choice([40, 50, 55, 60, 65, 70])
        d = rng.choice([90, 92, 94, 95, 96, 97, 98])
        R1, D = r1 / 100, d / 100
        good = _payback(cac, m, lambda t: 1 if t == 1 else R1 * D ** (t - 2))
        if good is None:
            continue
        # запас до порога: накопленная маржа в месяц ключа не на волоске от CAC
        acc = sum(m * (1 if t == 1 else R1 * D ** (t - 2)) for t in range(1, good + 1))
        if acc - cac < 0.02 * cac and acc - cac < m * 0.05:
            continue
        pool = {"no_churn": math.ceil(cac / m), "d_from_start": _payback(cac, m, lambda t: D ** (t - 1)),
                "r1_flat": _payback(cac, m, lambda t: 1 if t == 1 else R1),
                "r1_compound": _payback(cac, m, lambda t: R1 ** (t - 1)),
                "d_twice": _payback(cac, m, lambda t: 1 if t == 1 else R1 * D ** (t - 1)),
                "r1_ratio": math.ceil(cac / (m * R1) - 1e-9),
                "r1_first": _payback(cac, m, lambda t: R1 * D ** (t - 1))}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.08, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    stem = (f"{ctx[0].upper() + ctx[1:]}: привлечение одного клиента стоит {cac} ₽, маржа с активного клиента — {m} ₽ в месяц. "
            f"По когортам: во втором месяце активны {r1} % пришедших, дальше каждый месяц остаётся {d} % активных "
            f"прошлого месяца. На каком месяце (считая месяц привлечения первым) накопленная маржа когорты впервые "
            f"покроет стоимость привлечения?")
    pool_txt = {k: (str(v) if v else "не окупается") for k, v in pool.items()}
    why = (f"Активные по месяцам: 1; {r1} %; {r1} % × {d} %; … Накопленная маржа на клиента достигает {cac} ₽ на "
           f"месяце {good}. Ошибки: без оттока — {pool_txt['no_churn']}; удержание {d} % с первого месяца без резкого "
           f"оттока — {pool_txt['d_from_start']}; после второго месяца никто не уходит — {pool_txt['r1_flat']}; доля {r1} % "
           f"каждый месяц — {pool_txt['r1_compound']}; лишний множитель {d} % во втором месяце — {pool_txt['d_twice']}; "
           f"«маржа × {r1} %» на весь срок — {pool_txt['r1_ratio']}; отток уже в первом месяце — {pool_txt['r1_first']}. "
           f"Вывод: окупаемость канала определяется формой кривой удержания — резким оттоком первого месяца и "
           f"хвостом, а не средним удержанием.")
    program = PROGRAM.format(fmt=fmt_src, cac=cac, m=m, r1=r1, d=d)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, params={"cac": cac, "m": m, "r1": r1, "d": d},
                       note="Программа имитирует когорту из 10 000 клиентов помесячно точными дробями.")
