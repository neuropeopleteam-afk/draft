"""devops.cloud.principal_commit_capacity_mcq — mcq_concept (Principal): сколько мощности зарезервировать на год.

Недельный профиль нагрузки — четыре уровня (число ВМ) с числом часов в неделю; нагрузка растёт на g за квартал
(все уровни умножаются на (1 + g)^q в квартале q = 0…3, округление до целых ВМ). Резерв на год: N ВМ по цене
r = o·(1 − скидка) за час оплачиваются все часы года; сверх N — по требованию по цене o. Какое N минимизирует
цену года?

Ключ — решение «газетчика» по году: резервировать, пока доля часов года с нагрузкой ≥ N больше 1 − скидка; ответ —
одно из значений уровней с учётом роста. Ловушки одной формы (число ВМ), ранг ключа задаётся по seed до подбора
чисел (0–3 выше ключа) и выбирается через spread_pick. Ключ проверяется исполнением: программа считает цену года для
каждого N от 0 до пика через год по поквартальным профилям и печатает минимум.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import pick_traps, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural, text_table

FAMILY_ID = "devops.cloud.principal_commit_capacity_mcq"

CONTEXTS = ["кластер обработки заказов", "фермы сборки CI", "кластер API мобильного приложения",
            "кластер поиска по каталогу", "кластер обработки видео", "кластер расчёта отчётов",
            "кластер приёма телеметрии"]
HOURS = [(56, 60, 40, 12), (60, 50, 40, 18), (70, 50, 36, 12), (48, 64, 44, 12), (84, 42, 30, 12)]
WEEKS = 13

PROGRAM = """opts = __OPTS__
levels, hours, g, o, disc = {levels!r}, {hours!r}, {g}, {o}, {disc}
r = o * (1 - disc)
profiles = [[(round(L * (1 + g) ** q), h) for L, h in zip(levels, hours)] for q in range(4)]
top = max(load for prof in profiles for load, _h in prof)
best, best_cost = None, None
for n in range(0, top + 1):
    cost = 0.0
    for prof in profiles:                       # квартал: 13 недель
        for week in range({weeks}):
            for load, h in prof:
                cost += h * (n * r + max(0, load - n) * o)
    if best_cost is None or cost < best_cost - 1e-6:
        best, best_cost = n, cost
