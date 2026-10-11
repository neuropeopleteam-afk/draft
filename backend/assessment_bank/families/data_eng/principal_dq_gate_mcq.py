"""data_eng.quality.principal_dq_gate_mcq — mcq_concept (Principal): политика проверок качества данных перед публикацией.

Ежедневная загрузка витрины. С вероятностью p_c в загрузке критический дефект (дубли или потеря целого источника),
с вероятностью p_n — некритический (пропуски в части полей). Проверка критических дефектов ловит их с полнотой r_c
и ложно срабатывает на чистых данных с вероятностью f_c; проверка некритических — r_n и f_n. Цены: остановка
публикации — B (потребители без свежих данных, дежурный разбирается), карантин раздела — Q (публикуется остальное),
оповещение — A (разбор после публикации, дефект успевает нанести долю κ ущерба), дефект у потребителей — X_c или X_n.
Критический дефект обычно затрагивает все разделы: карантин локализует его лишь с вероятностью loc.
Четыре политики: блокировать по любой проверке; блокировать только по критической (некритическая — оповещение);
карантин по любой; только оповещения. Какая политика даёт минимальную ожидаемую цену за месяц?

Ловушки: «самая строгая» (блокировать всё), «самая мягкая» (только оповещения), расчёт без ложных срабатываний,
«оповещение устраняет ущерб полностью» (κ = 0). Ответ выбирается по seed до подбора чисел — равновероятен среди
четырёх политик; отличается хотя бы от двух ловушек (у крайних политик — хотя бы от одной), минимум отделён от
второго места ≥ 4 %. Ключ проверяется исполнением: программа перебирает 12 сценариев дня (состояние данных ×
сработала ли каждая проверка) с вероятностями и применяет правила политики.
"""
from __future__ import annotations

import itertools

from assessment_bank.families._principal_b_kit import argmin_sep, cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.quality.principal_dq_gate_mcq"

CONTEXTS = [("витрина выручки для финансовой отчётности", "дубли платежей", "пропуски в полях адреса"),
            ("витрина признаков для модели скоринга", "сдвиг дат на сутки во всём источнике", "пропуски в доходе"),
            ("витрина остатков для закупок", "потеря выгрузки одного склада", "пустые категории товаров"),
            ("витрина откликов для отчёта работодателям", "дубли откликов", "пропуски в городе кандидата"),
            ("витрина начислений абонентам", "двойной учёт сессий", "пустой тарифный план у части записей"),
            ("витрина рекламных показов для биллинга", "повтор пачки событий", "пропуски в площадке показа")]
NAMES = {"block_all": "блокировать публикацию по любой проверке",
         "block_crit": "блокировать только по критической проверке, по некритической — оповещение",
         "quarantine": "карантин раздела по любой проверке, остальное публиковать",
         "alert": "только оповещения, публиковать всегда"}
ORDER = ["block_all", "block_crit", "quarantine", "alert"]
POLICY = {"block_all": ("block", "block"), "block_crit": ("block", "alert"),
          "quarantine": ("quarantine", "quarantine"), "alert": ("alert", "alert")}

