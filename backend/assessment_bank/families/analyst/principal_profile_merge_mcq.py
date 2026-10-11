"""analyst.principal.profile_merge_mcq — mcq_concept (Principal, короткое): сколько уникальных клиентов окажется в
едином профиле после слияния двух систем, если правило сопоставления неточно.

В системе A — N_A записей, доля внутренних дублей d_A (записи-повторы того же клиента); в B — N_B и d_B. После
очистки дублей правило сопоставления нашло M пар «один клиент в A и B»; на выборке размечено: точность правила
(доля верных среди найденных пар) — p, полнота (доля найденных среди всех настоящих пар) — r. Настоящих общих
клиентов — M·p / r. Ключ — N_A(1 − d_A) + N_B(1 − d_B) − M·p / r (тыс. клиентов).

Ловушки: выше ключа — ``no_dedupe`` (без очистки внутренних дублей), ``naive_matches`` (вычли M как есть),
``ignore_recall`` (вычли M·p), ``swapped`` (вычли M·r / p); ниже — ``ignore_precision`` (вычли M / r),
``divide_both`` (вычли M / (p·r)). Сколько ловушек меньше ключа — 0–2 равновероятно. Ключ проверяется
исполнением: программа строит модель слияния — клиентов, записи и пары — в целых числах точными дробями.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.principal.profile_merge_mcq"

CONTEXTS = [("банк", "процессинг карт", "система кредитования"), ("страховая компания", "ОСАГО", "ДМС"),
            ("ритейлер", "программа лояльности", "интернет-магазин"), ("телеком-оператор", "биллинг связи", "домашний интернет"),
            ("сеть клиник", "запись к врачу", "лаборатория"), ("авиакомпания", "бронирования", "программа для часто летающих")]

PROGRAM = """from fractions import Fraction as F

{fmt}
NA, dA, NB, dB = {NA}, F({dA}, 100), {NB}, F({dB}, 100)      # записи (тыс.) и доля внутренних дублей
M, p, r = {M}, F({p}, 100), F({r}, 100)                      # найденные пары (тыс.), точность, полнота
clients_A = NA * (1 - dA)                 # уникальные клиенты A после очистки дублей
clients_B = NB * (1 - dB)
true_found = M * p                        # верные среди найденных пар
true_pairs = true_found / r               # все настоящие общие клиенты (найденные — доля r от них)
assert true_pairs <= min(clients_A, clients_B)
print(fmt(float(clients_A + clients_B - true_pairs)))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    org, sa, sb = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2])
    fmt, fmt_src = formatter("int", "тыс.")
    for _ in range(8000):
        NA, NB = rng.choice([300, 400, 500, 600, 700]), rng.choice([150, 200, 250, 300, 350])
        dA, dB = rng.choice([4, 5, 8, 10, 12, 15]), rng.choice([3, 5, 6, 8, 10])
        M = rng.choice([60, 80, 100, 120, 150, 180])
        p, r = rng.choice([80, 85, 90, 95]), rng.choice([60, 65, 70, 75, 80])
        UA, UB = NA * (1 - dA / 100), NB * (1 - dB / 100)
        P, R = p / 100, r / 100
        if M * P / R > min(UA, UB) or M / (P * R) > min(UA, UB) * 1.2:
            continue
        good = UA + UB - M * P / R
        pool = {"no_dedupe": NA + NB - M * P / R, "naive_matches": UA + UB - M, "ignore_recall": UA + UB - M * P,
                "swapped": UA + UB - M * R / P, "ignore_precision": UA + UB - M / R, "divide_both": UA + UB - M / (P * R)}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.03, lo=100, hi=1000)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    code = "\n".join([f"Система A «{sa}»: {NA} тыс. записей, внутренних дублей — {dA} % записей",
                      f"Система B «{sb}»: {NB} тыс. записей, внутренних дублей — {dB} % записей",
                      f"После очистки дублей правило сопоставления нашло {M} тыс. пар «один клиент в A и B»",
                      f"Разметка выборки пар: точность правила — {p} %, полнота — {r} %"])
    stem = (f"{org[0].upper() + org[1:]} строит единый профиль клиента из двух систем. Для бюджета на хранение и "
            f"коммуникации нужно число уникальных клиентов после слияния. Сколько их будет?")
    why = (f"Уникальных в A: {NA} × (1 − {dA} %), в B: {NB} × (1 − {dB} %). Верных пар среди найденных — M·p, а "
           f"найдена лишь доля r настоящих, поэтому общих клиентов M·p / r. Итого {fmt(good)}. Ошибки: без очистки "
           f"дублей — {fmt(pool['no_dedupe'])}; вычли найденные пары как есть — {fmt(pool['naive_matches'])}; без "
           f"полноты — {fmt(pool['ignore_recall'])}; точность и полнота перепутаны — {fmt(pool['swapped'])}; без "
           f"точности — {fmt(pool['ignore_precision'])}; деление на обе метрики — {fmt(pool['divide_both'])}. "
           f"Вывод: размер единого профиля зависит от качества сопоставления — точность убирает ложные пары, "
           f"полнота добавляет ненайденные.")
    why = why.replace("тыс..", "тыс.")
    program = PROGRAM.format(fmt=fmt_src, NA=NA, dA=dA, NB=NB, dB=dB, M=M, p=p, r=r)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=org, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code,
                       params={"NA": NA, "dA": dA, "NB": NB, "dB": dB, "M": M, "p": p, "r": r},
                       note="Программа считает уникальных клиентов и настоящие пары точными дробями.")
