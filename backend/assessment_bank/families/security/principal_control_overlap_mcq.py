"""security.principal.control_overlap_mcq — mcq_concept (Principal, короткое): годовая чистая выгода пакета из двух
защитных мер поверх уже действующей, если меры действуют на одни и те же атаки независимо.

Ожидаемые годовые потери до мер — частота успешных атак λ (в год) × ущерб одного инцидента L. Действующая мера уже
останавливает долю e атак; новые меры A и B останавливают доли a и b дошедших до них атак (независимо), их
годовая стоимость c_A и c_B. Выгода = λ·L·(1 − e)·(1 − (1 − a)(1 − b)) − c_A − c_B.

Ловушки: выше ключа — ``ignore_existing`` (без действующей меры), ``additive`` (доли складываются: a + b),
``no_cost`` (без стоимости мер); ниже ключа — ``max_only`` (засчитана только более сильная мера), ``first_only``
(только мера A), ``both_block`` (атака остановлена, только если её остановили обе меры: a·b). Сколько ловушек меньше
ключа — 0–2 равновероятно. Ключ проверяется исполнением: программа перебирает все исходы «остановила / пропустила»
по трём мерам для одной атаки (точные дроби) и считает ожидаемые потери до и после.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.principal.control_overlap_mcq"

CONTEXTS = [("захват учётных записей клиентов", "защита входа по поведенческим признакам", "MFA для всех клиентов",
             "лимиты частоты входа"),
            ("утечка данных через уязвимости веб-приложений", "межсетевой экран приложений",
             "программа поиска уязвимостей за вознаграждение", "сканирование кода в конвейере"),
            ("программы-вымогатели на рабочих станциях", "EDR на всех рабочих станциях",
             "запрет макросов и неподписанных программ", "фильтрация вложений почты"),
            ("мошеннические переводы", "антифрод-модель транзакций", "подтверждение переводов новым получателям",
             "лимиты на переводы"),
            ("компрометация облачных ключей", "короткоживущие учётные данные", "поиск секретов в репозиториях",
             "сегментация облачных аккаунтов")]

PROGRAM = """from fractions import Fraction as F
from itertools import product

{fmt}
lam, L = F({lam_n}, 10), {L}
STOP = {{"действующая": F({e}, 100), "A": F({a}, 100), "B": F({b}, 100)}}
COST = {cA} + {cB}

def passed(measures):     # доля атак, которую не остановила ни одна мера (перебор исходов)
    total = F(0)
    for outcome in product([True, False], repeat=len(measures)):
        pr = F(1)
        for m, stopped in zip(measures, outcome):
            pr *= STOP[m] if stopped else 1 - STOP[m]
        if not any(outcome):
            total += pr
    return total

before = lam * L * passed(["действующая"])
after = lam * L * passed(["действующая", "A", "B"])
print(fmt(float(before - after - COST)))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, existing, ma, mb = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2])
    fmt, fmt_src = formatter("d1", "млн ₽")
    for _ in range(5000):
        lam10 = rng.choice([3, 4, 5, 6, 8, 10, 12, 15])      # частота × 10
        L = rng.choice([20, 30, 40, 60, 80, 120])
        e = rng.choice([20, 30, 40, 50])
        a, b = rng.sample([30, 40, 50, 60, 70, 80], 2)
        cA, cB = rng.choice([2, 3, 4, 5, 6, 8]), rng.choice([2, 3, 4, 5, 6, 8])
        base = lam10 / 10 * L
        cur = base * (1 - e / 100)
        A, B = a / 100, b / 100
        good = cur * (1 - (1 - A) * (1 - B)) - cA - cB
        pool = {"ignore_existing": base * (1 - (1 - A) * (1 - B)) - cA - cB,
                "additive": cur * min(1.0, A + B) - cA - cB, "no_cost": cur * (1 - (1 - A) * (1 - B)),
                "max_only": cur * max(A, B) - cA - cB, "first_only": cur * A - cA - cB,
                "both_block": cur * A * B - cA - cB}
        traps = pick_traps(good, pool, n_below, rng, fmt, "d1", rel=0.08, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lam_txt = f"{lam10 / 10:g}".replace(".", ",")
    code = "\n".join([f"Риск: {ctx}",
                      f"Успешных атак в год без мер (в среднем): {lam_txt}; ущерб одного инцидента: {L} млн ₽",
                      f"Действующая мера «{existing}» останавливает {e} % атак",
                      f"Мера A «{ma}»: останавливает {a} % дошедших до неё атак, {cA} млн ₽ в год",
                      f"Мера B «{mb}»: останавливает {b} % дошедших до неё атак, {cB} млн ₽ в год",
                      "Меры действуют на атаки независимо друг от друга."])
    stem = (f"Совет директоров спрашивает, окупится ли пакет из двух новых мер против риска «{ctx}». Какова годовая "
            f"чистая выгода пакета A + B (снижение ожидаемых годовых потерь минус стоимость мер)?")
    why = (f"Сейчас ожидаемые потери {lam_txt} × {L} × (1 − {e} %) = {fmt(cur)[:-6]} млн ₽. Атаку пропускают обе "
           f"новые меры с вероятностью (1 − {a} %)(1 − {b} %), значит пакет снимает долю 1 − (1 − a)(1 − b) от текущих "
           f"потерь; минус {cA + cB} млн ₽ — {fmt(good)}. Ошибки: без действующей меры — {fmt(pool['ignore_existing'])}; "
           f"доли складываются — {fmt(pool['additive'])}; без стоимости — {fmt(pool['no_cost'])}; только более "
           f"сильная мера — {fmt(pool['max_only'])}; только A — {fmt(pool['first_only'])}. Вывод: эффект мер, "
           f"действующих на одни атаки, считается по остатку после уже действующих, а не суммой долей.")
    program = PROGRAM.format(fmt=fmt_src, lam_n=lam10, L=L, e=e, a=a, b=b, cA=cA, cB=cB)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code, params={"lam10": lam10, "L": L, "e": e, "a": a, "b": b},
                       note="Программа перебирает исходы «остановила / пропустила» по трём мерам точными дробями.")
