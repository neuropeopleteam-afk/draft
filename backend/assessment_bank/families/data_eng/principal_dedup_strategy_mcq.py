"""data_eng.streaming.principal_dedup_strategy_mcq — mcq_concept (Principal): как бороться с дублями потока.

Поток доставляет события «хотя бы один раз»; без мер в приёмник попадает ≈ N дублей в сутки, из них доля f —
повторы после долгих сбоев (повторная отправка старше окна дедупликации). Каждый дубль в приёмнике стоит c ₽
(ручной разбор, возврат). Четыре варианта с ценой в сутки: оставить как есть; идемпотентная запись в приёмник
(upsert по ключу события); хранилище дедупликации с окном W минут (ловит только повторы внутри окна); транзакции
потоковой платформы (exactly-once внутри платформы: если приёмник — топик той же платформы, дублей нет; если
приёмник — внешняя БД, граница транзакции до неё не доходит и дубли остаются). Какой вариант даёт минимум полной
цены суток (мера + дубли)?

Ловушки: «exactly-once закрывает всё» (транзакции убирают дубли и во внешней БД), «окно ловит все повторы»,
самая дешёвая мера, «ноль дублей любой ценой». Ответ выбирается по seed до подбора чисел — равновероятен среди
четырёх; отличается хотя бы от одной ловушки (обычно от двух); минимум отделён от второго места ≥ 5 %. Ключ
проверяется исполнением: программа считает для каждого варианта дубли, дошедшие до приёмника, и полную цену суток.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import argmin_sep, cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.streaming.principal_dedup_strategy_mcq"

CONTEXTS = [("события оплат", "начисление бонусов"), ("заказы из мобильного приложения", "резерв товара"),
            ("отклики на вакансии", "уведомление работодателю"), ("показания счётчиков", "выставление счёта"),
            ("события доставки", "смена статуса заказа"), ("переводы между счетами", "проводка в учётной системе")]
NAMES = {"none": "оставить как есть", "idem": "идемпотентная запись в приёмник (upsert по ключу события)",
         "window": "хранилище дедупликации с окном", "tx": "транзакции потоковой платформы (exactly-once)"}
ORDER = ["none", "idem", "window", "tx"]
SINKS = {"topic": "топик той же платформы (дальше его читает другой потребитель)", "db": "внешняя БД"}

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}

def dups_in_sink(way):
    if way == "idem":
        return 0.0
    if way == "window":
        return P["N"] * P["f_long"]              # повторы старше окна проходят
    if way == "tx":
        return 0.0 if P["sink"] == "topic" else P["N"]   # граница транзакции не доходит до внешней БД
    return P["N"]

total = {{w: cost[w] + dups_in_sink(w) * P["c_dup"] for w in cost}}
best = min(total, key=total.get)
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _total(p, *, eos_all=False, window_all=False):
    d = {"none": p["N"], "idem": 0.0, "window": 0.0 if window_all else p["N"] * p["f_long"],
         "tx": 0.0 if (p["sink"] == "topic" or eos_all) else p["N"]}
    return {w: p["cost"][w] + d[w] * p["c_dup"] for w in ORDER}, d


def _sample(rng):
    return {"N": rng.choice([20, 50, 120, 300, 800]), "f_long": rng.choice([0.05, 0.15, 0.3, 0.5]),
            "c_dup": rng.choice([30, 80, 200, 500]), "W": rng.choice([10, 30, 60]), "sink": rng.choice(["topic", "db"]),
            "cost": {"none": 0, "idem": rng.choice([3000, 8000, 20000, 45000]),
                     "window": rng.choice([1500, 4000, 10000, 25000]), "tx": rng.choice([2500, 6000, 15000, 35000])}}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, effect = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        if len(set(p["cost"].values())) < 4:
            return None
        tot, _d = _total(p)
        good = argmin_sep({w: max(v, 1.0) for w, v in tot.items()}, 0.05)
        if good != target:
            return None
        eos = argmin_sep(_total(p, eos_all=True)[0], 0.01)
        win = argmin_sep(_total(p, window_all=True)[0], 0.01)
        if None in (eos, win):
            return None
        traps = {"eos_all": eos, "window_all": win, "cheap": "none",
                 "zero_dups": min(("idem", "tx") if p["sink"] == "topic" else ("idem",), key=lambda w: p["cost"][w])}
        need = 1 if good in ("none", "idem") else 2
        if sum(1 for v in traps.values() if v != good) < need:
            return None
        return good, tot, traps

    p, (good, tot, traps) = search(rng, _sample, accept)
    c = p["cost"]
    rub = lambda x: f"{fmt_num(x, 0)} ₽"
    rows = [f"• {cap(NAMES['none'])} — 0 ₽;",
            f"• {cap(NAMES['idem'])} — {rub(c['idem'])} в сутки (индекс и более медленная запись);",
            f"• {cap(NAMES['window'])} {p['W']} мин — {rub(c['window'])} в сутки;",
            f"• {cap(NAMES['tx'])} — {rub(c['tx'])} в сутки (меньше пропускная способность — больше узлов)."]
    stem = (f"Поток «{ctx}» доставляет события «хотя бы один раз»; дальше по ним — {effect}. Без мер в приёмник "
            f"попадает ≈ {p['N']} дублей в сутки, из них {fmt_num(100 * p['f_long'], 0)} % — повторы после долгих сбоев "
            f"(старше {p['W']} мин). Каждый дубль в приёмнике стоит ≈ {rub(p['c_dup'])} (разбор и исправление). "
            f"Приёмник — {SINKS[p['sink']]}. Варианты (цена меры):\n" + "\n".join(rows) +
            "\n\nКакой вариант даёт минимум полной цены суток (мера + дубли)?")
    _t, d = _total(p)
    expl = ("Полная цена = цена меры + дубли, дошедшие до приёмника, × цена дубля. Транзакции платформы убирают дубли "
            "только внутри неё: " + ("приёмник — её топик, дублей нет" if p["sink"] == "topic" else
                                     "приёмник — внешняя БД, дубли остаются") +
            f"; окно {p['W']} мин не ловит повторы старше окна. По вариантам: " +
            "; ".join(f"{NAMES[w]} — дублей {fmt_num(d[w], 0)}, {rub(tot[w])}" for w in ORDER) +
            f". Минимум — {NAMES[good]}. Ловушки: «exactly-once закрывает всё» — {NAMES[traps['eos_all']]}; «окно "
            f"ловит все повторы» — {NAMES[traps['window_all']]}; самая дешёвая мера — {NAMES['none']}; «ноль дублей» — "
            f"{NAMES[traps['zero_dups']]}.")
    P = {k: v for k, v in p.items() if k != "cost"}
    program = PROGRAM.format(P=P, cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[w] for w in ORDER if w != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: дубли в приёмнике и полная цена суток по вариантам.")
