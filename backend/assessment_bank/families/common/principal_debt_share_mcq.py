"""common.strategy.principal_debt_share_mcq — mcq_concept (Principal, короткое): доля работ на технический долг.

Команда в квартал может сделать C единиц работы. Если на долг идёт доля s, на продукт — (1 − s) · C · p, где p —
производительность (в начале p0 ≤ 1). Каждый квартал долг снижает производительность на d, а работа над долгом
возвращает k · s (p не выше 1 и не ниже 0,2): p ← min(1, max(0,2, p − d + k · s)). Варианты доли — 0, 10, 20 и 30 %.
Вопрос — какая доля даёт больше всего продуктовой работы за горизонт H кварталов.

Ловушки: «ничего на долг — больше продукта сейчас» (0 %), «максимум на долг» (30 %) и расчёт на короткий горизонт
(первые два квартала). Верная доля распределена поровну по четырём и отличается хотя бы от двух ловушек (если верна
сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа моделирует кварталы для каждой доли и
печатает букву максимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "common.strategy.principal_debt_share_mcq"

CONTEXTS = ["платформа платежей", "мобильный банк", "система складского учёта", "маркетплейс", "сервис бронирования",
            "CRM для продаж", "платформа онлайн-обучения", "биллинг оператора связи"]
SHARES = [0, 10, 20, 30]
NAMES = {s: f"{s} % ёмкости на технический долг" for s in SHARES}

PROGRAM = """opts = __OPTS__
C, p0, d, k, H = {C}, {p0}, {d}, {k}, {H}
labels = {labels!r}        # подпись -> доля на долг, %
total = {{}}
for label, share in labels.items():
    s = share / 100
    p, done = p0, 0.0
    for quarter in range(H):
        done += C * (1 - s) * p                      # продуктовая работа квартала
        p = min(1.0, max(0.2, p - d + k * s))         # долг тянет вниз, работа над ним — вверх
    total[label] = done
best = max(total, key=total.get)
hit = [x for x, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _sim(C, p0, d, k, H, share):
    s = share / 100
    p, done = p0, 0.0
    for _ in range(H):
        done += C * (1 - s) * p
        p = min(1.0, max(0.2, p - d + k * s))
    return done


def _argmax(v, rel=0.03):
    o = sorted(v.values(), reverse=True)
    return max(v, key=v.get) if o[0] - o[1] >= rel * o[0] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(SHARES)
    for _ in range(80000):
        C = rng.choice([40, 60, 80, 100])
        p0 = rng.choice([0.6, 0.7, 0.8, 0.9])
        d = rng.choice([0.02, 0.04, 0.06, 0.08])
        k = rng.choice([0.2, 0.3, 0.4, 0.6, 0.8])
        H = rng.choice([4, 6, 8])
        full = {s: _sim(C, p0, d, k, H, s) for s in SHARES}
        good = _argmax(full)
        if good != target:
            continue
        short = _argmax({s: _sim(C, p0, d, k, 2, s) for s in SHARES})
        if short is None:
            continue
        traps = (0, 30, short)
        if sum(t != good for t in traps) >= (1 if good in (0, 30) else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    hq = plural(H, "квартал", "квартала", "кварталов")
    intro = rng.choice([
        f"Вы — главный инженер; продукт — {ctx}. Нужно утвердить, какую долю ёмкости команды отдавать на "
        f"технический долг в ближайшие {H} {hq}.",
        f"При планировании продукта «{ctx}» на {H} {hq} спорят о доле работ на технический долг; решение — за "
        f"вами как за главным инженером.",
        f"Руководство продукта «{ctx}» просит главного инженера назвать долю ёмкости на технический долг на "
        f"{H} {hq}.",
    ])
    stem = (f"{intro} Модель (оценка по истории команды): ёмкость — {C} единиц работы в квартал; производительность "
            f"сейчас {fmt_num(p0, 2)} от возможной. Продуктовой работы за квартал = ёмкость × (1 − доля на долг) × "
            f"производительность. После каждого квартала производительность падает на {fmt_num(d, 2)} из-за "
            f"накопления долга и растёт на {fmt_num(k, 1)} × долю на долг (не выше 1 и не ниже 0,2). Доля постоянна "
            f"весь горизонт. Варианты: 0, 10, 20 или 30 % ёмкости.\n\nКакая доля даёт больше всего продуктовой "
            f"работы за {H} {hq}?")
    expl = ("По кварталам: работа += C × (1 − s) × p; затем p ← min(1, max(0,2, p − d + k × s)). Итоги: " +
            "; ".join(f"{s} % — {fmt_num(full[s], 1)}" for s in SHARES) +
            f". Максимум — {good} %. На горизонте двух кварталов вышло бы {short} %: отдача от долга приходит позже.")
    program = PROGRAM.format(C=C, p0=p0, d=d, k=k, H=H, labels={NAMES[s]: s for s in SHARES})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[s] for s in SHARES if s != good], program=program, explanation=expl,
                       params={"C": C, "p0": p0, "d": d, "k": k, "H": H, "good": good, "short": short},
                       note="Ответ проверяется программой: моделирование кварталов для каждой доли.")
