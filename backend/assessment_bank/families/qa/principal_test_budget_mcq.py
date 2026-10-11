"""qa.principal.test_budget_mcq — mcq_concept (Principal): какие наборы регрессии запустить в бюджет конвейера.

Изменение в одном модуле; граф «модуль использует модули» (поведение меняется у изменённого модуля и у всех, кто
использует его прямо или через другие модули — транзитивно). Для каждого модуля — оценка ущерба от пропущенного
дефекта (баллы); наборы тестов — длительность и список проверяемых модулей; бюджет времени конвейера. Ущерб модуля
засчитывается, если модуль затронут изменением и проверен хотя бы одним запущенным набором (перекрытие наборов не
удваивает); при равном ущербе — меньшее время.

Дистракторы (фиксированный состав, все — разные наборы): ``direct`` — оптимум при затронутых «изменённый + прямые
пользователи» (без транзитивности); ``additive`` — оптимум, если складывать ценность наборов независимо (перекрытие
посчитано дважды); ``greedy`` — жадный отбор по ценности на минуту без пересчёта перекрытия. Ключ проверяется
исполнением: программа строит транзитивное замыкание графа и перебирает все подмножества наборов.
"""
from __future__ import annotations

from itertools import combinations

from assessment_bank.families._lead_b_utils import computed_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "qa.principal.test_budget_mcq"

CONTEXTS = ["интернет-магазин", "мобильный банк", "сервис доставки", "платформа бронирования", "онлайн-кинотеатр",
            "сервис такси", "страховой кабинет", "маркетплейс услуг"]
MODULES = ["платежи", "корзина", "каталог", "профиль", "скидки", "доставка", "уведомления", "отчёты", "склад",
           "авторизация", "поиск", "лояльность", "тарифы", "чеки"]
SUITES = ["П1", "П2", "П3", "П4", "П5", "П6"]

PROGRAM = '''from itertools import combinations

USES = {uses!r}
CHANGED = {changed!r}
RISK = {risk!r}
SUITES = {suites!r}
BUDGET = {budget}

affected = {{CHANGED}}
grew = True
while grew:   # транзитивное замыкание: кто использует затронутый модуль, тот затронут
    grew = False
    for m, deps in USES.items():
        if m not in affected and affected & set(deps):
            affected.add(m)
            grew = True

best = None
names = list(SUITES)
for k in range(1, len(names) + 1):
    for sel in combinations(names, k):
        t = sum(SUITES[s][0] for s in sel)
        if t > BUDGET:
            continue
        covered = set().union(*(SUITES[s][1] for s in sel)) & affected
        score = (sum(RISK[m] for m in covered), -t)
        if best is None or score > best[0]:
            best = (score, sel)
print("запустить " + ", ".join(best[1]))
'''


def _closure(uses: dict[str, list[str]], changed: str, transitive: bool) -> set[str]:
    aff = {changed}
    if not transitive:
        return aff | {m for m, deps in uses.items() if changed in deps}
    grew = True
    while grew:
        grew = False
        for m, deps in uses.items():
            if m not in aff and aff & set(deps):
                aff.add(m)
                grew = True
    return aff


def _best(suites, budget, value):
    """Подмножество с максимальной ценностью value(sel), при равенстве — меньшим временем; None, если не единственно."""
    scored = []
    for k in range(1, len(suites) + 1):
        for sel in combinations(sorted(suites), k):
            t = sum(suites[s][0] for s in sel)
            if t <= budget:
                scored.append(((value(sel), -t), sel))
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _opt(sel) -> str:
    return "запустить " + ", ".join(sel)


def _build(rng):
    mods = rng.sample(MODULES, 8)
    uses: dict[str, list[str]] = {}
    for i, m in enumerate(mods):
        if i == 0:
            uses[m] = []
            continue
        k = min(i, rng.choice([1, 1, 2]))
        uses[m] = sorted(rng.sample(mods[:i], k), key=mods.index)
    changed = rng.choice(mods[:3])
    risk = {m: rng.choice([2, 3, 4, 5, 6, 7, 8, 9]) for m in mods}
    suites = {}
    for s in SUITES:
        cov = sorted(rng.sample(mods, rng.choice([2, 2, 3])), key=mods.index)
        suites[s] = (rng.choice([5, 10, 15, 20, 25, 30]), cov)
    total = sum(t for t, _ in suites.values())
    budget = int(round(total * rng.choice([0.35, 0.4, 0.45, 0.5]) / 5) * 5)
    return mods, uses, changed, risk, suites, budget


