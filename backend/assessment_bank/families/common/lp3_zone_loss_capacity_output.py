"""common.reliability.lp3_zone_loss_capacity_output — predict_output: сколько экземпляров добавить ради N+1 по зонам.

Сервис в трёх зонах доступности, экземпляров в зонах неодинаково. Требование: при потере ЛЮБОЙ одной зоны
оставшиеся экземпляры выдерживают пик при целевой загрузке. Нужно наименьшее число добавляемых экземпляров
(в любые зоны). Ловушки: проверить только суммарную мощность; считать, что падает «средняя» зона, а не самая
крупная; добавлять поровну во все зоны. Решение — перебор распределений добавки. Ответ — целое число.
"""
from __future__ import annotations

from itertools import product

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.reliability.lp3_zone_loss_capacity_output"
SVCS = ["API каталога", "шлюз платежей", "сервис рекомендаций", "поиск", "сервис профилей", "сервис тарификации"]

CALC = r'''
import re, math
from itertools import product
v, zones = {}, []
for l in DATA.splitlines():
    m = re.match(r"^([^:|]+):\s*(\d+)", l)
    if m:
        v[m.group(1).strip()] = int(m.group(2))
    elif l.count("|") == 1 and "экземпляров" not in l:
        zones.append(int(l.split("|")[1]))
need = math.ceil(v["пик, RPS"] / (v["мощность экземпляра, RPS"] * v["целевая загрузка, %"] / 100))
best = None
for add in product(range(need + 1), repeat=len(zones)):
    z = [a + b for a, b in zip(zones, add)]
    if all(sum(z) - x >= need for x in z):
        s = sum(add)
        best = s if best is None else min(best, s)
print(best)
'''


def _solve(zones, need):
    best = None
    for add in product(range(need + 1), repeat=len(zones)):
        z = [a + b for a, b in zip(zones, add)]
        if all(sum(z) - x >= need for x in z):
            s = sum(add)
            best = s if best is None else min(best, s)
    return best


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SVCS)
    for _ in range(4000):
        cap = rng.choice([200, 250, 300, 400, 500, 800])
        util = rng.choice([60, 65, 70, 75, 80])
        zones = [rng.randint(2, 12) for _ in range(3)]
        peak = rng.randint(4, 30) * 500
        need = -(-peak * 100 // (cap * util))
        if need > 24:
            continue
        good = _solve(zones, need)
        total_only = max(0, need - sum(zones))
        equal = 0
        while True:
            z = [x + equal for x in zones]
            if all(sum(z) - x >= need for x in z):
                break
            equal += 1
        equal *= 3
        if good < 2 or good in (total_only, equal) and rng.random() < 0.8:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    names = ["зона a", "зона b", "зона c"]
    lines = [f"пик, RPS: {peak}", f"мощность экземпляра, RPS: {cap}", f"целевая загрузка, %: {util}", "",
             "зона | экземпляров"] + [f"{nm} | {z}" for nm, z in zip(names, zones)]
    block = "\n".join(lines)
    stem = (f"Сервис «{svc}» работает в трёх зонах доступности (таблица ниже), балансировщик делит нагрузку между "
            "живыми экземплярами поровну. Требование надёжности: при потере любой одной зоны оставшиеся экземпляры "
            "должны выдерживать пик, не превышая целевую загрузку. Экземпляры можно добавлять в любые зоны. Какое "
            "наименьшее число экземпляров нужно добавить? Ответ — целое число (0, если требование уже выполнено).")
    expl = (f"Нужно живых экземпляров: ⌈{peak} / ({cap} · {util} %)⌉ = {need}. Условие — для каждой зоны: сумма "
            f"остальных ≥ {need}; сейчас зоны {zones}. Перебор добавок даёт минимум {good}. Проверка только суммы — "
            f"{total_only}; добавка поровну во все зоны — {equal}. Падать может именно самая крупная зона — её и "
            "надо «закрыть» остальными.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=svc,
                         accept=num_accept(good, ("экземпляров", "экземпляра")),
                         params={"zones": zones, "need": need, "cap": cap, "util": util, "peak": peak})
