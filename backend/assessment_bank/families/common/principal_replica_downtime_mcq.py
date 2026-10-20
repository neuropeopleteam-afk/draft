"""common.http.principal_replica_downtime_mcq — mcq_concept (Principal): допустимый простой одной реплики зависимости.

Запрос проходит последовательно сервисы с доступностями a_1…a_k и зависимость D из n независимых реплик за
балансировщиком (запрос успешен, если жива хотя бы одна). Цель SLO цепочки — A. Сколько минут в месяц (30 дней)
может быть недоступна каждая реплика D? Решение: доступность D должна быть не меньше A / Πa_i, недоступность D —
u^n, где u — недоступность реплики: u ≤ (1 − A/Πa_i)^(1/n). Ловушки: без остальных сервисов, бюджет поделён на n
вместо корня, линейное вычитание бюджетов, бюджет всей цепочки без корня, корень без учёта остальных.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant
from assessment_bank.gen_utils import plural

FAMILY_ID = "common.http.principal_replica_downtime_mcq"
CONTEXTS = [("оформление заказа", "сервис скидок"), ("перевод между счетами", "сервис лимитов"),
            ("поиск отелей", "сервис цен"), ("запись к врачу", "сервис расписаний"),
            ("оплата подписки", "сервис токенизации карт"), ("вход в личный кабинет", "сервис профилей"),
            ("расчёт доставки", "сервис геокодирования"), ("выдача кредитного решения", "сервис скоринга")]

MODEL = '''
M = 30 * 24 * 60

def prod(xs):
    p = 1.0
    for x in xs:
        p *= x / 100
    return p

def per_replica(P, others=True, root=True):
    need = (P["A"] / 100) / (prod(P["a"]) if others else 1.0)
    budget = 1 - need
    if budget <= 0:
        return None
    u = budget ** (1 / P["n"]) if root else budget / P["n"]
    return round(min(u, 1.0) * M)

def answer(P):
    return per_replica(P)

def traps(P):
    lin = 1 - P["A"] / 100 - sum(1 - x / 100 for x in P["a"])
    return {"no_others": per_replica(P, others=False), "divide_n": per_replica(P, root=False),
            "linear_div": round(max(lin, 0) / P["n"] * M) if lin > 0 else None,
            "chain_budget": round((1 - P["A"] / 100) * M),
            "no_others_div": per_replica(P, others=False, root=False),
            "chain_x_n": round((1 - P["A"] / 100) * M * P["n"])}

def fmt(x):
    return f"{x:,} мин".replace(",", "\\u00a0")
'''


def _sample(rng):
    k = rng.choice([2, 3])
    return {"a": sorted(rng.sample([99.95, 99.97, 99.98, 99.99, 99.995], k)), "A": rng.choice([99.9, 99.92, 99.93, 99.95]),
            "n": rng.choice([2, 3])}


def _accept(P, ns):
    a = ns["answer"](P)
    return a is not None and 5 <= a < 30 * 24 * 60 // 2


def _stem(P, ctx):
    scen, dep = ctx
    svc = ", ".join(f"{num(x, 3).rstrip('0').rstrip(',')} %" for x in P["a"])
    return (f"Сценарий «{scen}» проходит последовательно {len(P['a'])} {plural(len(P['a']), 'сервис', 'сервиса', 'сервисов')} "
            f"с доступностью {svc} и {dep}: {P['n']} независимые реплики за балансировщиком (запрос успешен, если жива "
            f"хотя бы одна; переключение мгновенное). SLO сценария — {num(P['A'], 2).rstrip('0').rstrip(',')} % за месяц "
            f"(30 дней). Отказы независимы.\n\nСколько минут в месяц может быть недоступна каждая реплика ({dep}), "
            "чтобы сценарий держал SLO?")


def _explain(P, a, traps):
    p = 1.0
    for x in P["a"]:
        p *= x / 100
    need = P["A"] / 100 / p
    return (f"Остальные сервисы дают {num(100 * p, 4)} %, значит доступность зависимости должна быть ≥ "
            f"{num(100 * need, 4)} %: недоступность ≤ {num(100 * (1 - need), 4)} %. У {P['n']} независимых реплик "
            f"недоступность — u^{P['n']}, отсюда u ≤ ({num(1 - need, 6)})^(1/{P['n']}) ≈ {a} мин из 43 200.")


TRAP_DESC = {"no_others": "без остальных сервисов цепочки", "divide_n": "бюджет поделён на n вместо корня n-й степени",
             "linear_div": "бюджеты вычтены линейно и поделены на n", "chain_budget": "весь бюджет сценария на одну реплику",
             "no_others_div": "без остальных сервисов и деление на n", "chain_x_n": "бюджет сценария умножен на n"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.12, abs_min=3, trap_first="no_others",
                           trap_desc=TRAP_DESC)
