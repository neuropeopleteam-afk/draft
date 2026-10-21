"""common.arch.retry_amplification_mcq — mcq_concept (Lead): усиление нагрузки повторами по слоям.

Цепочка из трёх вызывающих слоёв (шлюз → сервис 1 → сервис 2 → база); каждый слой при неудаче вызова
нижнего повторяет его до r_i раз (всего 1 + r_i попыток). База перегружена: каждая попытка к ней неудачна
независимо с вероятностью p. Вызов слоя неудачен, если неудачны все его попытки. Сколько в среднем
запросов получит база на один пользовательский запрос?

Ключ: f₃ = p, E₃ = Σ_{j=0..r₃} p^j; f₂ = p^(1+r₃), E₂ = Σ_{j=0..r₂} f₂^j; f₁ = f₂^(1+r₂), E₁ = Σ_{j=0..r₁} f₁^j;
ответ — E₁·E₂·E₃. Дистракторы одной числовой формы — три из шести (ранг ключа задаётся по seed до подбора чисел
через n_below ∈ {0, 1, 2, 3} и spread_pick):
  выше ключа —
  * full_outage — произведение (1 + r_i), как будто база отказала полностью (верхняя граница);
  * independent_layers — каждый слой «видит» отказ с той же вероятностью p: Π Σ_j p^j;
  * top_sees_p — забыто только для шлюза: Σ_j p^j (шлюз) · E₂ · E₃;
  ниже ключа —
  * bottom_only — учтены только повторы нижнего слоя (E₃);
  * two_layers — учтены только два нижних слоя (E₂ · E₃, без повторов шлюза);
  * additive — повторы слоёв сложены, а не перемножены: E₁ + E₂ + E₃ − 2;
  * linear_p — линейная оценка 1 + p·(r₁ + r₂ + r₃).
Числа в вариантах — три значащие цифры (2,50 / 24,0), чтобы длина подписи не выдавала величину.
Ключ проверяется исполнением: программа-модель перечисляет все исходы попыток по дереву вызовов точной
арифметикой (Fraction) — распределение пар (успех, число запросов к базе) — и печатает букву варианта.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq, well_separated
from assessment_bank.gen_utils import make_rng, plural, spread_pick

FAMILY_ID = "common.arch.retry_amplification_mcq"

CONTEXTS = [
    ("API-шлюз", "сервис заказов", "сервис остатков", "PostgreSQL"),
    ("BFF мобильного приложения", "сервис профилей", "сервис рекомендаций", "хранилище признаков"),
    ("шлюз партнёрского API", "сервис платежей", "сервис лимитов", "база лимитов"),
    ("веб-шлюз", "сервис поиска", "сервис ранжирования", "кластер Elasticsearch"),
    ("шлюз личного кабинета", "сервис документов", "сервис подписи", "база документов"),
]

PROGRAM = """from fractions import Fraction
p = Fraction({pn}, {pd})
retries = {retries}          # повторы слоёв сверху вниз: шлюз, сервис 1, сервис 2

def layer(i):
    # распределение исходов вызова слоя i: {{(успех, запросов к базе): вероятность}}
    if i == len(retries):
        return {{(True, 1): 1 - p, (False, 1): p}}        # одна попытка к базе
    sub = layer(i + 1)
    dist = {{(False, 0): Fraction(1)}}                    # «ещё ни одной попытки, неуспех»
    for _ in range(1 + retries[i]):
        nxt = {{}}
        for (ok, n), pr in dist.items():
            if ok:
                nxt[(ok, n)] = nxt.get((ok, n), 0) + pr  # успех — больше не повторяем
                continue
            for (ok2, n2), pr2 in sub.items():
                key = (ok2, n + n2)
                nxt[key] = nxt.get(key, 0) + pr * pr2
        dist = nxt
    return dist

d = layer(0)
mean = float(sum(n * pr for (ok, n), pr in d.items()))
opts = __OPTS__
def val(t):
    return float(t.split("≈ ")[1].split(" ")[0].replace(",", "."))
hit = [k for k, t in opts.items() if abs(val(t) - mean) <= 0.051 * mean]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _sig3(x: float) -> str:
    """Три значащие цифры: длина подписи варианта не выдаёт порядок величины (2,50 / 24,0)."""
    return fmt_num(x, 2 if x < 10 else 1 if x < 100 else 0)


