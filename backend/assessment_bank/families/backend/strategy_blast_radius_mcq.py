"""backend.strategy.blast_radius_mcq — mcq_concept (Principal): ограничение радиуса поражения — ячейки, канарейка или ничего.

Сервис с U пользователями; за год — k дефектных выкладок и m отказов общей зависимости внутри развёртывания
(база, кэш, очередь). Дефект замечают через t_det минут после попадания к пользователям, откат — t_rb минут;
отказ зависимости длится t_inc минут. Четыре варианта:
  * одно развёртывание, выкладка сразу на всех (без доплаты);
  * одно развёртывание и канарейка s % на W минут (замечает дефект с вероятностью q_c);
  * N ячеек, выкладка волнами — сначала одна ячейка на W минут (замечает дефект с вероятностью q_n);
  * N ячеек, выкладка сразу во все (ячейки ограничивают только отказы зависимостей).
У ячеек и канарейки — годовая доплата (инфраструктура, сопровождение). Минута недоступности для одного
пользователя стоит V ₽. Вопрос — какой вариант даёт минимальную ожидаемую годовую цену (доплата + ожидаемые
потери от дефектных выкладок и отказов зависимостей).

Ловушки: «без доплаты», «максимальная защита», учёт только выкладок (без отказов зависимостей), учёт только
отказов зависимостей. Генератор подбирает числа так, что верный ответ отличается хотя бы от двух ловушек
(если верен вариант без доплаты или максимальной защиты — хотя бы от одной) и меняется между вариантами.
Ключ проверяется исполнением: программа перебирает исходы каждого события (замечен на первой волне / нет)
с весами вероятности и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "backend.strategy.blast_radius_mcq"

CONTEXTS = ["интернет-банк", "маркетплейс", "сервис такси", "платформа найма", "онлайн-кинотеатр",
            "сервис доставки продуктов"]

NAMES = {"none": "одно развёртывание, выкладка сразу на всех", "canary": "одно развёртывание и канарейка",
         "cells": "ячейки и выкладка волнами по ячейкам", "cells_flat": "ячейки, выкладка сразу во все"}

PROGRAM = """opts = __OPTS__
U, V, k, m = {U}, {V}, {k}, {m}
t_det, t_rb, t_inc, W = {t_det}, {t_rb}, {t_inc}, {W}
plans = {plans!r}     # название -> (доплата млн ₽, доля первой волны или None, вероятность заметить, доля при отказе)
cost = {{}}
for name, (extra, first, q, inc_share) in plans.items():
    loss = 0.0
    for _ in range(k):                         # дефектная выкладка: исходы с весами
        if first is None:
            outcomes = [(1.0, 1.0 * (t_det + t_rb))]
        else:
            outcomes = [(q, first * (t_det + t_rb)),
                        (1 - q, first * W + 1.0 * (t_det + t_rb))]
        loss += sum(w * share_min for w, share_min in outcomes) * U * V / 1e6
    for _ in range(m):                         # отказ общей зависимости внутри развёртывания
        loss += inc_share * t_inc * U * V / 1e6
    cost[name] = extra + loss
