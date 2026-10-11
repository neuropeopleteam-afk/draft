"""mobile.principal.sync_conflict_mcq — mcq_concept (Principal, короткое): сколько конфликтов синхронизации в сутки
даст офлайн-режим на нескольких устройствах — основание для решения «последняя запись побеждает» против слияния.

У пользователя n устройств; в каждом окне офлайн-работы длиной T часов устройство правит общий документ хотя бы раз
с вероятностью 1 − e^{−λT} (правки — поток Пуассона с интенсивностью λ в час, независимо по устройствам). Конфликт в
окне — когда правили хотя бы два разных устройства. Конфликтов в сутки: U · W · P(≥ 2 устройств правили), W — окон
в сутки.

Ловушки: выше ключа — ``any_edit`` (конфликт при любой правке: 1 − q^n), ``edits_ge2`` (две правки любых устройств,
в том числе одного), ``pairs_linear`` (C(n, 2)·(λT)² — приближение для редких правок там, где они не редки); ниже —
``two_devices`` (как будто устройств два), ``all_devices`` (правили все устройства). Сколько ловушек меньше ключа —
0–2 равновероятно. Ключ проверяется исполнением: программа перебирает все 2^n наборов «правило / не правило» по
устройствам точными дробями от e^{−λT}, посчитанного рядом Тейлора.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "mobile.principal.sync_conflict_mcq"

CONTEXTS = [("заметки", "заметку"), ("список покупок семьи", "список"), ("карточка клиента в CRM", "карточку"),
            ("план тренировок", "план"), ("смета ремонта", "смету"), ("чек-лист выездного инспектора", "чек-лист"),
            ("маршрутный лист курьера", "маршрутный лист")]

PROGRAM = """from fractions import Fraction as F
from itertools import product

{fmt}
n, lam, T, U, W = {n}, F({lam_n}, 100), F({T_n}, 10), {U}, {W}
x = lam * T
q = sum(F((-1) ** k) * x ** k / F(__import__("math").factorial(k)) for k in range(40))   # e^(−λT) рядом Тейлора
p = 1 - q                                          # устройство правило в окне
conflict = F(0)
for edited in product([True, False], repeat=n):    # все наборы «правило / не правило»
    pr = F(1)
    for e in edited:
        pr *= p if e else q
    if sum(edited) >= 2:
        conflict += pr
print(fmt(float(U * W * conflict)))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    doc, doc_acc = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2])
    fmt, fmt_src = formatter("int")
    for _ in range(6000):
        n = rng.choice([3, 4, 5])
        lam_n = rng.choice([5, 10, 15, 20, 30, 40])     # правок в час × 100
        T_n = rng.choice([5, 10, 20, 30, 40])            # часов × 10
        U = rng.choice([2_000, 5_000, 10_000, 20_000, 50_000])
        W = rng.choice([2, 3, 4, 6])
        x = lam_n / 100 * T_n / 10
        q = math.exp(-x)
        p = 1 - q
        P = 1 - q ** n - n * p * q ** (n - 1)
        good = U * W * P
        pool = {"any_edit": U * W * (1 - q ** n), "edits_ge2": U * W * (1 - math.exp(-n * x) * (1 + n * x)),
                "pairs_linear": U * W * math.comb(n, 2) * x ** 2, "two_devices": U * W * p ** 2,
                "all_devices": U * W * p ** n}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.1, lo=1000, hi=10000)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lam_txt = f"{lam_n / 100:g}".replace(".", ",")
    T_txt = f"{T_n / 10:g}".replace(".", ",")
    U_txt = f"{U:,}".replace(",", " ")
    dev = "устройства" if n < 5 else "устройств"
    stem = (f"Приложение «{doc}» работает офлайн; синхронизация — по окнам: {W} {plural(W, 'окно', 'окна', 'окон')} в "
            f"сутки, в каждом окне устройства работают офлайн {T_txt} ч, затем отправляют правки. У каждого из {U_txt} "
            f"активных пользователей {n} {dev} с общим доступом; каждое правит {doc_acc} в среднем {lam_txt} раза в час (правки "
            f"случайны и независимы). Конфликт — если в одном окне правили хотя бы два разных устройства. Сколько "
            f"конфликтов в сутки ожидать по всем пользователям (целое число)?")
    x_txt = f"{x:.2f}".replace(".", ",")
    why = (f"Устройство правит в окне с вероятностью p = 1 − e^(−λT) = 1 − e^(−{x_txt})"
           f"; конфликт — когда правили ≥ 2 из {n}: 1 − q^n − n·p·q^(n−1). Итого {fmt(good)} в сутки. Ошибки: "
           f"конфликт при любой правке — {fmt(pool['any_edit'])}; ≥ 2 правок, в том числе одного устройства — "
           f"{fmt(pool['edits_ge2'])}; приближение C(n, 2)·(λT)² — {fmt(pool['pairs_linear'])}; как будто устройства "
           f"два — {fmt(pool['two_devices'])}; правили все — {fmt(pool['all_devices'])}. Вывод: масштаб конфликтов "
           f"задаёт выбор стратегии (слияние по полям или «последняя запись побеждает»), и считать его надо по "
           f"модели, а не по приближению для редких правок.")
    program = PROGRAM.format(fmt=fmt_src, n=n, lam_n=lam_n, T_n=T_n, U=U, W=W)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=doc, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, params={"n": n, "lam_n": lam_n, "T_n": T_n, "U": U, "W": W},
                       note="Программа перебирает все наборы «правило / не правило» по устройствам точными дробями.")