def _geom(q: Fraction, r: int) -> Fraction:
    return sum((q ** j for j in range(r + 1)), Fraction(0))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    gw, s1, s2, db = rng.choice(CONTEXTS)
    n_below = make_rng(FAMILY_ID, seed // 4, "rank").sample(range(4), 4)[seed % 4]
    for _ in range(1200):
        r1, r2, r3 = rng.choice([1, 2, 3]), rng.choice([2, 3]), rng.choice([2, 3, 4])
        p = rng.choice([Fraction(3, 5), Fraction(13, 20), Fraction(7, 10),
                        Fraction(3, 4), Fraction(4, 5), Fraction(17, 20), Fraction(9, 10)])
        e3 = _geom(p, r3)
        f2 = p ** (1 + r3)
        e2 = _geom(f2, r2)
        f1 = f2 ** (1 + r2)
        e1 = _geom(f1, r1)
        good = float(e1 * e2 * e3)
        cand = {
            "full_outage": float((1 + r1) * (1 + r2) * (1 + r3)),
            "independent_layers": float(_geom(p, r1) * _geom(p, r2) * e3),
            "top_sees_p": float(_geom(p, r1) * e2 * e3),
            "mid_sees_p": float(e1 * _geom(p, r2) * e3),
            "two_layers": float(e2 * e3),
            "bottom_only": float(e3),
            "additive": float(e1 + e2 + e3 - 2),
            "linear_p": float(1 + p * (r1 + r2 + r3)),
            "first_retry_only": float(1 + p + p ** 2),
        }
        below = [k for k, v in cand.items() if v < good * 0.90]
        above = [k for k, v in cand.items() if v > good * 1.10]
        if len(below) < n_below or len(above) < 3 - n_below:
            continue
        rng.shuffle(below)
        rng.shuffle(above)
        sp = spread_pick(rng, good, below, above, n_below, 3 - n_below, cand.__getitem__,
                         lambda tvals: well_separated([good, *tvals], 0.11), min_step=0.11)
        if sp is not None:
            traps = [k for k, _ in sp]
            fl = {"good": good, **{k: cand[k] for k in traps}}
            allv = cand
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    text = {k: f"≈ {_sig3(v)} запроса" for k, v in fl.items()}
    rr = lambda r: f"{r} {plural(r, 'раза', 'раз', 'раз')}"
    pct = round(100 * float(p))
    stem = (f"Цепочка: «{gw}» → «{s1}» → «{s2}» → «{db}». При неудачном вызове нижнего звена «{gw}» делает "
            f"до {rr(r1)} повторных попыток сверх первой (всего до {1 + r1} попыток на вызов), «{s1}» — "
            f"до {rr(r2)} повторных попыток сверх первой (всего до {1 + r2}), «{s2}» — до {rr(r3)} повторных "
            f"попыток сверх первой (всего до {1 + r3}; без бюджета повторов, вызов звена неудачен, только если "
            f"неудачны все его попытки). Нижнее звено «{db}» перегружено: каждая попытка к нему независимо "
            f"неудачна с вероятностью {pct} %. Сколько в среднем запросов получит «{db}» на один пользовательский "
            f"запрос?")
    retries = [r1, r2, r3]
    program = PROGRAM.format(pn=p.numerator, pd=p.denominator, retries=retries)
    why = {
        "full_outage": f"произведение (1 + r_i) = {_sig3(allv['full_outage'])} — полный отказ базы (верхняя граница)",
        "independent_layers": (f"«каждый слой видит отказ с вероятностью p» — {_sig3(allv['independent_layers'])}: "
                               f"забыто, что повторы нижних слоёв уже снизили вероятность отказа звена"),
        "top_sees_p": (f"«шлюз видит отказ с вероятностью p» — {_sig3(allv['top_sees_p'])}: то же упущение "
                       f"для верхнего слоя"),
        "mid_sees_p": (f"«средний слой видит отказ с вероятностью p» — {_sig3(allv['mid_sees_p'])}: не учтено "
                       f"сглаживание отказов нижним звеном"),
        "two_layers": f"учтены только два нижних звена — {_sig3(allv['two_layers'])}: без повторов шлюза",
        "bottom_only": f"только повторы нижнего звена — {_sig3(allv['bottom_only'])}: верхние слои не учтены",
        "additive": (f"сумма E₁ + E₂ + E₃ − 2 = {_sig3(allv['additive'])}: повторы слоёв сложены, а они "
                     f"перемножаются"),
        "linear_p": f"линейная оценка 1 + p·Σr_i = {_sig3(allv['linear_p'])} без каскадного умножения",
        "first_retry_only": f"учтены только первые два повтора 1 + p + p² = {_sig3(allv['first_retry_only'])}",
    }
    expl = (f"Нижнее звено делает в среднем Σ p^j = {_sig3(allv['bottom_only'])} попытки на вызов, но его вызов "
            f"неудачен только с вероятностью p^{1 + r3}; верхние слои повторяют с этой (меньшей) вероятностью, "
            f"поэтому итог — произведение средних чисел вызовов по слоям ≈ {_sig3(fl['good'])}. Ловушки: "
            + "; ".join(why[k] for k in sorted(traps)) +
            ". Вывод для ведущего: повторы на каждом слое умножаются — нужен бюджет повторов и повтор только на "
            "одном слое.")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=gw, stem=stem, good=text["good"],
                       distractors=[text[k] for k in traps],
                       program=program, explanation=expl,
                       params={"retries": retries, "p": str(p), "mean": round(fl["good"], 4),
                               "n_below": n_below, "traps": traps},
                       note="Ответ проверяется программой-моделью: перечисление всех исходов попыток по дереву "
                            "вызовов точной арифметикой.")
