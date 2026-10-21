"""qa.strategy.lp3_risk_regression_budget_output — predict_output: максимум покрытого риска регресса в бюджет времени.

Перед срочным релизом есть T минут на регресс. У каждого набора тестов — время и «очки риска» (вес сценариев,
которые он закрывает); наборы, закрывающие одну и ту же область, взаимоисключающие по пользе — в таблице
область указана, очки области засчитываются один раз (по лучшему набору). Нужно максимальное число очков риска.
Решение — перебор; жадный выбор по «очкам на минуту» и по «очкам» не оптимален. Ловушки: жадный выбор; суммировать
очки дублирующих наборов одной области. Ответ — целое число очков.
"""
from __future__ import annotations

from itertools import combinations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.strategy.lp3_risk_regression_budget_output"
AREAS = ["оплата", "вход", "корзина", "доставка", "промокоды", "профиль", "уведомления", "поиск", "возвраты"]

CALC = r'''
from itertools import combinations
T, rows = None, []
for l in DATA.splitlines():
    if l.startswith("бюджет"):
        T = int(l.split(":")[1].split()[0])
    elif l.count("|") == 3 and "очки" not in l:
        n, area, mins, pts = [x.strip() for x in l.split("|")]
        rows.append((area, int(mins), int(pts)))
best = 0
for k in range(len(rows) + 1):
    for c in combinations(range(len(rows)), k):
        if sum(rows[i][1] for i in c) > T:
            continue
        by = {}
        for i in c:
            by[rows[i][0]] = max(by.get(rows[i][0], 0), rows[i][2])
        best = max(best, sum(by.values()))
print(best)
'''


def _score(rows, c):
    by = {}
    for i in c:
        by[rows[i][0]] = max(by.get(rows[i][0], 0), rows[i][2])
    return sum(by.values())


def _best(rows, T):
    best = 0
    for k in range(len(rows) + 1):
        for c in combinations(range(len(rows)), k):
            if sum(rows[i][1] for i in c) <= T:
                best = max(best, _score(rows, c))
    return best


def _greedy(rows, T, key):
    used, t = [], 0
    for i in sorted(range(len(rows)), key=key):
        if t + rows[i][1] <= T:
            used.append(i)
            t += rows[i][1]
    return _score(rows, used)


PRODUCTS = ["интернет-магазин", "мобильный банк", "сервис доставки еды", "онлайн-кинотеатр", "сервис такси",
            "маркетплейс услуг"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    prod = rng.choice(PRODUCTS)
    for _ in range(3000):
        n = rng.randint(9, 12)
        areas = rng.sample(AREAS, rng.randint(5, 7))
        rows = [(rng.choice(areas), rng.choice([5, 8, 10, 12, 15, 20, 25, 30, 40]), rng.choice([3, 5, 8, 10, 13, 20, 30]))
                for _ in range(n)]
        T = rng.choice([45, 60, 75, 90])
        if sum(r[1] for r in rows) <= T:
            continue
        good = _best(rows, T)
        g1 = _greedy(rows, T, lambda i: -rows[i][2] / rows[i][1])
        g2 = _greedy(rows, T, lambda i: -rows[i][2])
        dup = 0
        used, t = [], 0
        for i in sorted(range(n), key=lambda i: -rows[i][2] / rows[i][1]):
            if t + rows[i][1] <= T:
                used.append(i)
                t += rows[i][1]
        dup = sum(rows[i][2] for i in used)  # дубли областей сложены
        if good in (g1,) and rng.random() < 0.7 or good == g2 and good == g1:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"бюджет: {T} мин", "", "набор | область | мин | очки риска"]
    for i, (a, m, p) in enumerate(rows, 1):
        lines.append(f"R{i} | {a} | {m} | {p}")
    block = "\n".join(lines)
    stem = (f"Продукт «{prod}», срочный релиз: на регресс есть ограниченное время (блок ниже). Для каждого набора тестов известны время и "
            "очки риска — вес пользовательских сценариев, которые он проверяет. Наборы одной области дублируют друг "
            "друга: область засчитывается один раз, по лучшему набору. Наборы запускаются целиком, последовательно. "
            "Какое наибольшее число очков риска можно закрыть в бюджете? Ответ — целое число.")
    expl = (f"Перебор подмножеств наборов с суммарным временем ≤ {T} мин и подсчётом каждой области один раз: максимум "
            f"{good}. Жадно по очкам на минуту — {g1}, по очкам — {g2}; если сложить дубли областей — {dup}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=prod,
                         accept=num_accept(good, ("очков", "очка")), params={"T": T, "rows": rows})
