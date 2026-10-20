"""common.k8s.k8s_rollout_capacity_mcq — mcq_concept (Senior/Lead, Kubernetes): мощность сервиса в худший момент выкладки.

Deployment на R реплик, стратегия RollingUpdate с maxSurge и maxUnavailable в процентах. Kubernetes округляет
maxSurge вверх, maxUnavailable — вниз; в любой момент готовых подов не меньше R − maxUnavailable. Под держит c
запросов в секунду. Вопрос: какой поток гарантированно выдержит сервис в худший момент выкладки (новые поды
готовы не сразу). Ловушки: maxUnavailable округлён вверх, проценты без округления, «всего подов R + maxSurge»,
без учёта maxUnavailable (R·c), maxSurge вычтен вместо maxUnavailable. ``brute`` — пошаговая имитация контроллера
(создание новых подов в пределах surge, удаление старых в пределах unavailable, новые поды готовы через шаг).
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.k8s.k8s_rollout_capacity_mcq"
CONTEXTS = ["API каталога", "сервис поиска", "шлюз платежей", "сервис корзины", "API профиля", "сервис рекомендаций",
            "бэкенд мобильного приложения", "сервис уведомлений"]

MODEL = '''
from math import ceil, floor

def unavail(P, up=False, exact=False):
    x = P["R"] * P["u"] / 100
    return x if exact else (ceil(x) if up else floor(x))

def surge(P):
    return ceil(P["R"] * P["s"] / 100)

def answer(P):
    mu = unavail(P)
    if mu == 0 and surge(P) == 0:
        mu = 1
    return (P["R"] - mu) * P["c"]

def brute(P):
    R, ms, mu = P["R"], surge(P), unavail(P)
    if ms == 0 and mu == 0:
        mu = 1
    old, new_ready, new_pending, low = R, 0, 0, R
    while old > 0 or new_pending > 0:
        new_ready += new_pending
        new_pending = 0
        total = old + new_ready
        can_add = max(0, R + ms - total)
        add = min(can_add, R - new_ready - new_pending)
        new_pending += add
        ready = old + new_ready
        kill = max(0, min(old, ready - (R - mu)))
        old -= kill
        low = min(low, old + new_ready)
    return low * P["c"]

def traps(P):
    R, c = P["R"], P["c"]
    return {"ceil_unavail": (R - unavail(P, up=True)) * c, "exact_pct": round((R - unavail(P, exact=True)) * c),
            "surge_total": (R + surge(P)) * c, "full": R * c, "minus_surge": (R - surge(P)) * c,
            "half": R * c // 2}

def fmt(x):
    return f"{x:,} RPS".replace(",", "\\u00a0")
'''


def _sample(rng):
    return {"R": rng.choice([6, 7, 9, 10, 11, 13, 14, 18, 22, 30]), "s": rng.choice([10, 25, 30, 50]),
            "u": rng.choice([10, 15, 25, 30, 40]), "c": rng.choice([120, 150, 200, 250, 400])}


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]}: Deployment на {P['R']} реплик, стратегия RollingUpdate с maxSurge: "
            f"{P['s']} % и maxUnavailable: {P['u']} %. Один готовый под держит {P['c']} RPS; новый под становится "
            "готовым (readiness) не сразу, трафик идёт только на готовые поды.\n\nКакой наибольший поток сервис "
            "гарантированно выдержит в любой момент выкладки?")


def _explain(P, a, traps):
    from math import floor, ceil
    mu, ms = floor(P["R"] * P["u"] / 100), ceil(P["R"] * P["s"] / 100)
    return (f"Kubernetes переводит проценты в поды: maxSurge округляется вверх ({ms}), maxUnavailable — вниз ({mu}). "
            f"Контроллер держит готовыми не меньше R − maxUnavailable = {P['R'] - mu} подов; surge добавляет поды, "
            f"которые ещё не готовы, и мощность не увеличивает. {P['R'] - mu} · {P['c']} = {num(a)} RPS.")


TRAP_DESC = {"ceil_unavail": "maxUnavailable округлён вверх", "exact_pct": "проценты без округления до подов",
             "surge_total": "все R + maxSurge подов считаются готовыми", "full": "без учёта maxUnavailable",
             "minus_surge": "вычтен maxSurge вместо maxUnavailable", "half": "половина мощности"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, rel=0.03, abs_min=50, trap_first="ceil_unavail", trap_desc=TRAP_DESC)
