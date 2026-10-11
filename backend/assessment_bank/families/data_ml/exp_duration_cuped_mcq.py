"""data_ml.exp.duration_cuped_mcq — mcq_concept (Lead): длительность A/B-эксперимента с CUPED.

Базовая конверсия p₀, минимальный обнаруживаемый эффект — относительный (m % от p₀), α = 0,05 (двусторонний),
мощность 80 %, CUPED по предпериоду с корреляцией ρ (дисперсия × (1 − ρ²)), в эксперимент идёт доля трафика
(поровну на две группы). Сколько полных дней нужно?

Ключ: n на группу = (z₀,₉₇₅ + z₀,₈)² · 2·p₀(1 − p₀)(1 − ρ²) / (p₀·m)²; дней = ⌈2n / (T·доля)⌉.
Дистракторы одной числовой формы (дни) — три из пяти (версия 2: число ловушек больше ключа равновероятно
0, 1 или 2, поэтому место ключа по величине меняется):
  больше ключа —
  * no_cuped — дисперсия без снижения (1 − ρ²);
  * double_split — размер обеих групп поделён на трафик одной группы (2n / (T·доля/2));
  меньше ключа —
  * one_group — забыта вторая группа (n вместо 2n);
  * one_sided — односторонний z₀,₉₅ вместо двустороннего;
  * rho_linear — множитель CUPED (1 − ρ) вместо (1 − ρ²).
Ключ проверяется исполнением: программа ищет минимальное n с мощностью ≥ 0,8 перебором (двоичный поиск
по функции мощности Φ(δ/SE − z), а не обращением формулы) и сверяет дни с вариантами (допуск — 1 день).
"""
from __future__ import annotations

import math
from statistics import NormalDist

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq, well_separated
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_ml.exp.duration_cuped_mcq"

CONTEXTS = [("оформление заказа", "конверсия в заказ"), ("отклик на вакансию", "доля откликнувшихся"),
            ("оплата подписки", "конверсия в оплату"), ("регистрация", "доля завершивших регистрацию"),
            ("бронирование", "конверсия в бронь"), ("заявка на кредит", "доля отправивших заявку")]

PROGRAM = """from statistics import NormalDist
import math
p0, m, rho, traffic, share = {p0}, {m}, {rho}, {traffic}, {share}
Z = NormalDist()
var = p0 * (1 - p0) * (1 - rho ** 2)
delta = p0 * m
za = Z.inv_cdf(1 - 0.05 / 2)
def power(n):
    se = math.sqrt(2 * var / n)
    return Z.cdf(delta / se - za)
lo, hi = 1, 10 ** 9
while lo < hi:
    mid = (lo + hi) // 2
    if power(mid) >= 0.8:
        hi = mid
    else:
        lo = mid + 1
days = math.ceil(2 * lo / (traffic * share))
opts = __OPTS__
def val(t):
    return int(t.split(" ")[0])
hit = [k for k, t in opts.items() if abs(val(t) - days) <= 1]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _days(p0, m, rho, traffic, share, *, cuped=True, groups=2, two_sided=True, rho_pow=2, split=1):
    z = NormalDist().inv_cdf
    za = z(1 - 0.05 / 2) if two_sided else z(1 - 0.05)
    var = p0 * (1 - p0) * ((1 - rho ** rho_pow) if cuped else 1)
    n = math.ceil((za + z(0.8)) ** 2 * 2 * var / (p0 * m) ** 2)
    return math.ceil(groups * n / (traffic * share / split)), n


WHY = {"no_cuped": "без CUPED (дисперсия без множителя 1 − ρ²) — {d}",
       "double_split": "размер обеих групп (2n) поделён на трафик одной группы — {d}",
       "one_group": "одна группа вместо двух — {d}",
       "one_sided": "односторонний z = 1,645 — {d}",
       "rho_linear": "множитель CUPED 1 − ρ вместо 1 − ρ² — {d}"}
ABOVE = {"no_cuped": dict(cuped=False), "double_split": dict(split=2)}
BELOW = {"one_group": dict(groups=1), "one_sided": dict(two_sided=False), "rho_linear": dict(rho_pow=1)}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, metric = rng.choice(CONTEXTS)
    n_above = rng.choice([0, 1, 2])          # сколько ловушек больше ключа — до подбора чисел
    for _ in range(500):
        p0 = rng.choice([0.02, 0.04, 0.06, 0.1, 0.15, 0.25])
        m = rng.choice([0.03, 0.05, 0.08, 0.1])
        rho = rng.choice([0.4, 0.5, 0.6, 0.7])
        traffic = rng.choice([8000, 15000, 30000, 60000, 120000])
        share = rng.choice([0.2, 0.3, 0.5, 1.0])
        args = (p0, m, rho, traffic, share)
        good, n = _days(*args)
        traps = rng.sample(sorted(ABOVE), n_above) + rng.sample(sorted(BELOW), 3 - n_above)
        alld = {k: _days(*args, **kw)[0] for k, kw in (ABOVE | BELOW).items()}
        vals = {"good": good, **{k: alld[k] for k in traps}}
        if 7 <= good <= 60 and min(vals.values()) >= 3 and well_separated(list(vals.values()), 0.12) \
                and min(abs(a - b) for a in vals.values() for b in vals.values() if a != b) >= 3:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    day = lambda v: f"{v} {plural(v, 'день', 'дня', 'дней')}"
    text = {k: day(v) for k, v in vals.items()}
    pct = lambda x: fmt_num(100 * x, 0 if abs(100 * x - round(100 * x)) < 1e-9 else 1)
    stem = (f"Эксперимент на шаге «{ctx}»: метрика — {metric}, сейчас {pct(p0)} %. Продукту важен рост не меньше "
            f"{pct(m)} % относительно текущего значения (то есть до {fmt_num(100 * p0 * (1 + m), 2)} %). Уровень "
            f"значимости 0,05 (двусторонняя проверка), мощность 80 %; метрику оцениваем с CUPED по предпериоду, "
            f"корреляция с ковариатой ρ = {fmt_num(rho, 1)}. На шаг приходит {fmt_num(traffic, 0)} пользователей в день, в "
            f"эксперимент отдаём {pct(share)} % трафика поровну на контроль и тест. Сколько полных дней минимум "
            f"должен идти эксперимент?")
    program = PROGRAM.format(p0=p0, m=m, rho=rho, traffic=traffic, share=share)
    expl = (f"n на группу = (1,96 + 0,84)² · 2 · p₀(1 − p₀)(1 − ρ²) / (p₀·m)² ≈ {fmt_num(n, 0)}; обе группы — "
            f"вместе {fmt_num(2 * n, 0)}; при {fmt_num(traffic * share, 0)} пользователях в день в эксперименте → "
            f"{text['good']}. Ловушки: " + "; ".join(WHY[k].format(d=day(alld[k])) for k in sorted(traps)) +
            ". Дальше ведущий округлит до целых недель из-за недельной сезонности — но минимум задаёт расчёт "
            "мощности.")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=text["good"],
                       distractors=[text[k] for k in traps], program=program,
                       explanation=expl,
                       params={"p0": p0, "m": m, "rho": rho, "traffic": traffic, "share": share, "n": n,
                               "days": vals, "traps": traps},
                       note="Ответ проверяется программой: минимальное n с мощностью ≥ 0,8 двоичным поиском по "
                            "функции мощности.")
