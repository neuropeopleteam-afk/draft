"""data_eng.etl.principal_backfill_plan_mcq — mcq_concept (Principal): план пересчёта истории к сроку.

После смены логики витрины нужно пересчитать D дней истории, каждый день-раздел — w узло-часов. Общий кластер из
C узлов: 00:00–06:00 — окно ночных SLA-загрузок (пересчёт в нём запрещён), 09:00–19:00 — аналитики занимают A узлов
(пересчёт на остальных узлах замедляет их запросы — цена β ₽ за каждый такой час), 06:00–09:00 и 19:00–24:00 —
кластер свободен. Временный кластер — K узлов круглосуточно по r ₽ за узло-час плюс разовая плата за подъём; пересчёт сразу на двух
кластерах требует разового сведения и сверки результатов.
Четыре плана: только свободные часы общего кластера; свободные часы и дневные часы рядом с аналитиками; только
временный кластер; временный кластер и свободные часы общего. Какой план успевает к сроку T дней и дешевле
остальных таких?

Ловушки: самый дешёвый план, самый быстрый, расчёт без запрета ночного окна (свободных часов 14 вместо 8),
без цены замедления аналитиков. Ответ выбирается по seed до подбора чисел — равновероятен среди четырёх планов;
отличается хотя бы от двух ловушек; срок окончания каждого плана отстоит от T не меньше чем на 3 %. Ключ проверяется
исполнением: программа почасово распределяет узлы под пересчёт по правилам плана, пока работа не кончится,
и суммирует цену.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.etl.principal_backfill_plan_mcq"

CONTEXTS = ["витрина выручки после смены правил признания", "витрина откликов после исправления дедупликации",
            "витрина остатков после смены единиц учёта", "витрина начислений после смены тарифной логики",
            "витрина сессий после смены правила склейки", "витрина рисков после смены модели лимитов"]
NAMES = {"off": "только свободные часы общего кластера", "day": "свободные часы и днём рядом с аналитиками",
         "temp": "только временный кластер", "temp_off": "временный кластер и свободные часы общего"}
ORDER = ["off", "day", "temp", "temp_off"]

PROGRAM = """opts = __OPTS__
P = {P!r}
names = {names!r}

def run(plan):
    work = P["D"] * P["w"]
    hour = cost = 0.0
    if plan in ("temp", "temp_off"):
        cost += P["startup"]
    if plan == "temp_off":
        cost += P["merge"]                           # сведение результатов двух кластеров
    while work > 1e-9:
        h = int(hour) % 24
        nodes = 0
        if plan in ("off", "day", "temp_off") and (6 <= h < 9 or h >= 19):
            nodes += P["C"]                          # общий кластер свободен
        if plan == "day" and 9 <= h < 19:
            nodes += P["C"] - P["A"]                 # рядом с аналитиками
            cost += P["beta"]
        if plan in ("temp", "temp_off"):
            nodes += P["K"]
            cost += P["K"] * P["r"]
        work -= nodes
        hour += 1
    return hour / 24, cost

res = {{k: run(k) for k in names}}
ok = [k for k, (days, _c) in res.items() if days <= P["T"]]
best = min(ok, key=lambda k: res[k][1])
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _per_day(p, plan, *, night_ok=False):
    free_h = 14 if night_ok else 8
    shared = p["C"] * free_h if plan in ("off", "day", "temp_off") else 0
    daytime = (p["C"] - p["A"]) * 10 if plan == "day" else 0
    temp = p["K"] * 24 if plan in ("temp", "temp_off") else 0
    return shared + daytime + temp


def _hour(p, plan, h, night_ok, analysts):
    nodes, cost = 0, 0.0
    free = 6 <= h < 9 or h >= 19 or (night_ok and h < 6)
    if plan in ("off", "day", "temp_off") and free:
        nodes += p["C"]
    if plan == "day" and 9 <= h < 19:
        nodes += p["C"] - p["A"]
        cost += p["beta"] if analysts else 0.0
    if plan in ("temp", "temp_off"):
        nodes += p["K"]
        cost += p["K"] * p["r"]
    return nodes, cost


