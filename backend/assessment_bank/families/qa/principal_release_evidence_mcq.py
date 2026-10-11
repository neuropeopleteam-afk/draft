"""qa.principal.release_evidence_mcq — mcq_concept (Principal, короткое): сколько релизов подряд нужно, чтобы с
заданной уверенностью утверждать, что доля релизов с инцидентом не выше цели программы качества.

Релизы независимы, у каждого вероятность инцидента p_true. Цель — p_true ≤ p. За n релизов было не больше k с
инцидентом. Утверждать с уверенностью 1 − α можно при P(X ≤ k | n, p) ≤ α (иначе такой результат правдоподобен и при
доле, равной цели). Ключ — минимальное n.

Ловушки (пул): ниже ключа — ``ignore_k`` (формула для нуля инцидентов), ``inv_p`` ((k + 1) / p — «в среднем один
инцидент на 1/p релизов»), ``point`` (k / p — точечная оценка равна цели), ``conf_swap`` (P(X ≤ k) ≤ 1 − α);
выше ключа — ``mult_k`` ((k + 1) × формула для нуля), ``two_sided`` (уровень α/2, двусторонний интервал);
``rule3`` (3 / p) — с любой стороны. Сколько ловушек меньше ключа — 1–3 равновероятно.
Ключ проверяется исполнением: программа считает биномиальную функцию распределения точными дробями и
перебирает n.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "qa.principal.release_evidence_mcq"

CONTEXTS = ["мобильный банк", "интернет-магазин", "сервис доставки", "платформа бронирования", "страховой кабинет",
            "онлайн-кинотеатр", "маркетплейс услуг", "сервис такси", "облачная бухгалтерия", "система записи к врачу"]

PROGRAM = """from fractions import Fraction as F
from math import comb

{fmt}
p, alpha, k = F({pn}, {pd}), F({an}, {ad}), {k}
n = k + 1
while True:
    cdf = sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
    if cdf <= alpha:
        break
    n += 1
print(fmt(n))
"""


def _min_n(p: float, alpha: float, k: int) -> int:
    lo, hi = k + 1, 20000
    cdf = lambda n: sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))  # noqa: E731
    while lo < hi:                       # бисекция по монотонной функции n
        mid = (lo + hi) // 2
        if cdf(mid) <= alpha:
            hi = mid
        else:
            lo = mid + 1
    return lo


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([1, 2, 3])
    fmt, fmt_src = formatter("int")
    for _ in range(3000):
        p_pct = rng.choice([1, 1.5, 2, 2.5, 3, 4, 5])
        p = p_pct / 100
        alpha = rng.choice([0.01, 0.05, 0.1])
        k = rng.choice([1, 2])
        good = _min_n(p, alpha, k)
        zero = _min_n(p, alpha, 0)
        pool = {"ignore_k": zero, "inv_p": math.ceil((k + 1) / p), "point": math.ceil(k / p),
                "conf_swap": _min_n(p, 1 - alpha, k), "mult_k": (k + 1) * zero, "two_sided": _min_n(p, alpha / 2, k),
                "rule3": math.ceil(3 / p)}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.08, lo=100, hi=1000)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    conf = f"{round(100 * (1 - alpha))} %"
    p_txt = f"{p_pct:g}".replace(".", ",") + " %"
    stem = (f"{ctx.capitalize()}: цель программы качества — не больше {p_txt} релизов с инцидентом в эксплуатации. "
            f"Руководство просит доказательство: «с уверенностью {conf} доля релизов с инцидентом не выше {p_txt}». "
            f"Релизы считаем независимыми. Среди последних релизов инцидент был не больше чем у {k} "
            f"{plural(k, 'релиза', 'релизов', 'релизов')} — сколько релизов подряд с таким итогом минимально "
            f"нужно, чтобы это утверждение было обоснованным "
            f"(односторонняя проверка)?")
    p_frac = (int(round(p_pct * 10)), 1000)
    a_frac = (int(round(alpha * 100)), 100)
    why = (f"Нужно наименьшее n, при котором «не больше {k} инцидентов из n» маловероятно (≤ {round(100 * alpha)} %) "
           f"при доле, равной цели: P(X ≤ {k} | n, {p_txt}) ≤ α — это n = {good}. Ошибки: формула для нуля "
           f"инцидентов ln α / ln(1 − p) — {pool['ignore_k']}; её умножение на k + 1 — {pool['mult_k']}; "
           f"(k + 1) / p — {pool['inv_p']}; точечная оценка k / n = p — {pool['point']}; двусторонний уровень "
           f"α/2 — {pool['two_sided']}; правило «3 / p» верно только для нуля инцидентов и уверенности 95 % — "
           f"{pool['rule3']}; перепутанный уровень (≤ 1 − α) — {pool['conf_swap']}. Вывод: доказательство цели "
           f"по качеству релизов требует числа наблюдений, растущего с допуском инцидентов и уверенностью.")
    program = PROGRAM.format(fmt=fmt_src, pn=p_frac[0], pd=p_frac[1], an=a_frac[0], ad=a_frac[1], k=k)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, params={"p_pct": p_pct, "alpha": alpha, "k": k},
                       note="Программа считает биномиальную функцию распределения точными дробями и перебирает n.")
