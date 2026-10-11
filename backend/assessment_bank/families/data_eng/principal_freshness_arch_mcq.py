"""data_eng.strategy.principal_freshness_arch_mcq — mcq_concept (Principal): поток или пакеты под требование свежести.

Витрина должна отражать события не позже чем через F минут; события приходят с опозданием до L часов и обязаны
попасть в витрину, поэтому каждый пакетный запуск пересчитывает последние L часов (окно досчёта), а поток держит
состояние на это окно. Четыре архитектуры: поток на постоянно включённом кластере, микропакеты каждые m минут,
почасовые пакеты, суточный пакет. У пакета — накладные запуска (подъём кластера, чтение метаданных) и цена
обработки гигабайта; у потока — фиксированная плата за месяц и цена гигабайта. Какая архитектура, укладывающаяся в
F, даёт минимальную цену за месяц?

Ловушки: «самая свежая» (поток), «самая дешёвая без требования свежести», расчёт без окна досчёта (микропакеты
кажутся дешёвыми), без накладных запуска. Ответ выбирается по seed до подбора чисел — равновероятен среди четырёх
архитектур; ответ отличается хотя бы от двух ловушек (если ответ — поток или суточный пакет — хотя бы от одной),
минимум отделён от второго места ≥ 4 %. Ключ проверяется исполнением: программа строит расписание запусков на
месяц и суммирует цену каждого запуска (накладные + объём интервала и окна досчёта), а задержку находит перебором
минуты прихода события за сутки (до завершения ближайшего следующего запуска).
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import argmin_sep, cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.strategy.principal_freshness_arch_mcq"

CONTEXTS = [("витрина остатков для склада", "движения товаров"), ("антифрод-витрина платежей", "платёжные события"),
            ("витрина откликов для рекрутеров", "отклики и просмотры"), ("витрина продаж для категорийных менеджеров",
                                                                        "чеки касс"),
            ("витрина телеметрии парка машин", "показания датчиков"), ("витрина заказов для колл-центра",
                                                                     "статусы заказов"),
            ("витрина рекламных показов для биллинга", "показы и клики")]
NAMES = {"stream": "поток на постоянно включённом кластере", "micro": "микропакеты",
         "hourly": "почасовые пакеты", "daily": "один суточный пакет"}
ORDER = ["stream", "micro", "hourly", "daily"]
MONTH_MIN = 30 * 24 * 60

PROGRAM = """opts = __OPTS__
P = {P!r}
names = {names!r}
F = {F}
MONTH = 30 * 24 * 60

