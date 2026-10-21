"""analyst.retention.lp3_cohort_active_output — predict_output: число активных пользователей в целевом месяце.

Новые пользователи по месяцам (когорты) и кривая удержания по «возрасту» когорты (доля активных в месяце 0, 1, 2 …).
Активные в месяце X = Σ по когортам размер · удержание[X − месяц когорты]. Ловушки: применять удержание по
номеру календарного месяца, а не по возрасту когорты; забыть месяц 0 (сам месяц привлечения); суммировать
когорты, привлечённые позже X. Ответ — целое число (округление до целого).
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.retention.lp3_cohort_active_output"
PRODUCTS = ["фитнес-приложение", "сервис доставки продуктов", "онлайн-банк", "приложение для изучения языков",
            "сервис подписки на кофе"]
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг"]

CALC = r'''
coh, ret, target = [], [], None
for l in DATA.splitlines():
    if l.startswith("удержание по возрасту"):
        ret = [int(x.strip().rstrip("%")) / 100 for x in l.split(":", 1)[1].split(";")]
    elif l.startswith("целевой месяц"):
        target = l.split(":")[1].strip()
    elif l.count("|") == 1 and "новых" not in l:
        m, n = [x.strip() for x in l.split("|")]
        coh.append((m, int(n)))
names = [m for m, _ in coh]
names_all = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг"]
X = names_all.index(target)
tot = 0.0
for m, n in coh:
    age = X - names_all.index(m)
    if 0 <= age < len(ret):
        tot += n * ret[age]
print(round(tot))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    prod = rng.choice(PRODUCTS)
    for _ in range(3000):
        k = rng.randint(4, 6)
        start = rng.randint(0, 8 - k)
        months = MONTHS[start:start + k]
        sizes = [rng.randint(8, 60) * 100 for _ in months]
        ret = [100, rng.choice([35, 40, 45, 50, 55])]
        for _ in range(k):
            ret.append(max(5, ret[-1] - rng.choice([3, 5, 8, 10])))
        X = start + rng.randint(2, k - 1)
        target = MONTHS[X]
        tot = sum(n * ret[X - MONTHS.index(m)] / 100 for m, n in zip(months, sizes) if 0 <= X - MONTHS.index(m) < len(ret))
        good = round(tot)
        cal = sum(n * ret[min(len(ret) - 1, X - start)] / 100 for m, n in zip(months, sizes) if MONTHS.index(m) <= X)
        no0 = sum(n * ret[X - MONTHS.index(m) + 1] / 100 for m, n in zip(months, sizes)
                  if 0 <= X - MONTHS.index(m) < len(ret) - 1)
        if abs(tot - round(tot)) > 0.45 or good in (round(cal), round(no0)):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = ["удержание по возрасту когорты (месяц 0, 1, 2 …): " + "; ".join(f"{r}%" for r in ret),
             f"целевой месяц: {target}", "", "когорта | новых пользователей"]
    lines += [f"{m} | {n}" for m, n in zip(months, sizes)]
    block = "\n".join(lines)
    stem = (f"{prod.capitalize()}: новые пользователи по месяцам привлечения и типичная кривая удержания по возрасту "
            "когорты (месяц 0 — месяц привлечения, 100 %). Все месяцы одного года. Сколько активных пользователей "
            "ожидать в целевом месяце, если кривая одинакова для всех когорт? Ответ — целое число (округлите).")
    expl = (f"Для каждой когорты возраст = целевой месяц − месяц привлечения; активные = размер · удержание[возраст]; "
            f"сумма = {tot:.1f} ≈ {good}. Удержание по номеру месяца с начала данных — {round(cal)}; без месяца 0 — "
            f"{round(no0)}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=prod,
                         accept=num_accept(good, ("пользователей",)),
                         params={"months": months, "sizes": sizes, "ret": ret, "target": target})
