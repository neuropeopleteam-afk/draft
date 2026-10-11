"""data_ml.strategy.principal_data_vs_model_mcq — mcq_concept (Principal): данные, разметка или модель — что купить.

Ошибка модели разложена на три части (по диагностике: кривая обучения, повторная разметка выборки, модель больше
на той же выборке): пол из-за шума разметки F_n, пол ёмкости модели F_c и «устранимая данными» часть R. Удвоение
размеченных данных уменьшает R в k раз (по кривой обучения), учетверение — в k². Повторная разметка с перекрёстной
проверкой убирает долю ρ шума (пол F_n × (1 − ρ)). Модель больше: пол ёмкости × (1 − γ), но на тех же данных
устранимая часть растёт в μ раз (большая модель «голоднее»). Нужно довести ошибку до цели E*. Какая мера одна
доводит и дешевле остальных таких?

Ловушки: самая дешёвая мера; наибольшее снижение ошибки; «вся ошибка устранима данными» (без полов: удвоение —
E / k); «модель больше» без роста устранимой части. Ответ выбирается по seed до подбора чисел — равновероятен среди
четырёх мер; отличается хотя бы от двух ловушек; ошибки после каждой меры отстоят от цели не меньше чем на 0,1 процентного пункта.
Ключ проверяется исполнением: программа пересчитывает три части ошибки для каждой меры.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.strategy.principal_data_vs_model_mcq"

CONTEXTS = [("классификация обращений в поддержку", "обращений"), ("распознавание товаров на фото полки", "фото"),
            ("модерация объявлений", "объявлений"), ("извлечение реквизитов из счетов", "счетов"),
            ("категоризация банковских операций", "операций"), ("разбор резюме по навыкам", "резюме"),
            ("определение тональности отзывов", "отзывов")]
NAMES = {"data2": "удвоить размеченные данные", "data4": "учетверить размеченные данные",
         "relabel": "повторная разметка с перекрёстной проверкой", "bigger": "модель больше"}
ORDER = ["data2", "data4", "relabel", "bigger"]

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}

def error(measure):
    noise, capacity, reducible = P["Fn"], P["Fc"], P["R"]
    if measure == "data2":
        reducible /= P["k"]
    elif measure == "data4":
        reducible /= P["k"] ** 2
    elif measure == "relabel":
        noise *= 1 - P["rho"]
    elif measure == "bigger":
        capacity *= 1 - P["gamma"]
        reducible *= P["mu"]
    return noise + capacity + reducible

ok = [m for m in cost if error(m) <= P["target"] + 1e-9]
best = min(ok, key=lambda m: cost[m])
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _err(p, m, *, floors=True, mu=True):
    fn, fc, r = p["Fn"], p["Fc"], p["R"]
    if not floors:                       # ловушка: вся ошибка «устранима данными»
        r, fn, fc = fn + fc + r, 0.0, 0.0
    if m == "data2":
        r /= p["k"]
    elif m == "data4":
        r /= p["k"] ** 2
    elif m == "relabel":
        fn *= 1 - p["rho"]
    elif m == "bigger":
        fc *= 1 - p["gamma"]
        r *= p["mu"] if mu else 1.0
    return fn + fc + r


def _sample(rng):
    c2 = rng.choice([0.6, 1.0, 1.5, 2.0])
    return {"Fn": rng.choice([1.0, 1.5, 2.0, 3.0, 4.0]), "Fc": rng.choice([1.0, 2.0, 3.0, 4.0]),
            "R": rng.choice([1.5, 2.0, 3.0, 4.0, 6.0]), "k": rng.choice([1.3, 1.5, 2.0]),
            "rho": rng.choice([0.5, 0.7, 0.9]), "gamma": rng.choice([0.4, 0.6, 0.8]), "mu": rng.choice([1.2, 1.5]),
            "drop": rng.choice([0.8, 1.2, 1.6, 2.0, 2.5, 3.0]), "n": rng.choice([20, 50, 120, 300]),
            "cost": {"data2": c2, "data4": round(3 * c2, 1), "relabel": rng.choice([0.5, 0.9, 1.4, 2.5]),
                     "bigger": rng.choice([0.8, 1.6, 3.2])}}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, unit = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        if len(set(p["cost"].values())) < 4:
            return None
        cur = p["Fn"] + p["Fc"] + p["R"]
        p["target"] = round(cur - p["drop"], 2)
        if p["target"] <= 0.5:
            return None
        err = {m: _err(p, m) for m in ORDER}
        if any(abs(e - p["target"]) < 0.1 for e in err.values()):
            return None
        ok = [m for m in ORDER if err[m] <= p["target"]]
        if not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda m: p["cost"][m])
        if good != target:
            return None
        cheap = min(ORDER, key=lambda m: p["cost"][m])
        if sorted(err.values())[0] == sorted(err.values())[1]:
            return None
        biggest = min(ORDER, key=lambda m: err[m])
        ok_nf = [m for m in ORDER if _err(p, m, floors=False) <= p["target"]]
        ok_mu = [m for m in ORDER if _err(p, m, mu=False) <= p["target"]]
        if not ok_nf or not ok_mu:
            return None
        traps = {"cheap": cheap, "biggest": biggest, "no_floors": min(ok_nf, key=lambda m: p["cost"][m]),
                 "no_mu": min(ok_mu, key=lambda m: p["cost"][m])}
        if sum(1 for v in traps.values() if v != good) < 2:
            return None
        return good, err, traps

    p, (good, err, traps) = search(rng, _sample, accept)
    pp = lambda x: fmt_num(x, 1) + " %"
    cur = p["Fn"] + p["Fc"] + p["R"]
    c = p["cost"]
    rows = [f"• {cap(NAMES['data2'])} (ещё {p['n']} тыс. {unit}) — {fmt_num(c['data2'], 1)} млн ₽;",
            f"• {cap(NAMES['data4'])} (ещё {3 * p['n']} тыс.) — {fmt_num(c['data4'], 1)} млн ₽;",
            f"• {cap(NAMES['relabel'])} всей выборки: убирает {fmt_num(100 * p['rho'], 0)} % шума разметки — "
            f"{fmt_num(c['relabel'], 1)} млн ₽;",
            f"• {cap(NAMES['bigger'])}: пол ёмкости × {fmt_num(1 - p['gamma'], 1)}, но устранимая данными часть на тех "
            f"же данных × {fmt_num(p['mu'], 1)} — {fmt_num(c['bigger'], 1)} млн ₽ в год (GPU)."]
    stem = (f"Задача — {ctx}; модель обучена на {p['n']} тыс. размеченных {unit}, доля ошибок {pp(cur)}. Диагностика "
            f"разложила её на части: шум разметки — {pp(p['Fn'])}, пол ёмкости модели — {pp(p['Fc'])}, устранимая "
            f"данными часть — {pp(p['R'])}; по кривой обучения удвоение данных уменьшает устранимую часть в "
            f"{fmt_num(p['k'], 1)} раза. Цель — ошибка не выше {pp(p['target'])}. Бюджет — на одну меру:\n" +
            "\n".join(rows) + "\n\nКакая мера одна доводит ошибку до цели и дешевле остальных таких?")
    expl = ("Ошибка = шум разметки + пол ёмкости + устранимая данными часть; каждая мера двигает только свою часть. "
            "После меры: " + "; ".join(f"{NAMES[m]} — {pp(err[m])}" for m in ORDER) +
            f". Цель {pp(p['target'])} достигают: {', '.join(NAMES[m] for m in ORDER if err[m] <= p['target'])}; "
            f"дешевле — {NAMES[good]}. Ловушки: самая дешёвая мера — {NAMES[traps['cheap']]}; наибольшее снижение — "
            f"{NAMES[traps['biggest']]}; «вся ошибка устранима данными» — {NAMES[traps['no_floors']]}; модель больше "
            f"без роста устранимой части — {NAMES[traps['no_mu']]}.")
    P = {k: v for k, v in p.items() if k != "cost"}
    program = PROGRAM.format(P=P, cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[m] for m in ORDER if m != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: пересчёт трёх частей ошибки для каждой меры.")