def batch(interval, proc):
    runs = cost = 0
    for start in range(0, MONTH, interval):           # расписание запусков на месяц
        hours = interval / 60 + P["L"]                 # интервал + окно досчёта
        cost += P["startup"] + hours * P["v"] * P["rate_b"]
        runs += 1
    worst = 0
    for t in range(0, 24 * 60):                        # минута прихода события
        nxt = (t // interval + 1) * interval           # ближайший следующий запуск
        worst = max(worst, nxt + proc - t)
    return cost, worst

res = {{"stream": (P["base_s"] + MONTH / 60 * P["v"] * P["rate_s"], P["lag_s"]),
        "micro": batch(P["m"], P["proc_m"]), "hourly": batch(60, P["proc_h"]), "daily": batch(1440, P["proc_d"])}}
ok = {{k: c for k, (c, delay) in res.items() if delay <= F}}
best = min(ok, key=ok.get)
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _costs(p, *, lookback=True, startup=True):
    L = p["L"] if lookback else 0
    s = p["startup"] if startup else 0
    run = lambda interval: (MONTH_MIN // interval) * (s + (interval / 60 + L) * p["v"] * p["rate_b"])
    return {"stream": p["base_s"] + MONTH_MIN / 60 * p["v"] * p["rate_s"], "micro": run(p["m"]),
            "hourly": run(60), "daily": run(1440)}


def _delay(p):
    return {"stream": p["lag_s"], "micro": p["m"] + p["proc_m"], "hourly": 60 + p["proc_h"],
            "daily": 1440 + p["proc_d"]}


def _sample(rng):
    return {"v": rng.choice([5, 10, 20, 50, 100]), "rate_b": rng.choice([2, 4, 8]),
            "rate_s": rng.choice([3, 6, 12]), "base_s": rng.choice([60_000, 120_000, 250_000]),
            "startup": rng.choice([50, 150, 400, 1000]), "L": rng.choice([1, 2, 6, 12, 24]),
            "m": rng.choice([5, 10, 15]), "proc_m": rng.choice([3, 5]), "proc_h": rng.choice([10, 20]),
            "proc_d": rng.choice([60, 120]), "lag_s": rng.choice([1, 2]),
            "F": rng.choice([20, 30, 45, 90, 120, 240, 1800, 2880])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, events = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        d = _delay(p)
        if any(abs(d[k] - p["F"]) < 3 for k in ORDER):
            return None
        full = {k: c for k, c in _costs(p).items() if d[k] <= p["F"]}
        if len(full) < 2:
            return None
        good = argmin_sep(full)
        if good != target:
            return None
        freshest = "stream"
        no_f = argmin_sep(_costs(p), 0.01)
        no_lb = argmin_sep({k: c for k, c in _costs(p, lookback=False).items() if d[k] <= p["F"]}, 0.01)
        no_su = argmin_sep({k: c for k, c in _costs(p, startup=False).items() if d[k] <= p["F"]}, 0.01)
        if None in (no_f, no_lb, no_su):
            return None
        traps = {"freshest": freshest, "no_freshness": no_f, "no_lookback": no_lb, "no_startup": no_su}
        need = 1 if good in ("stream", "daily") else 2
        if sum(1 for v in traps.values() if v != good) < need:
            return None
        return good, full, d, traps

    p, (good, full, d, traps) = search(rng, _sample, accept)
    allc = _costs(p)
    mins = lambda n: f"{n} {plural(n, 'минуту', 'минуты', 'минут')}"
    hrs = lambda n: f"{n} {plural(n, 'час', 'часа', 'часов')}"
    rows = [f"• {cap(NAMES['stream'])}: {fmt_num(p['base_s'], 0)} ₽ в месяц за кластер плюс {p['rate_s']} ₽ за "
            f"обработанный гигабайт; задержка ≈ {mins(p['lag_s'])}; поздние события учитывает состояние окна.",
            f"• {cap(NAMES['micro'])} каждые {p['m']} минут: обработка запуска ≈ {mins(p['proc_m'])}.",
            f"• {cap(NAMES['hourly'])}: обработка запуска ≈ {mins(p['proc_h'])}.",
            f"• {cap(NAMES['daily'])}: обработка ≈ {mins(p['proc_d'])}."]
    stem = (f"{cap(ctx)}: источник — {events}, ≈ {p['v']} ГБ в час. Требование потребителей — событие видно в "
            f"витрине не позже чем через {mins(p['F'])}. События приходят с опозданием до {hrs(p['L'])} и обязаны "
            f"попасть в витрину, поэтому каждый пакетный запуск пересчитывает свой интервал плюс последние "
            f"{hrs(p['L'])}. Пакетный запуск стоит {fmt_num(p['startup'], 0)} ₽ накладных (подъём кластера, метаданные) "
            f"плюс {p['rate_b']} ₽ за каждый обработанный гигабайт. Варианты:\n" + "\n".join(rows) +
            "\n\nКакая архитектура укладывается в требование свежести и даёт минимальную цену за месяц (30 дней)?")
    expl = ("Задержка (худший случай: событие пришло сразу после запуска — ждёт следующий и его обработку) и цена за "
            "месяц: " + "; ".join(f"{NAMES[k]} — {ru_num(d[k])} мин, {fmt_num(allc[k], 0)} ₽" for k in ORDER) +
            f". В {ru_num(p['F'])} мин укладываются: {', '.join(NAMES[k] for k in ORDER if k in full)}; минимум — "
            f"{NAMES[good]}. Пакет пересчитывает интервал + {p['L']} ч окна, поэтому частые пакеты при длинном окне "
            f"досчёта дороги. Ловушки: самая свежая — {NAMES[traps['freshest']]}; без требования свежести — "
            f"{NAMES[traps['no_freshness']]}; без окна досчёта — {NAMES[traps['no_lookback']]}; без накладных запуска — "
            f"{NAMES[traps['no_startup']]}.")
    P = {k: v for k, v in p.items() if k != "F"}
    program = PROGRAM.format(P=P, names=NAMES, F=p["F"])
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={**p, "good": good, **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: расписание запусков на месяц и перебор минуты прихода "
                            "события.")
