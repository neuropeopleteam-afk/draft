"""data_ml.llm.principal_rag_fix_mcq — mcq_concept (Principal): что чинить в RAG — поиск, контекст или модель.

Доля верных ответов RAG-помощника раскладывается: Q = R × A, где R — доля вопросов, для которых нужный фрагмент
попал в контекст (полнота поиска при k фрагментах), A — точность модели-читателя, когда фрагмент в контексте.
Сейчас k = 5. Измерено на размеченном наборе: R при k = 5, 20 и 50. Четыре меры с ценой в месяц и добавкой к p95
задержки: переранжирование (берём 50, переранжировщик оставляет 5 и сохраняет нужный фрагмент с долей e);
давать читателю 20 фрагментов (R = R20, но точность читателя падает в d раз от «размытого» контекста); гибридный
поиск (лексический + векторный, R растёт на h); модель-читатель сильнее (A = A_big). Нужна доля верных ответов не
ниже цели при p95 не выше бюджета. Какая мера одна выполняет оба требования и дешевле остальных таких?

Ловушки: самая дешёвая мера; наибольшая доля верных ответов; «больше контекста — не хуже» (20 фрагментов без
падения точности читателя); без бюджета задержки. Ответ выбирается по seed до подбора чисел — равновероятен среди
четырёх; отличается хотя бы от двух ловушек; доли и задержки отстоят от порогов не меньше чем на 1 п. п. и 5 %.
Ключ проверяется исполнением: программа пересчитывает R, A и p95 для каждой меры.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.llm.principal_rag_fix_mcq"

CONTEXTS = ["помощник поддержки по базе знаний", "помощник юристов по договорам", "помощник рекрутера по вакансиям",
            "помощник инженеров по регламентам эксплуатации", "помощник операторов по тарифам",
            "помощник аналитиков по описаниям витрин"]
NAMES = {"rerank": "переранжирование 50 → 5", "top20": "давать читателю 20 фрагментов",
         "hybrid": "гибридный поиск (лексический + векторный)", "bigger": "модель-читатель сильнее"}
ORDER = ["rerank", "top20", "hybrid", "bigger"]

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}

def measure(m):                      # (доля верных ответов, p95 задержки, мс)
    recall, acc, lat = P["R5"], P["A"], P["lat"]
    if m == "rerank":
        recall, lat = P["R50"] * P["e"], lat + P["lat_rerank"]
    elif m == "top20":
        recall, acc, lat = P["R20"], P["A"] / P["d"], lat + P["lat_top20"]
    elif m == "hybrid":
        recall, lat = min(1.0, P["R5"] + P["h"]), lat + P["lat_hybrid"]
    elif m == "bigger":
        acc, lat = P["A_big"], lat + P["lat_bigger"]
    return recall * acc, lat

ok = [m for m in cost if measure(m)[0] >= P["target"] - 1e-9 and measure(m)[1] <= P["lat_max"] + 1e-9]
best = min(ok, key=lambda m: cost[m])
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _meas(p, m, *, no_dilution=False):
    r, a, lat = p["R5"], p["A"], p["lat"]
    if m == "rerank":
        r, lat = p["R50"] * p["e"], lat + p["lat_rerank"]
    elif m == "top20":
        r, a, lat = p["R20"], (p["A"] if no_dilution else p["A"] / p["d"]), lat + p["lat_top20"]
    elif m == "hybrid":
        r, lat = min(1.0, p["R5"] + p["h"]), lat + p["lat_hybrid"]
    elif m == "bigger":
        a, lat = p["A_big"], lat + p["lat_bigger"]
    return r * a, lat


def _sample(rng):
    r5 = rng.choice([0.6, 0.65, 0.7, 0.75])
    r20 = round(r5 + rng.choice([0.1, 0.15, 0.2]), 2)
    r50 = round(min(0.98, r20 + rng.choice([0.05, 0.08])), 2)
    a = rng.choice([0.8, 0.85, 0.9])
    return {"R5": r5, "R20": r20, "R50": r50, "A": a, "A_big": round(min(0.98, a + rng.choice([0.04, 0.07, 0.1])), 2),
            "e": rng.choice([0.9, 0.95]), "d": rng.choice([1.05, 1.1, 1.2]), "h": rng.choice([0.05, 0.08, 0.12]),
            "lat": rng.choice([1200, 1800, 2500]), "lat_rerank": rng.choice([150, 300, 600]),
            "lat_top20": rng.choice([400, 800, 1200]), "lat_hybrid": rng.choice([50, 100]),
            "lat_bigger": rng.choice([700, 1200, 2000]), "lat_room": rng.choice([300, 700, 1000, 1500]),
            "drop": rng.choice([0.03, 0.06, 0.09, 0.12]),
            "cost": {"rerank": rng.choice([60, 120, 200]), "top20": rng.choice([80, 150, 300]),
                     "hybrid": rng.choice([40, 90, 250]), "bigger": rng.choice([180, 400, 700])}}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        if len(set(p["cost"].values())) < 4:
            return None
        p["lat_max"] = p["lat"] + p["lat_room"]
        p["target"] = round(p["R5"] * p["A"] + p["drop"], 3)
        res = {m: _meas(p, m) for m in ORDER}
        for q, lat in res.values():
            if abs(q - p["target"]) < 0.01 or abs(lat - p["lat_max"]) < 0.05 * p["lat_max"]:
                return None
        ok = [m for m in ORDER if res[m][0] >= p["target"] and res[m][1] <= p["lat_max"]]
        if not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda m: p["cost"][m])
        if good != target:
            return None
        qs = sorted(q for q, _l in res.values())
        if qs[-1] - qs[-2] < 0.005:
            return None
        cheap = min(ORDER, key=lambda m: p["cost"][m])
        best_q = max(ORDER, key=lambda m: res[m][0])
        ok_nd = [m for m in ORDER if _meas(p, m, no_dilution=True)[0] >= p["target"]
                 and _meas(p, m, no_dilution=True)[1] <= p["lat_max"]]
        ok_nl = [m for m in ORDER if res[m][0] >= p["target"]]
        traps = {"cheap": cheap, "best_quality": best_q, "no_dilution": min(ok_nd, key=lambda m: p["cost"][m]),
                 "no_latency": min(ok_nl, key=lambda m: p["cost"][m])}
        if sum(1 for v in traps.values() if v != good) < 2:
            return None
        return good, res, traps

    p, (good, res, traps) = search(rng, _sample, accept)
    pc = lambda x: fmt_num(100 * x, 1) + " %"
    c = p["cost"]
    rows = [f"• {cap(NAMES['rerank'])}: переранжировщик сохраняет нужный фрагмент в {pc(p['e'])} случаев; +{p['lat_rerank']} "
            f"мс; {c['rerank']} тыс. ₽ в месяц;",
            f"• {cap(NAMES['top20'])}: точность читателя падает в {fmt_num(p['d'], 2)} раза от длинного контекста; "
            f"+{fmt_num(p['lat_top20'], 0)} мс; {c['top20']} тыс. ₽ в месяц (токены);",
            f"• {cap(NAMES['hybrid'])}: полнота при k = 5 растёт на {fmt_num(100 * p['h'], 0)} п. п.; +{p['lat_hybrid']} мс; "
            f"{c['hybrid']} тыс. ₽ в месяц;",
            f"• {cap(NAMES['bigger'])}: точность при фрагменте в контексте {pc(p['A_big'])}; +{fmt_num(p['lat_bigger'], 0)} мс; "
            f"{c['bigger']} тыс. ₽ в месяц."]
    stem = (f"{cap(ctx)} (RAG, сейчас k = 5 фрагментов) отвечает верно в {pc(p['R5'] * p['A'])} случаев, p95 — "
            f"{fmt_num(p['lat'], 0)} мс. Размеченный набор: нужный фрагмент попадает в выдачу при k = 5 — в {pc(p['R5'])}, при k = 20 "
            f"— в {pc(p['R20'])}, при k = 50 — в {pc(p['R50'])}; когда он в контексте, модель отвечает верно в "
            f"{pc(p['A'])}. Нужно: верных ответов не меньше {pc(p['target'])}, p95 не больше {fmt_num(p['lat_max'], 0)} мс. "
            f"Бюджет — на одну меру:\n" + "\n".join(rows) +
            "\n\nКакая мера одна выполняет оба требования и дешевле остальных таких?")
    expl = ("Доля верных = доля вопросов с нужным фрагментом в контексте × точность читателя. После меры: " +
            "; ".join(f"{NAMES[m]} — {pc(res[m][0])}, p95 {fmt_num(res[m][1], 0)} мс" for m in ORDER) +
            f". Оба требования выполняют: "
            f"{', '.join(NAMES[m] for m in ORDER if res[m][0] >= p['target'] and res[m][1] <= p['lat_max'])}; "
            f"дешевле — {NAMES[good]}. Ловушки: самая дешёвая — {NAMES[traps['cheap']]}; наибольшая доля верных — "
            f"{NAMES[traps['best_quality']]}; «больше контекста — не хуже» — {NAMES[traps['no_dilution']]}; без "
            f"бюджета задержки — {NAMES[traps['no_latency']]}.")
    P = {k: v for k, v in p.items() if k not in ("cost", "lat_room", "drop")}
    program = PROGRAM.format(P=P, cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[m] for m in ORDER if m != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: пересчёт полноты поиска, точности читателя и p95.")
