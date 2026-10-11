"""data_ml.exp.duration_cuped_mcq — mcq_concept (Lead): длительность A/B-эксперимента с CUPED.

Базовая конверсия p₀, минимальный обнаруживаемый эффект — относительный (m % от p₀), α = 0,05 (двусторонний),
мощность 80 %, CUPED по предпериоду с корреляцией ρ (дисперсия × (1 − ρ²)), в эксперимент идёт доля трафика
(поровну на две группы). Сколько полных дней нужно?

Ключ: n на группу = (z₀,₉₇₅ + z₀,₈)² · 2·p₀(1 − p₀)(1 − ρ²) / (p₀·m)²; дней = ⌈2n / (T·доля)⌉.
Дистракторы одной числовой формы (дни):
  * no_cuped — дисперсия без снижения (1 − ρ²);
  * one_group — забыта вторая группа (n вместо 2n);
  * one_sided — односторонний z₀,₉₅ вместо двустороннего.
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


def _days(p0, m, rho, traffic, share, *, cuped=True, groups=2, two_sided=True):
    z = NormalDist().inv_cdf
    za = z(1 - 0.05 / 2) if two_sided else z(1 - 0.05)
    var = p0 * (1 - p0) * ((1 - rho ** 2) if cuped else 1)
    n = math.ceil((za + z(0.8)) ** 2 * 2 * var / (p0 * m) ** 2)
    return math.ceil(groups * n / (traffic * share)), n


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, metric = rng.choice(CONTEXTS)
    for _ in range(500):
        p0 = rng.choice([0.02, 0.04, 0.06, 0.1, 0.15, 0.25])
        m = rng.choice([0.03, 0.05, 0.08, 0.1])
        rho = rng.choice([0.4, 0.5, 0.6, 0.7])
        traffic = rng.choice([8000, 15000, 30000, 60000, 120000])
        share = rng.choice([0.2, 0.3, 0.5, 1.0])
        args = (p0, m, rho, traffic, share)
        good, n = _days(*args)
        vals = {"good": good, "no_cuped": _days(*args, cuped=False)[0], "one_group": _days(*args, groups=1)[0],
                "one_sided": _days(*args, two_sided=False)[0]}
        if 7 <= good <= 60 and min(vals.values()) >= 3 and well_separated(list(vals.values()), 0.12) \
                and min(abs(a - b) for a in vals.values() for b in vals.values() if a != b) >= 3:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    text = {k: f"{v} {plural(v, 'день', 'дня', 'дней')}" for k, v in vals.items()}
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
            f"{text['good']}. Без CUPED "
            f"(дисперсия без множителя 1 − ρ²) — {text['no_cuped']}; одна группа вместо двух — {text['one_group']}; "
            f"односторонний z = 1,645 — {text['one_sided']}. Дальше ведущий округлит до целых недель из-за "
            f"недельной сезонности — но минимум задаёт расчёт мощности.")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=text["good"],
                       distractors=[text["no_cuped"], text["one_group"], text["one_sided"]], program=program,
                       explanation=expl,
                       params={"p0": p0, "m": m, "rho": rho, "traffic": traffic, "share": share, "n": n,
                               "days": vals},
                       note="Ответ проверяется программой: минимальное n с мощностью ≥ 0,8 двоичным поиском по "
                            "функции мощности.")