def _plan(p, plan, *, night_ok=False, analysts=True):
    """Почасовая имитация (как в программе проверки): целые сутки сразу, последние двое суток — по часам."""
    work = p["D"] * p["w"]
    cost = {"temp": p["startup"], "temp_off": p["startup"] + p["merge"]}.get(plan, 0.0)
    day = [_hour(p, plan, h, night_ok, analysts) for h in range(24)]
    per_day, cost_day = sum(n for n, _c in day), sum(c for _n, c in day)
    full = max(0, int(work // per_day) - 1)
    work -= full * per_day
    cost += full * cost_day
    hour = full * 24
    while work > 1e-9:
        n, c = day[hour % 24]
        work -= n
        cost += c
        hour += 1
    return hour / 24, cost


def _sample(rng):
    return {"D": rng.choice([90, 180, 365, 730]), "w": rng.choice([2, 4, 6, 10]), "C": rng.choice([20, 40, 60]),
            "A_share": rng.choice([0.5, 0.7, 0.85]), "K": rng.choice([10, 20, 40]), "r": rng.choice([40, 80, 120]),
            "startup": rng.choice([5000, 20000]), "merge": rng.choice([30000, 60000, 120000]),
            "beta": rng.choice([2000, 5000, 10000, 20000]),
            "T": rng.choice([3, 5, 7, 10, 14])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        p["A"] = int(round(p["C"] * p["A_share"]))
        res = {k: _plan(p, k) for k in ORDER}
        if any(abs(d - p["T"]) < 0.03 * p["T"] for d, _c in res.values()):
            return None
        ok = {k: c for k, (d, c) in res.items() if d <= p["T"]}
        if not ok or len(ok) == 4:
            return None
        srt = sorted(ok.values())
        good = min(ok, key=ok.get)
        if len(srt) > 1 and srt[1] - srt[0] < 0.05 * max(srt[1], 1):
            return None
        if good != target:
            return None
        cheap = min(ORDER, key=lambda k: res[k][1])
        fastest = min(ORDER, key=lambda k: res[k][0])
        ok_night = {k: c for k, (d, c) in ((k, _plan(p, k, night_ok=True)) for k in ORDER) if d <= p["T"]}
        ok_an = {k: c for k, (d, c) in ((k, _plan(p, k, analysts=False)) for k in ORDER) if d <= p["T"]}
        if not ok_night or not ok_an:
            return None
        no_night = min(ok_night, key=ok_night.get)
        no_an = min(ok_an, key=ok_an.get)
        traps = {"cheap": cheap, "fastest": fastest, "no_sla_window": no_night, "no_analyst_cost": no_an}
        if sum(1 for v in traps.values() if v != good) < (1 if good == "off" else 2):
            return None
        return good, res, traps

    p, (good, res, traps) = search(rng, _sample, accept)
    days = lambda n: f"{n} {plural(n, 'день', 'дня', 'дней')}"
    stem = (f"{cap(ctx)}: нужно пересчитать {days(p['D'])} истории, каждый день-раздел — {p['w']} "
            f"{plural(p['w'], 'узло-час', 'узло-часа', 'узло-часов')}. Срок — {days(p['T'])}. Общий кластер — {p['C']} "
            f"{plural(p['C'], 'узел', 'узла', 'узлов')}: 00:00–06:00 — окно ночных SLA-загрузок, пересчёт в нём "
            f"запрещён; 09:00–19:00 аналитики занимают {p['A']} {plural(p['A'], 'узел', 'узла', 'узлов')}, пересчёт на "
            f"остальных замедляет их запросы — ≈ {fmt_num(p['beta'], 0)} ₽ за каждый такой час; 06:00–09:00 и "
            f"19:00–24:00 кластер свободен (уже оплачен). Временный кластер: {p['K']} "
            f"{plural(p['K'], 'узел', 'узла', 'узлов')} круглосуточно по {p['r']} ₽ за узло-час плюс "
            f"{fmt_num(p['startup'], 0)} ₽ за подъём; если пересчёт идёт на двух кластерах сразу, результаты надо "
            f"сводить и сверять — ещё {fmt_num(p['merge'], 0)} ₽ разово. Планы:\n" + ";\n".join(f"• {cap(NAMES[k])}" for k in ORDER) +
            ".\n\nКакой план успевает к сроку и дешевле остальных таких?")
    expl = (f"Работа — {fmt_num(p['D'] * p['w'], 0)} узло-часов. Узло-часов в сутки и итог по планам: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(_per_day(p, k), 0)} в сутки, {fmt_num(res[k][0], 1)} дн., "
                      f"{fmt_num(res[k][1], 0)} ₽" for k in ORDER) +
            f". К сроку {ru_num(p['T'])} дн. успевают: {', '.join(NAMES[k] for k in ORDER if res[k][0] <= p['T'])}; "
            f"дешевле — {NAMES[good]}. Ловушки: самый дешёвый — {NAMES[traps['cheap']]}; самый быстрый — "
            f"{NAMES[traps['fastest']]}; без запрета ночного окна — {NAMES[traps['no_sla_window']]}; без цены "
            f"замедления аналитиков — {NAMES[traps['no_analyst_cost']]}.")
    P = {k: v for k, v in p.items() if k != "A_share"}
    program = PROGRAM.format(P=P, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={**P, "good": good, **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: почасовое распределение узлов под пересчёт по правилам "
                            "плана.")
