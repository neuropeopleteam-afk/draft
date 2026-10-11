"""data_eng.orchestration.principal_dag_sla_mcq — mcq_concept (Principal): самое дешёвое вложение под SLA витрины.

Ночная цепочка: выгрузка источника приходит в плановое время с задержкой по распределению (вовремя / +d1 / +d2
минут с вероятностями), затем загрузка (ℓ), два преобразования A и B — сейчас по очереди в одном слоте — и сборка
витрины (m). Витрина должна быть готова к сроку; доля дней «вовремя» сейчас ниже цели. Четыре меры, у каждой цена:
запустить A и B параллельно (второй слот), ускорить A на x минут (переписать преобразование), кластер мощнее (все
шаги × k), договориться с владельцем источника о выгрузке на s минут раньше. Какая мера одна выводит на цель и
дешевле остальных таких?

Ловушки: самая дешёвая мера; «наибольший прирост» доли дней вовремя; расчёт по средней задержке вместо
распределения (самая дешёвая мера, «укладывающаяся в срок при средней задержке»); ответ отличается хотя бы от
двух. Сроки готовности в каждом сценарии отстоят от срока не меньше чем на 5 минут. Ответ выбирается по seed до подбора чисел — равновероятен среди четырёх мер.
Ключ проверяется исполнением: программа проводит каждый сценарий задержки через граф зависимостей (начало шага —
после конца всех его предшественников) для каждой меры, суммирует вероятности дней «вовремя» и печатает букву самой
дешёвой из достигших цели.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.orchestration.principal_dag_sla_mcq"

CONTEXTS = [("витрина продаж к утренней планёрке", "выгрузка кассовой системы"),
            ("витрина рисков к открытию торгов", "выгрузка процессинга"),
            ("витрина откликов к началу рабочего дня рекрутеров", "выгрузка из системы откликов"),
            ("витрина остатков к первой волне отгрузки", "выгрузка складской системы"),
            ("витрина начислений к утренней рассылке", "выгрузка биллинга"),
            ("витрина KPI к отчёту руководству", "выгрузка CRM")]
NAMES = {"parallel": "запустить A и B параллельно (второй слот)", "speed_a": "ускорить преобразование A",
         "cluster": "кластер мощнее (все шаги быстрее)", "earlier": "выгрузка источника раньше по договорённости"}
ORDER = ["parallel", "speed_a", "cluster", "earlier"]

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}
target = {target}

def on_time(measure):
    k = P["k"] if measure == "cluster" else 1.0
    dur = {{"load": P["l"] * k, "A": (P["a"] - (P["x"] if measure == "speed_a" else 0)) * k, "B": P["b"] * k,
            "mart": P["m"] * k}}
    deps = {{"load": ["arrive"], "A": ["load"], "B": ["load"] if measure == "parallel" else ["A"],
             "mart": ["A", "B"]}}
    total = 0.0
    for delay, prob in P["delays"]:
        finish = {{"arrive": P["arrive"] + delay - (P["s"] if measure == "earlier" else 0)}}
        for job in ("load", "A", "B", "mart"):          # топологический порядок
            finish[job] = max(finish[d] for d in deps[job]) + dur[job]
        if finish["mart"] <= P["deadline"] + 1e-9:
            total += prob
    return total

ok = [m for m in cost if on_time(m) >= target - 1e-9]
best = min(ok, key=lambda m: cost[m])
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _finish(p, m, delay):
    k = p["k"] if m == "cluster" else 1.0
    a = (p["a"] - (p["x"] if m == "speed_a" else 0)) * k
    b, ld, mart = p["b"] * k, p["l"] * k, p["m"] * k
    t0 = p["arrive"] + delay - (p["s"] if m == "earlier" else 0) + ld
    return t0 + (max(a, b) if m == "parallel" else a + b) + mart


def _on_time(p, m, delays=None):
    delays = p["delays"] if delays is None else delays
    return sum(pr for d, pr in delays if _finish(p, m, d) <= p["deadline"] + 1e-9)


def _hm(minutes: float) -> str:
    m = int(round(minutes)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _sample(rng):
    d1, d2 = rng.choice([(20, 60), (30, 90), (40, 120), (15, 45)])
    probs = rng.choice([(0.7, 0.2, 0.1), (0.8, 0.15, 0.05), (0.6, 0.3, 0.1), (0.75, 0.2, 0.05)])
    arrive = rng.choice([180, 210, 240, 270])
    return {"arrive": arrive, "delays": [(0, probs[0]), (d1, probs[1]), (d2, probs[2])],
            "l": rng.choice([20, 30, 40]), "a": rng.choice([40, 60, 80, 100]), "b": rng.choice([30, 50, 70, 90]),
            "m": rng.choice([15, 20, 30]), "x": rng.choice([20, 30, 40, 60]), "k": rng.choice([0.6, 0.7, 0.8]),
            "s": rng.choice([20, 30, 45, 60]), "slack": rng.choice([0, 10, 20, 30, 45, 60]),
            "cost": {"parallel": rng.choice([0.4, 0.8, 1.2]), "speed_a": rng.choice([0.2, 0.6, 1.0, 1.5]),
                     "cluster": rng.choice([2.0, 3.0, 4.5]), "earlier": rng.choice([0.3, 0.5, 2.5])},
            "target": rng.choice([0.9, 0.95, 0.99])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, src = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        base = p["arrive"] + p["l"] + p["a"] + p["b"] + p["m"]
        p["deadline"] = base + p["slack"]
        if len(set(p["cost"].values())) < 4 or p["a"] - p["x"] < 10 or _on_time(p, None) >= p["target"]:
            return None
        fin = {m: [_finish(p, m, d) for d, _pr in p["delays"]] for m in ORDER}
        if any(abs(f - p["deadline"]) < 5 for fs in fin.values() for f in fs):
            return None                                    # не на грани срока: ±5 минут
        ot = {m: _on_time(p, m) for m in ORDER}
        ok = [m for m in ORDER if ot[m] >= p["target"] - 1e-9]
        if not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda m: p["cost"][m])
        if good != target:
            return None
        cheap = min(ORDER, key=lambda m: p["cost"][m])
        top = max(ot.values())
        if sum(1 for v in ot.values() if v == top) > 1:
            return None
        biggest = max(ot, key=ot.get)
        mean_d = sum(d * pr for d, pr in p["delays"])
        ok_mean = [m for m in ORDER if _finish(p, m, mean_d) <= p["deadline"]]
        if not ok_mean:
            return None
        mean_t = min(ok_mean, key=lambda m: p["cost"][m])
        traps = {"cheap": cheap, "biggest": biggest, "mean_delay": mean_t}
        if sum(1 for v in traps.values() if v != good) < 2:
            return None
        return good, ot, traps

    p, (good, ot, traps) = search(rng, _sample, accept)
    pc = lambda x: fmt_num(100 * x, 0) + " %"
    mins = lambda n: f"{n} {plural(n, 'минуту', 'минуты', 'минут')}"
    (d0, p0), (d1, p1), (d2, p2) = p["delays"]
    c = p["cost"]
    rows = [f"• {cap(NAMES['parallel'])} — {fmt_num(c['parallel'], 1)} млн ₽ в год;",
            f"• {cap(NAMES['speed_a'])} на {mins(p['x'])} — {fmt_num(c['speed_a'], 1)} млн ₽ в год (разработка и поддержка в пересчёте на год);",
            f"• {cap(NAMES['cluster'])}: длительность каждого шага × {fmt_num(p['k'], 1)} — {fmt_num(c['cluster'], 1)} "
            f"млн ₽ в год;",
            f"• {cap(NAMES['earlier'])}: на {mins(p['s'])} раньше — {fmt_num(c['earlier'], 1)} млн ₽ в год "
            f"(доплата владельцу источника)."]
    stem = (f"{cap(ctx)} должна быть готова к {_hm(p['deadline'])} не реже чем в {pc(p['target'])} дней. Цепочка: "
            f"{src} приходит в {_hm(p['arrive'])} — вовремя в {pc(p0)} дней, на {mins(d1)} позже в {pc(p1)}, на "
            f"{mins(d2)} позже в {pc(p2)}; затем загрузка ({mins(p['l'])}), преобразования A ({mins(p['a'])}) и B "
            f"({mins(p['b'])}) — сейчас по очереди в одном слоте, B после A, — и сборка витрины ({mins(p['m'])}) "
            f"после обоих. Бюджет — на одну меру:\n" + "\n".join(rows) +
            "\n\nКакая мера одна выводит цепочку на цель и дешевле остальных таких?")
    expl = (f"Доля дней «вовремя» сейчас {pc(_on_time(p, None))}. С мерой: " +
            "; ".join(f"{NAMES[m]} — {pc(ot[m])}" for m in ORDER) +
            f". Цели {pc(p['target'])} достигают: {', '.join(NAMES[m] for m in ORDER if ot[m] >= p['target'] - 1e-9)}; "
            f"самая дешёвая — {NAMES[good]}. Считать надо по каждому сценарию задержки (вовремя, +{d1}, +{d2} мин), а "
            f"не по средней. Ловушки: самая дешёвая мера — {NAMES[traps['cheap']]}; наибольший прирост — "
            f"{NAMES[traps['biggest']]}; по средней задержке — {NAMES[traps['mean_delay']]}.")
    P = {k: v for k, v in p.items() if k not in ("cost", "target")}
    program = PROGRAM.format(P=P, cost=c, names=NAMES, target=p["target"])
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[m] for m in ORDER if m != good], program=program, explanation=expl,
                       params={**{k: v for k, v in P.items() if k != "delays"},
                               "delays": [list(x) for x in p["delays"]], "target": p["target"],
                               **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: каждый сценарий задержки проходит через граф зависимостей.")