def _solve(uses, changed, risk, suites, budget):
    aff_t = _closure(uses, changed, True)
    aff_d = _closure(uses, changed, False)
    if aff_t == aff_d or not 4 <= len(aff_t) <= 6:
        return None

    def cover(aff):
        return lambda sel: sum(risk[m] for m in set().union(*(suites[s][1] for s in sel)) & aff)

    def additive(sel):
        return sum(sum(risk[m] for m in set(suites[s][1]) & aff_t) for s in sel)

    good = _best(suites, budget, cover(aff_t))
    direct = _best(suites, budget, cover(aff_d))
    add = _best(suites, budget, additive)
    if not good or not direct or not add:
        return None
    vals = {s: sum(risk[m] for m in set(suites[s][1]) & aff_t) for s in suites}
    order = sorted(suites, key=lambda s: (-vals[s] / suites[s][0], s))
    greedy, t = [], 0
    for s in order:
        if vals[s] > 0 and t + suites[s][0] <= budget:
            greedy.append(s)
            t += suites[s][0]
    greedy = tuple(sorted(greedy))
    sets = [good, direct, add, greedy]
    if len({tuple(x) for x in sets}) != 4 or not all(1 <= len(x) <= 4 for x in sets):
        return None
    return aff_t, aff_d, good, direct, add, greedy, vals


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    for _ in range(3000):
        mods, uses, changed, risk, suites, budget = _build(rng)
        res = _solve(uses, changed, risk, suites, budget)
        if res is None:
            continue
        aff_t, aff_d, good, direct, add, greedy, vals = res
        texts = [_opt(x) for x in (good, direct, add, greedy)]
        lens = [len(x) for x in texts]
        if max(lens) <= min(lens) * 1.35 + 6:
            break
    else:  # pragma: no cover - генератор подобран так, что вариант находится
        raise RuntimeError("не удалось построить вариант")

    def tl(sel):
        return sum(suites[s][0] for s in sel)

    def cv(sel):
        n = sum(risk[m] for m in set().union(*(suites[s][1] for s in sel)) & aff_t)
        return f"{n} {plural(n, 'балл', 'балла', 'баллов')}"

    data = ["Граф зависимостей (модуль → какие модули он использует):"]
    data += [f"  {m} → {', '.join(d) if d else '—'}" for m, d in uses.items()]
    data.append("Ущерб от пропущенного дефекта (баллы): " + "; ".join(f"{m} {risk[m]}" for m in mods))
    data.append("Наборы регрессии (время, проверяемые модули):")
    data += [f"  {s} — {t} мин: {', '.join(c)}" for s, (t, c) in suites.items()]
    data.append(f"Бюджет конвейера на регрессию: {budget} мин")
    code = "\n".join(data)
    stem = (f"{ctx.capitalize()}: изменение внесено в модуль «{changed}». Полная регрессия не помещается в бюджет "
            f"конвейера ({budget} мин), нужно выбрать наборы тестов. Поведение может измениться у изменённого "
            f"модуля и у модулей, которые от него зависят. Ущерб модуля засчитывается как выявляемый, если модуль "
            f"может быть задет изменением и проверен хотя бы одним из запущенных наборов. Какие наборы запустить, "
            f"чтобы выявляемый ущерб был наибольшим (при равенстве — с меньшим временем)?")
    order_aff = [m for m in mods if m in aff_t]
    extra = [m for m in order_aff if m not in aff_d]
    why = (f"Затронуты транзитивно: {', '.join(order_aff)} — «{changed}» и все, кто использует его прямо или через "
           f"другие модули (только по прямым связям выпадают: {', '.join(extra)}). Перебор наборов в бюджет {budget} "
           f"мин: {', '.join(good)} — выявляемый ущерб {cv(good)} за {tl(good)} мин. Без транзитивности "
           f"получается {', '.join(direct)} ({cv(direct)} по честному счёту). Если складывать ценность "
           f"наборов независимо, перекрытие считается дважды и выбирается {', '.join(add)} ({cv(add)}). "
           f"Жадный отбор по ценности на минуту без пересчёта перекрытия даёт {', '.join(greedy)} ({cv(greedy)})"
           f". Вывод для программы качества: выбор тестов — по графу влияния изменения и с учётом "
           f"перекрытия наборов, а не по отдельным «самым ценным» наборам.")
    program = PROGRAM.format(uses=uses, changed=changed, risk=risk,
                             suites={s: (t, list(c)) for s, (t, c) in suites.items()}, budget=budget)
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=_opt(good),
                        distractors=[_opt(direct), _opt(add), _opt(greedy)], program=program, why=why,
                        context=ctx, code=code, language="text",
                        note="Программа строит транзитивное замыкание графа зависимостей и перебирает все "
                             "подмножества наборов в бюджет по тем же числам.",
                        params={"changed": changed, "budget": budget, "n_affected": len(aff_t)})
