"""common.arch.retry_amplification_mcq — mcq_concept (Lead): усиление нагрузки повторами по слоям.

Цепочка из трёх вызывающих слоёв (шлюз → сервис 1 → сервис 2 → база); каждый слой при неудаче вызова
нижнего повторяет его до r_i раз (всего 1 + r_i попыток). База перегружена: каждая попытка к ней неудачна
независимо с вероятностью p. Вызов слоя неудачен, если неудачны все его попытки. Сколько в среднем
запросов получит база на один пользовательский запрос?

Ключ: f₃ = p, E₃ = Σ_{j=0..r₃} p^j; f₂ = p^(1+r₃), E₂ = Σ_{j=0..r₂} f₂^j; f₁ = f₂^(1+r₂), E₁ = Σ_{j=0..r₁} f₁^j;
ответ — E₁·E₂·E₃. Дистракторы одной числовой формы:
  * full_outage — произведение (1 + r_i), как будто база отказала полностью (верхняя граница);
  * bottom_only — учтены только повторы нижнего слоя (E₃);
  * independent_layers — каждый слой «видит» отказ с той же вероятностью p: Π Σ_j p^j.
Ключ проверяется исполнением: программа-модель перечисляет все исходы попыток по дереву вызовов точной
арифметикой (Fraction) — распределение пар (успех, число запросов к базе) — и печатает букву варианта.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq, well_separated
from assessment_bank.gen_utils import make_rng, plural

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


def _geom(q: Fraction, r: int) -> Fraction:
    return sum((q ** j for j in range(r + 1)), Fraction(0))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    gw, s1, s2, db = rng.choice(CONTEXTS)
    for _ in range(400):
        r1, r2, r3 = rng.choice([1, 2]), rng.choice([2, 3]), rng.choice([2, 3, 4])
        p = rng.choice([Fraction(1, 2), Fraction(3, 5), Fraction(7, 10), Fraction(4, 5)])
        e3 = _geom(p, r3)
        f2 = p ** (1 + r3)
        e2 = _geom(f2, r2)
        f1 = f2 ** (1 + r2)
        e1 = _geom(f1, r1)
        vals = {"good": e1 * e2 * e3, "full_outage": Fraction((1 + r1) * (1 + r2) * (1 + r3)),
                "bottom_only": e3, "independent_layers": _geom(p, r1) * _geom(p, r2) * e3}
        fl = {k: float(v) for k, v in vals.items()}
        if well_separated(list(fl.values()), 0.12) and fl["good"] > fl["bottom_only"] * 1.12:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    text = {k: f"≈ {fmt_num(v, 2)} запроса" for k, v in fl.items()}
    rr = lambda r: f"{r} {plural(r, 'раза', 'раз', 'раз')}"
    pct = round(100 * float(p))
    stem = (f"Цепочка: «{gw}» → «{s1}» → «{s2}» → «{db}». При неудачном вызове нижнего звена «{gw}» повторяет "
            f"его до {rr(r1)}, «{s1}» — до {rr(r2)}, «{s2}» — до {rr(r3)} (без бюджета повторов; вызов звена "
            f"неудачен, если неудачны все его попытки). Нижнее звено «{db}» перегружено: каждая попытка к нему "
            f"независимо неудачна с вероятностью {pct} %. Сколько в среднем запросов получит «{db}» на один пользовательский "
            f"запрос?")
    retries = [r1, r2, r3]
    program = PROGRAM.format(pn=p.numerator, pd=p.denominator, retries=retries)
    expl = (f"Нижнее звено делает в среднем Σ p^j = {fmt_num(fl['bottom_only'], 2)} попытки на вызов, но его вызов "
            f"неудачен только с вероятностью p^{1 + r3}; верхние слои повторяют с этой (меньшей) вероятностью, "
            f"поэтому итог — произведение средних чисел вызовов по слоям ≈ {fmt_num(fl['good'], 2)}. "
            f"Произведение (1 + r_i) = {fmt_num(fl['full_outage'], 2)} — полный отказ базы (верхняя граница); "
            f"«каждый слой видит отказ с вероятностью p» — {fmt_num(fl['independent_layers'], 2)}: забыто, что "
            f"повторы нижних слоёв уже снизили вероятность отказа звена. Вывод для ведущего: повторы на каждом "
            f"слое умножаются — нужен бюджет повторов и повтор только на одном слое.")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=gw, stem=stem, good=text["good"],
                       distractors=[text["full_outage"], text["bottom_only"], text["independent_layers"]],
                       program=program, explanation=expl,
                       params={"retries": retries, "p": str(p), "mean": round(fl["good"], 4)},
                       note="Ответ проверяется программой-моделью: перечисление всех исходов попыток по дереву "
                            "вызовов точной арифметикой.")