best = min(cost, key=cost.get)
hit = [x for x, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _cost(plan, U, V, k, m, t_det, t_rb, t_inc, W, deploys=True, incidents=True):
    extra, first, q, inc = plan
    if first is None:
        dep = t_det + t_rb
    else:
        dep = q * first * (t_det + t_rb) + (1 - q) * (first * W + t_det + t_rb)
    return (extra + (k * dep * U * V / 1e6 if deploys else 0) + (m * inc * t_inc * U * V / 1e6 if incidents else 0))


def _argmin(d, rel=0.04):
    s = sorted(d.values())
    return min(d, key=d.get) if s[1] - s[0] >= rel * s[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(sorted(NAMES))
    for _ in range(30000):
        U = rng.choice([200_000, 500_000, 1_000_000, 3_000_000])
        V = rng.choice([0.5, 1, 2, 4])                       # ₽ за минуту недоступности одного пользователя
        k = rng.choice([2, 4, 8, 12])
        m = rng.choice([1, 2, 4, 6])
        t_det, t_rb = rng.choice([10, 20, 30]), rng.choice([5, 10, 15])
        t_inc = rng.choice([30, 60, 120])
        W = rng.choice([20, 30, 60])
        N = rng.choice([4, 8, 10])
        s = rng.choice([0.02, 0.05, 0.1])
        q_c, q_n = rng.choice([0.5, 0.6, 0.7]), rng.choice([0.7, 0.8, 0.9])
        plans = {"none": (0, None, 0.0, 1.0),
                 "canary": (rng.choice([3, 6, 10]), s, q_c, 1.0),
                 "cells": (rng.choice([15, 25, 40]), round(1 / N, 4), q_n, round(1 / N, 4)),
                 "cells_flat": (rng.choice([12, 20, 35]), None, 0.0, round(1 / N, 4))}
        if plans["cells_flat"][0] >= plans["cells"][0]:
            continue
        a = (U, V, k, m, t_det, t_rb, t_inc, W)
        full = {x: _cost(p, *a) for x, p in plans.items()}
        good = _argmin(full)
        if good != target:
            continue
        cheap = "none"
        safest = "cells"
        dep_only = _argmin({x: _cost(p, *a, incidents=False) for x, p in plans.items()})
        inc_only = _argmin({x: _cost(p, *a, deploys=False) for x, p in plans.items()})
        if None in (dep_only, inc_only):
            continue
        differ = sum(1 for t in (cheap, safest, dep_only, inc_only) if t != good)
        if differ >= (1 if good in ("none", "cells") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    order = ["none", "canary", "cells", "cells_flat"]
    cells_w = plural(N, "независимая ячейка", "независимые ячейки", "независимых ячеек")
    desc = {
        "none": "без доплаты; дефект и отказ зависимости задевают всех",
        "canary": (f"доплата {plans['canary'][0]} млн ₽ в год; новая версия сначала у {fmt_num(100 * s, 0)} % пользователей "
                   f"на {W} мин, дефект за это время замечают с вероятностью {fmt_num(100 * q_c, 0)} %; отказ "
                   f"зависимости задевает всех"),
        "cells": (f"доплата {plans['cells'][0]} млн ₽ в год; {N} {cells_w}, выкладка сначала в одну ячейку на "
                  f"{W} мин, дефект за это время замечают с вероятностью {fmt_num(100 * q_n, 0)} %; отказ зависимости "
                  f"задевает одну ячейку"),
        "cells_flat": (f"доплата {plans['cells_flat'][0]} млн ₽ в год; {N} {cells_w}, но выкладка сразу во все; "
                       f"отказ зависимости задевает одну ячейку"),
    }
    rows = "\n".join(f"• {NAMES[x].capitalize()}: {desc[x]}." for x in order)
    intro = rng.choice([
        f"Вы — главный инженер; продукт — {ctx}, ≈ {fmt_num(U, 0)} активных пользователей. Руководство просит "
        f"обосновать, тратить ли деньги на ограничение радиуса поражения.",
        f"Продукт «{ctx}» (≈ {fmt_num(U, 0)} активных пользователей) пережил за квартал два крупных сбоя, и вам как "
        f"главному инженеру нужно выбрать, во что вложиться.",
        f"На архитектурном совете «{ctx}» (≈ {fmt_num(U, 0)} активных пользователей) спорят, нужны ли ячейки и "
        f"канарейка; решение за вами как за главным инженером.",
    ])
    ask = rng.choice([
        "Какой вариант даёт минимальную ожидаемую годовую цену (доплата плюс ожидаемые потери от дефектных "
        "выкладок и отказов зависимостей)?",
        "Какой вариант выгоднее всего по ожидаемой цене за год — с учётом доплаты и ожидаемых потерь от обоих "
        "видов событий?",
    ])
    stem = (f"{intro} По статистике за год бывает ≈ {k} "
            f"дефектных выкладок и ≈ {m} отказов общей зависимости внутри развёртывания (база, кэш, очередь). Дефект "
            f"замечают через {t_det} мин после того, как он дошёл до пользователей, откат занимает {t_rb} мин; отказ "
            f"зависимости длится ≈ {t_inc} мин. Минута недоступности для одного пользователя обходится в "
            f"{fmt_num(V, 1)} ₽. Если дефект не заметили на первой волне, версия уходит ко всем.\nВарианты:\n{rows}\n\n"
            f"{ask}")
    expl = ("Ожидаемая цена = доплата + k × E[потери выкладки] + m × доля при отказе × t_inc × U × V. Итоги: " +
            "; ".join(f"{NAMES[x]} — {fmt_num(full[x], 1)} млн ₽" for x in order) +
            f". Минимум — {NAMES[good]}. Ловушки: только выкладки — {NAMES[dep_only]}, только отказы зависимостей — "
            f"{NAMES[inc_only]}, без доплаты — {NAMES['none']}, максимальная защита — {NAMES['cells']}.")
    program = PROGRAM.format(U=U, V=V, k=k, m=m, t_det=t_det, t_rb=t_rb, t_inc=t_inc, W=W,
                             plans={NAMES[x]: plans[x] for x in order})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[x] for x in order if x != good], program=program, explanation=expl,
                       params={"U": U, "V": V, "k": k, "m": m, "N": N, "W": W, "good": good, "dep_only": dep_only,
                               "inc_only": inc_only},
                       note="Ответ проверяется программой: исходы каждого события с весами вероятности.")