PROGRAM = """import itertools
opts = __OPTS__
P = {P!r}
names = {names!r}
policy = {policy!r}          # политика -> (действие критической проверки, действие некритической)
X = {{"crit": P["X_c"], "non": P["X_n"]}}

def day_cost(actions):
    total = 0.0
    for state, fc, fn in itertools.product(("crit", "non", "clean"), (True, False), (True, False)):
        ps = {{"crit": P["p_c"], "non": P["p_n"], "clean": 1 - P["p_c"] - P["p_n"]}}[state]
        pc = P["r_c"] if state == "crit" else P["f_c"]       # сработала критическая проверка
        pn = P["r_n"] if state == "non" else P["f_n"]        # сработала некритическая проверка
        pr = ps * (pc if fc else 1 - pc) * (pn if fn else 1 - pn)
        fired = [(a, kind) for a, kind, f in ((actions[0], "crit", fc), (actions[1], "non", fn)) if f]
        if any(a == "block" for a, _k in fired):
            cost = P["B"]
        else:
            cost = (P["Q"] if any(a == "quarantine" for a, _k in fired) else 0.0)
            cost += P["A"] * sum(1 for a, _k in fired if a == "alert")
            if state != "clean":
                own = [a for a, kind in fired if kind == state]
                if not own:
                    cost += X[state]
                elif own[0] == "alert":
                    cost += P["kappa"] * X[state]
                elif own[0] == "quarantine" and state == "crit":
                    cost += (1 - P["loc"]) * X[state]
        total += pr * cost
    return total

month = {{k: 30 * day_cost(a) for k, a in policy.items()}}
best = min(month, key=month.get)
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _day(p, actions):
    total = 0.0
    X = {"crit": p["X_c"], "non": p["X_n"]}
    for state, fc, fn in itertools.product(("crit", "non", "clean"), (True, False), (True, False)):
        ps = {"crit": p["p_c"], "non": p["p_n"], "clean": 1 - p["p_c"] - p["p_n"]}[state]
        pc = p["r_c"] if state == "crit" else p["f_c"]
        pn = p["r_n"] if state == "non" else p["f_n"]
        pr = ps * (pc if fc else 1 - pc) * (pn if fn else 1 - pn)
        fired = [(a, k) for a, k, f in ((actions[0], "crit", fc), (actions[1], "non", fn)) if f]
        if any(a == "block" for a, _k in fired):
            cost = p["B"]
        else:
            cost = (p["Q"] if any(a == "quarantine" for a, _k in fired) else 0.0)
            cost += p["A"] * sum(1 for a, _k in fired if a == "alert")
            if state != "clean":
                own = [a for a, k in fired if k == state]
                if not own:
                    cost += X[state]
                elif own[0] == "alert":
                    cost += p["kappa"] * X[state]
                elif own[0] == "quarantine" and state == "crit":
                    cost += (1 - p["loc"]) * X[state]
        total += pr * cost
    return total


def _month(p, **over):
    q = {**p, **over}
    return {k: 30 * _day(q, POLICY[k]) for k in ORDER}


def _sample(rng):
    return {"p_c": rng.choice([0.003, 0.005, 0.01, 0.02]), "p_n": rng.choice([0.03, 0.05, 0.1, 0.15]),
            "r_c": rng.choice([0.9, 0.95, 0.99]), "r_n": rng.choice([0.7, 0.8, 0.9]),
            "f_c": rng.choice([0.005, 0.01, 0.02, 0.05]), "f_n": rng.choice([0.02, 0.05, 0.1, 0.2]),
            "X_c": rng.choice([800, 2000, 5000, 10000]), "X_n": rng.choice([20, 50, 100, 200]),
            "B": rng.choice([60, 120, 250, 500]), "Q": rng.choice([15, 30, 60]), "A": rng.choice([3, 5, 10]),
            "kappa": rng.choice([0.2, 0.3, 0.5]), "loc": rng.choice([0.2, 0.4, 0.6, 0.8])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, crit, non = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        full = _month(p)
        good = argmin_sep(full)
        if good != target:
            return None
        no_fa = argmin_sep(_month(p, f_c=0.0, f_n=0.0), 0.01)
        no_k = argmin_sep(_month(p, kappa=0.0), 0.01)
        if None in (no_fa, no_k):
            return None
        traps = {"strict": "block_all", "lax": "alert", "no_false_alarms": no_fa, "alert_fixes_all": no_k}
        need = 1 if good in ("block_all", "alert") else 2
        if sum(1 for v in traps.values() if v != good) < need:
            return None
        return good, full, traps

    p, (good, full, traps) = search(rng, _sample, accept)
    pc = lambda x: fmt_num(100 * x, 1 if abs(100 * x - round(100 * x)) > 1e-9 else 0) + " %"
    th = lambda x: f"{fmt_num(x, 0)} тыс. ₽"
    stem = (f"{cap(ctx)} загружается раз в сутки. По истории: критический дефект ({crit}) — в {pc(p['p_c'])} "
            f"загрузок, некритический ({non}) — в {pc(p['p_n'])}. Критическая проверка ловит свой дефект в "
            f"{pc(p['r_c'])} случаев и ложно срабатывает на чистых данных в {pc(p['f_c'])} дней; некритическая — "
            f"{pc(p['r_n'])} и {pc(p['f_n'])}. Цены: остановка публикации — {th(p['B'])} (потребители без свежих "
            f"данных, дежурный разбирается); карантин раздела с публикацией остального — {th(p['Q'])}, но критический "
            f"дефект обычно задевает все разделы и карантин локализует его лишь в {pc(p['loc'])} случаев; оповещение — "
            f"{th(p['A'])} на разбор, а дефект до исправления успевает нанести {pc(p['kappa'])} своего ущерба. "
            f"Дефект, дошедший до потребителей: критический — {th(p['X_c'])}, некритический — {th(p['X_n'])}. "
            f"Варианты политики:\n" + ";\n".join(f"• {cap(NAMES[k])}" for k in ORDER) + "." +
            "\n\nКакая политика даёт минимальную ожидаемую цену за месяц (30 загрузок)?")
    expl = ("Ожидаемая цена за месяц по сценариям дня (состояние данных × сработала ли каждая проверка): " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 0)} тыс. ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Ложные срабатывания стоят остановки у блокирующих политик и карантина у "
            f"карантинной; оповещение оставляет долю ущерба. Ловушки: самая строгая — {NAMES[traps['strict']]}; самая "
            f"мягкая — {NAMES[traps['lax']]}; без ложных срабатываний — {NAMES[traps['no_false_alarms']]}; «оповещение "
            f"устраняет ущерб полностью» — {NAMES[traps['alert_fixes_all']]}.")
    program = PROGRAM.format(P=p, names=NAMES, policy=POLICY)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={**p, "good": good, **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: перебор 12 сценариев дня с вероятностями.")
