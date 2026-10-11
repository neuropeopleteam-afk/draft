"""devops.k8s.lead_rollout_capacity_mcq — mcq_concept (Lead): стратегия RollingUpdate под ёмкость, квоту и окно выкладки.

Deployment на R реплик; для пикового трафика нужно не меньше M готовых подов всё время выкладки; квота
пространства имён позволяет не больше R + C подов приложения; выкладка идёт волнами по t минут; окно — T минут.
Варианты — четыре пары maxSurge/maxUnavailable (абсолютные и в процентах: по правилам Kubernetes maxSurge
округляется вверх, maxUnavailable — вниз). Верна ровно одна: не опускает число готовых подов ниже M, не
застревает (лишние поды сверх квоты не создаются — при maxUnavailable = 0 выкладка встаёт) и укладывается в окно.

Исходы дистракторов: below_min — maxUnavailable опускает ниже M (часто — из-за округления процента не в ту
сторону); stuck — запас surge съеден квотой при maxUnavailable = 0; slow — безопасно, но волн слишком много.
Ключ проверяется исполнением: программа-модель контроллера по волнам (создать новые в пределах surge и квоты,
удалить старые, пока готовых не меньше R − maxUnavailable, новые готовы к концу волны) проигрывает каждую
стратегию и печатает букву единственной, выполнившей все условия.
"""
from __future__ import annotations

import math

from assessment_bank.families.common._lead_kit import numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.k8s.lead_rollout_capacity_mcq"

CONTEXTS = [("api-gateway", "шлюз API"), ("checkout", "оформление заказа"), ("search-api", "поиск"),
            ("payments", "платежи"), ("notifications", "уведомления"), ("profile", "профили")]

POOL = [("25%", "0"), ("1", "0"), ("0", "1"), ("50%", "0"), ("0", "25%"), ("2", "1"), ("3", "0"), ("100%", "0"),
        ("25%", "25%"), ("0", "50%"), ("2", "0"), ("1", "1"), ("0", "2"), ("30%", "0"), ("0", "30%"), ("4", "0")]

MODEL = """import math
R, M, C, t, T = {R}, {M}, {C}, {t}, {T}
def resolve(v, up):
    if v.endswith("%"):
        x = int(v[:-1]) * R / 100
        return math.ceil(x) if up else math.floor(x)
    return int(v)
def run(surge, unavail):
    s, u = resolve(surge, True), resolve(unavail, False)
    old, new_ready, waves, min_ready = R, 0, 0, R
    steps = 0
    while new_ready < R or old > 0:
        steps += 1
        if steps > 500:
            return "stuck", waves, min_ready
        total = old + new_ready
        create = max(0, min(R + s, R + C) - total)   # не больше R + maxSurge и не сверх квоты
        create = min(create, R - new_ready)
        delete = max(0, min(old, old + new_ready - (R - u)))   # готовых не меньше R − maxUnavailable
        if create == 0 and delete == 0:
            return "stuck", waves, min_ready
        old -= delete
        min_ready = min(min_ready, old + new_ready)
        if create:
            waves += 1                            # ожидание готовности новых подов — одна волна
            new_ready += create
    if min_ready < M:
        return "below_min", waves, min_ready
    if waves * t > T:
        return "slow", waves, min_ready
    return "ok", waves, min_ready
"""

PROGRAM = MODEL + """
opts = __OPTS__
def parse(text):
    a = text.split("maxSurge: ")[1].split(",")[0]
    b = text.split("maxUnavailable: ")[1].split(" ")[0].rstrip(",;")
    return a, b
ok = [k for k, text in opts.items() if run(*parse(text))[0] == "ok"]
print(ok[0] if len(ok) == 1 else "AMBIGUOUS")
"""


def _run(R, M, C, t, T, surge, unavail):
    ns: dict = {}
    exec(MODEL.format(R=R, M=M, C=C, t=t, T=T), ns)      # та же модель, что в проверке (генератор подбирает условия)
    return ns["run"](surge, unavail)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, ctx = rng.choice(CONTEXTS)
    for _ in range(3000):
        R = rng.choice([8, 10, 12, 16, 20])
        M = R - rng.choice([0, 1, 2, 3])
        C = rng.choice([0, 1, 2, 3, 4])
        t = rng.choice([2, 3, 4])
        T = rng.choice([12, 15, 20, 30])
        res = {cfg: _run(R, M, C, t, T, *cfg) for cfg in POOL}
        good = [c for c, r in res.items() if r[0] == "ok"]
        bad = {}
        for c, r in res.items():
            if r[0] != "ok":
                bad.setdefault(r[0], []).append(c)
        if not good or len(bad) < 2:
            continue
        g = rng.choice(good)
        kinds = sorted(bad)
        rng.shuffle(kinds)
        picks = []
        for kd in kinds[:3]:
            picks.append(rng.choice(bad[kd]))
        rest = [c for kd in kinds for c in bad[kd] if c not in picks]
        while len(picks) < 3 and rest:
            c = rng.choice(rest)
            rest.remove(c)
            picks.append(c)
        if len(picks) == 3:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    label = lambda c: f"maxSurge: {c[0]}, maxUnavailable: {c[1]}"
    mm = lambda x: f"{x} {plural(x, 'минута', 'минуты', 'минут')}"
    stem = (f"Deployment `{name}` ({ctx}): {R} реплик. Для пикового трафика нужно не меньше {M} готовых подов всё время "
            f"выкладки. ResourceQuota пространства имён позволяет держать не больше {R + C} подов приложения "
            f"(сверх квоты поды не создаются). Выкладка идёт волнами: каждая волна — {mm(t)} от создания новых подов "
            f"до их готовности. Окно выкладки — {T} минут. Какая стратегия RollingUpdate выполняет все три "
            f"условия (ёмкость, квота, окно)?")
    why = {"below_min": "опускает число готовых подов ниже требуемого", "stuck": "застревает: запас surge съеден квотой, "
           "а удалять старые поды до готовности новых нельзя", "slow": "безопасна, но не укладывается в окно"}
    outcome = {c: _run(R, M, C, t, T, *c) for c in [g] + picks}
    parts = []
    for c in picks:
        kd, waves, mn = outcome[c]
        extra = f" (минимум готовых — {mn})" if kd == "below_min" else (f" ({waves} волн × {t} мин)" if kd == "slow" else "")
        parts.append(f"«{label(c)}» {why[kd]}{extra}")
    kg, wg, mg = outcome[g]
    expl = (f"Верна «{label(g)}»: минимум готовых подов — {mg} (нужно ≥ {M}), {wg} "
            f"{plural(wg, 'волна', 'волны', 'волн')} × {t} мин ≤ {T} мин, квота {R + C} подов не мешает. Проценты: "
            f"maxSurge округляется вверх, maxUnavailable — вниз (от {R} реплик). Остальные: " + "; ".join(parts) + ".")
    program = PROGRAM.format(R=R, M=M, C=C, t=t, T=T)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=label(g),
                       distractors=[label(c) for c in picks], program=program, explanation=expl,
                       params={"R": R, "M": M, "C": C, "t": t, "T": T, "good": list(g),
                               "distractors": {label(c): outcome[c][0] for c in picks}},
                       note="Ответ проверяется программой-моделью контроллера Deployment по волнам.")