hit = [k for k, t in opts.items() if int(t.split(" ")[0]) == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _profiles(levels, hours, g, quarters=4):
    return [[(round(L * (1 + g) ** q), h) for L, h in zip(levels, hours)] for q in range(quarters)]


def _opt(profiles, disc, invert=False):
    """Наименьшее N, при котором доля часов с нагрузкой > N не больше порога (1 − скидка; перевёрнуто — скидка)."""
    thr = disc if invert else 1 - disc
    pts = [(load, h) for prof in profiles for load, h in prof]
    total = sum(h for _l, h in pts)
    for n in sorted({load for load, _h in pts}):
        if sum(h for load, h in pts if load > n) / total <= thr + 1e-12:
            return n
    return max(load for load, _h in pts)


def _year_cost(profiles, n, o, disc):
    r = o * (1 - disc)
    return WEEKS * sum(h * (n * r + max(0, load - n) * o) for prof in profiles for load, h in prof)


def _sample(rng):
    base = rng.choice([12, 15, 18, 20, 24, 30])
    steps = [rng.choice([0.2, 0.3, 0.4]), rng.choice([0.2, 0.3, 0.45]), rng.choice([0.25, 0.4, 0.6])]
    levels = [base]
    for s in steps:
        levels.append(round(levels[-1] * (1 + s)))
    return {"levels": levels, "hours": list(rng.choice(HOURS)), "g": rng.choice([0.05, 0.1, 0.15, 0.2]),
            "o": rng.choice([8, 10, 12, 15]), "disc": rng.choice([0.25, 0.3, 0.4, 0.5, 0.6])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_above = make_rng(FAMILY_ID, seed // 4, "rank").sample(range(4), 4)[seed % 4]

    def accept(p):
        prof = _profiles(p["levels"], p["hours"], p["g"])
        good = _opt(prof, p["disc"])
        if not (15 <= good <= 82):
            return None
        costs = {n: _year_cost(prof, n, p["o"], p["disc"]) for n in range(0, prof[-1][-1][0] + 1)}
        srt = sorted(costs.values())
        if min(costs, key=costs.get) != good or srt[1] - srt[0] < 1e-3 * srt[0] * 0.01:
            return None
        now = prof[:1]
        avg_now = round(sum(L * h for L, h in now[0]) / 168)
        avg_year = round(sum(L * h for qprof in prof for L, h in qprof) / (4 * 168))
        cand_raw = {
            "peak_now": p["levels"][-1],
            "peak_year": prof[-1][-1][0],
            "peak_q2": prof[1][-1][0],
            "subpeak_q4": prof[-1][-2][0],
            "avg_now": avg_now,
            "avg_year": avg_year,
            "no_growth": _opt(now, p["disc"]),
            "base_only": p["levels"][0],
            "base_q4": prof[-1][0][0],
            "inverted": _opt(prof, p["disc"], invert=True),
        }
        cand = {k: v for k, v in cand_raw.items() if v != good and 10 <= v <= 99}
        traps = pick_traps(rng, good, cand, n_above, rel=0.08, abs_min=2)
        if traps is None:
            return None
        if any(costs.get(cand[t], float("inf")) < costs[good] * 1.01 for t in traps):
            return None
        return good, cand, traps, costs

    p, (good, cand, traps, costs) = search(rng, _sample, accept)
    vm = lambda n: f"{n} ВМ"
    rows = [(f"{L} ВМ", f"{h} {plural(h, 'час', 'часа', 'часов')}") for L, h in zip(p["levels"], p["hours"])]
    table = text_table(["Нагрузка", "Часов в неделю"], rows)
    gtxt = ("нагрузка не растёт" if p["g"] == 0 else
            f"нагрузка растёт на {fmt_num(100 * p['g'], 0)} % за квартал (все уровни; в квартале q уровень × "
            f"{fmt_num(1 + p['g'], 2)}^q, q = 0…3, округление до целых ВМ)")
    stem = (f"Вы планируете закупку мощности на год — {ctx}. Текущий недельный профиль:\n{table}\n"
            f"По плану продукта {gtxt}. Резерв на год: N ВМ со скидкой {fmt_num(100 * p['disc'], 0)} % от цены по "
            f"требованию ({p['o']} ₽ за ВМ-час), оплачиваются все часы года независимо от загрузки; всё, что сверх N, — "
            f"по требованию. Сколько ВМ зарезервировать, чтобы цена года была минимальной?")
    pts = sorted({load for prof in _profiles(p["levels"], p["hours"], p["g"]) for load, _h in prof})
    why = {
        "peak_now": "по текущему пику",
        "peak_year": "по пику через год",
        "peak_q2": "по пику второго квартала",
        "subpeak_q4": "по предпиковому уровню четвёртого квартала",
        "avg_now": "по средней текущей нагрузке",
        "avg_year": "по среднегодовой нагрузке",
        "no_growth": "оптимум без учёта роста",
        "base_only": "только постоянная база первого квартала",
        "base_q4": "постоянная база четвёртого квартала",
        "inverted": "перевёрнутое правило (доля часов ≥ скидки)",
    }
    expl = (f"Резервировать N выгодно, пока ВМ номер N занята больше чем в (1 − скидка) = "
            f"{fmt_num(100 * (1 - p['disc']), 0)} % часов года (иначе её дешевле брать по требованию). Уровни года: "
            f"{', '.join(str(x) for x in pts)} ВМ; ответ — {vm(good)}, цена года ≈ {fmt_num(costs[good] / 1e6, 2)} "
            f"млн ₽. Ловушки: " + "; ".join(f"{why[t]} — {vm(cand[t])}" for t in traps) + ".")
    program = PROGRAM.format(levels=p["levels"], hours=p["hours"], g=p["g"], o=p["o"], disc=p["disc"], weeks=WEEKS)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=vm(good),
                       distractors=[vm(cand[t]) for t in traps], program=program, explanation=expl,
                       params={**p, "good": good, "n_above": n_above, "traps": {t: cand[t] for t in traps}},
                       note="Ответ проверяется программой: цена года для каждого N по поквартальным профилям.")
