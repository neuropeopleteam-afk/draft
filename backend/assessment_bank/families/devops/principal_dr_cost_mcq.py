"""devops.strategy.principal_dr_cost_mcq — mcq_concept (Principal): стратегия аварийного восстановления по ожидаемой цене.

Четыре стратегии на случай потери региона: резервные копии с восстановлением, «тлеющий запал» (минимальная
копия инфраструктуры), тёплый резерв, активный-активный. У каждой — годовая стоимость, время восстановления
(RTO) и окно потери данных (RPO). Даны вероятность потери региона за год, потери бизнеса за час простоя,
цена минуты потерянных данных (ручная сверка, компенсации) и требование регулятора к RTO (стратегии, его не
выполняющие, недопустимы). Вопрос — какая допустимая стратегия даёт минимальную ожидаемую годовую цену
(стоимость + вероятность × (RTO × потери в час + RPO × цена минуты данных)).

Ловушки: «самая дешёвая инфраструктура» (без риска), «самая надёжная» (без цены), выбор без требования
регулятора, без цены потерянных данных. Генератор подбирает числа так, что верный ответ отличается хотя бы
от двух ловушек (если верна самая дешёвая или самая надёжная — хотя бы от одной) и меняется между вариантами.
Ключ проверяется исполнением: программа перебирает годы-сценарии (без события и с событием) с весами
вероятности, отбрасывает недопустимые и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.strategy.principal_dr_cost_mcq"

CONTEXTS = ["платёжный процессинг", "интернет-банк", "маркетплейс", "систему записи к врачу", "облачную онлайн-кассу",
            "логистическую платформу"]

NAMES = {"backup": "резервные копии с восстановлением", "pilot": "минимальная копия инфраструктуры («тлеющий запал»)",
         "warm": "тёплый резерв в другом регионе", "active": "активный-активный в двух регионах"}

PROGRAM = """opts = __OPTS__
plans = {plans!r}          # название -> (стоимость в год, RTO ч, RPO мин), млн ₽
p, loss_h, loss_min, rto_max = {p}, {loss_h}, {loss_min}, {rto_max}
best, best_cost = None, None
for name, (cost, rto, rpo) in plans.items():
    if rto > rto_max:
        continue
    years = [(1 - p, cost), (p, cost + rto * loss_h + rpo * loss_min)]   # год без события и с событием
    expected = sum(w * c for w, c in years)
    if best_cost is None or expected < best_cost - 1e-9:
        best, best_cost = name, expected
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _exp(plan, p, loss_h, loss_min):
    cost, rto, rpo = plan
    return cost + p * (rto * loss_h + rpo * loss_min)


def _argmin(d, rel=0.04):
    s = sorted(d.values())
    if len(s) < 2:
        return min(d, key=d.get) if s else None
    return min(d, key=d.get) if s[1] - s[0] >= rel * s[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(["pilot", "warm", "active", "backup"])
    for _ in range(20000):
        plans = {
            "backup": (rng.choice([3, 5, 8]), rng.choice([24, 36, 48]), rng.choice([240, 720, 1440])),
            "pilot": (rng.choice([12, 18, 25]), rng.choice([4, 6, 8]), rng.choice([15, 30, 60])),
            "warm": (rng.choice([35, 50, 70]), rng.choice([1, 2]), rng.choice([1, 5])),
            "active": (rng.choice([90, 120, 160]), rng.choice([0.1, 0.25]), 0),
        }
        p = rng.choice([0.02, 0.05, 0.1, 0.2])
        loss_h = rng.choice([5, 15, 40, 100])         # млн ₽ за час простоя
        loss_min = rng.choice([0.05, 0.2, 0.5, 1.0])  # млн ₽ за минуту потерянных данных
        rto_max = rng.choice([4, 8, 24, 72])
        allowed = {k: v for k, v in plans.items() if v[1] <= rto_max}
        if len(allowed) < 3:
            continue
        full = {k: _exp(v, p, loss_h, loss_min) for k, v in allowed.items()}
        good = _argmin(full)
        if good != target:
            continue
        cheap = min(plans, key=lambda k: plans[k][0])                     # самая дешёвая инфраструктура
        safe = min(plans, key=lambda k: (plans[k][1], plans[k][2]))        # самая надёжная
        no_reg = _argmin({k: _exp(v, p, loss_h, loss_min) for k, v in plans.items()})
        no_rpo = _argmin({k: _exp((v[0], v[1], 0), p, loss_h, loss_min) for k, v in allowed.items()})
        traps = {"дешёвая": cheap, "надёжная": safe, "без регулятора": no_reg, "без цены данных": no_rpo}
        differ = sum(1 for v in traps.values() if v is not None and v != good)
        if differ >= (1 if good in ("backup", "active") else 2) and None not in (no_reg, no_rpo):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    order = ["backup", "pilot", "warm", "active"]
    rows = []
    for k in order:
        c, rto, rpo = plans[k]
        rpo_t = "без потери данных" if rpo == 0 else f"RPO {fmt_num(rpo, 0)} мин"
        rows.append(f"• {NAMES[k].capitalize()}: {fmt_num(c, 0)} млн ₽ в год, RTO {fmt_num(rto, 2 if rto < 1 else 0)} ч, "
                    f"{rpo_t}.")
    stem = (f"Вы — главный инженер, отвечаете за {ctx}. Выбираете стратегию на случай потери целого региона облака. "
            f"Вероятность такого события — около {fmt_num(100 * p, 0)} % в год. Час простоя стоит бизнесу ≈ "
            f"{fmt_num(loss_h, 0)} млн ₽, минута потерянных данных (ручная сверка, компенсации) — ≈ "
            f"{fmt_num(loss_min, 2)} млн ₽. Регулятор требует восстанавливать работу не дольше чем за {rto_max} ч. "
            f"Варианты:\n" + "\n".join(rows) +
            "\n\nКакая допустимая стратегия даёт минимальную ожидаемую годовую цену (стоимость стратегии плюс "
            "ожидаемые потери от события)?")
    allowed_txt = "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in order if k in full)
    banned = [NAMES[k] for k in order if k not in full]
    expl = (f"Ожидаемая цена = стоимость + {fmt_num(p, 2)} × (RTO × {fmt_num(loss_h, 0)} + RPO × {fmt_num(loss_min, 2)}). "
            f"Допустимые (RTO ≤ {rto_max} ч): {allowed_txt}"
            + (f"; недопустимы: {', '.join(banned)}" if banned else "") +
            f". Минимум — {NAMES[good]}. Ловушки: самая дешёвая инфраструктура — {NAMES[cheap]}; самая надёжная — "
            f"{NAMES[safe]}; без требования регулятора — {NAMES[no_reg]}; без цены потерянных данных — {NAMES[no_rpo]}.")
    program = PROGRAM.format(plans={NAMES[k]: plans[k] for k in order}, p=p, loss_h=loss_h, loss_min=loss_min,
                             rto_max=rto_max)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in order if k != good], program=program, explanation=expl,
                       params={"p": p, "loss_h": loss_h, "loss_min": loss_min, "rto_max": rto_max, "good": good,
                               "cheap": cheap, "safe": safe, "no_reg": no_reg, "no_rpo": no_rpo},
                       note="Ответ проверяется программой: годы-сценарии с весами вероятности, недопустимые "
                            "стратегии отброшены.")
