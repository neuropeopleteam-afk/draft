"""frontend.quality.principal_test_strategy_mcq — mcq_concept (Principal, короткое): стратегия тестов фронтенда.

За год в релизы попадают дефекты трёх видов: логика компонентов (N_l), интеграция с API (N_i) и вёрстка (N_v);
дефект, ушедший к пользователям, стоит своего (c_l, c_i, c_v тыс. ₽). Четыре стратегии (доли пойманных до релиза):
  * упор на сквозные тесты в браузере — ловят логику и интеграцию (e_l, e_i), вёрстку слабо (e_v); сопровождение
    M_e и нестабильные падения: F часов разбора на каждый из R релизов по h тыс. ₽ в час;
  * модульные и компонентные тесты — логика 0,9, интеграция и вёрстка слабо; сопровождение M_c;
  * компонентные и контрактные тесты API — логика 0,9, интеграция k_i; M_c + M_k;
  * компонентные и скриншотные тесты — логика 0,9, вёрстка k_v; M_c + M_v.
Годовая цена = сопровождение + разбор нестабильных падений + ушедшие дефекты × их цена.

Ловушки: «ловит больше всего дефектов» (по числу, без цены), «дешевле всего в сопровождении» (только компонентные) и
расчёт без разбора нестабильных падений. Верная стратегия распределена поровну по четырём и отличается хотя бы от двух
ловушек (если верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа проходит список
дефектов года, для каждой стратегии считает ожидаемую цену ушедших и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.quality.principal_test_strategy_mcq"

CONTEXTS = ["интернет-банк", "маркетплейс", "сервис бронирования отелей", "онлайн-кинотеатр", "личный кабинет оператора",
            "сервис доставки продуктов", "портал госуслуг региона", "CRM для продаж"]
NAMES = {"e2e": "упор на сквозные тесты в браузере", "comp": "модульные и компонентные тесты",
         "contract": "компонентные и контрактные тесты API", "visual": "компонентные и скриншотные тесты"}
ORDER = ["e2e", "comp", "contract", "visual"]

PROGRAM = """opts = __OPTS__
defects = {defects!r}       # вид -> (число за год, цена ушедшего, тыс. ₽)
plans = {plans!r}           # подпись -> (доли пойманных по видам, сопровождение млн ₽, разбор нестабильных млн ₽)
cost = {{}}
for label, (catch, upkeep, flaky) in plans.items():
    escaped = 0.0
    for kind, (n, price) in defects.items():
        for _ in range(n):                         # каждый дефект года
            escaped += (1 - catch[kind]) * price
    cost[label] = upkeep + flaky + escaped / 1000
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(v, rel=0.04):
    o = sorted(v.values())
    return min(v, key=v.get) if o[1] - o[0] >= rel * o[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(80000):
        N = {"l": rng.choice([20, 40, 60]), "i": rng.choice([10, 20, 40]), "v": rng.choice([20, 40, 80])}
        c = {"l": rng.choice([50, 100, 200]), "i": rng.choice([100, 200, 400]), "v": rng.choice([20, 50, 100])}
        e_l, e_i, e_v = rng.choice([0.7, 0.8]), rng.choice([0.7, 0.8, 0.9]), rng.choice([0.2, 0.3])
        k_i, k_v = rng.choice([0.6, 0.7, 0.8]), rng.choice([0.7, 0.8, 0.9])
        M_c = rng.choice([1, 2, 3])
        M_e, M_k, M_v = rng.choice([3, 5, 8]), rng.choice([1, 2, 4]), rng.choice([1, 2, 4])
        R, F, h = rng.choice([50, 100, 250]), rng.choice([2, 4, 8]), rng.choice([3, 5])
        flaky = R * F * h / 1000                            # млн ₽
        catch = {"e2e": {"l": e_l, "i": e_i, "v": e_v}, "comp": {"l": 0.9, "i": 0.2, "v": 0.2},
                 "contract": {"l": 0.9, "i": k_i, "v": 0.2}, "visual": {"l": 0.9, "i": 0.2, "v": k_v}}
        upkeep = {"e2e": M_e, "comp": M_c, "contract": M_c + M_k, "visual": M_c + M_v}
        esc = {p: sum(N[t] * (1 - catch[p][t]) * c[t] for t in N) / 1000 for p in ORDER}
        full = {p: upkeep[p] + (flaky if p == "e2e" else 0) + esc[p] for p in ORDER}
        good = _argmin(full)
        if good != target:
            continue
        no_flaky = _argmin({p: upkeep[p] + esc[p] for p in ORDER})
        caught = {p: sum(N[t] * catch[p][t] for t in N) for p in ORDER}
        most = max(caught, key=caught.get)
        if no_flaky is None or sorted(caught.values())[-1] - sorted(caught.values())[-2] < 1:
            continue
        traps = (most, "comp", no_flaky)
        if sum(t != good for t in traps) >= (1 if good in (most, "comp") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    pc = lambda v: fmt_num(100 * v, 0)
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['e2e'])}: ловит {pc(e_l)} % дефектов логики, {pc(e_i)} % интеграции, {pc(e_v)} % вёрстки; "
            f"сопровождение — {M_e} млн ₽ в год; нестабильные падения — {F} ч разбора на каждый из {R} релизов в год "
            f"по {h} тыс. ₽ в час.",
            f"• {cap(NAMES['comp'])}: 90 % логики, 20 % интеграции, 20 % вёрстки; сопровождение — {M_c} млн ₽ в год.",
            f"• {cap(NAMES['contract'])}: 90 % логики, {pc(k_i)} % интеграции, 20 % вёрстки; сопровождение — "
            f"{M_c + M_k} млн ₽ в год.",
            f"• {cap(NAMES['visual'])}: 90 % логики, 20 % интеграции, {pc(k_v)} % вёрстки; сопровождение — "
            f"{M_c + M_v} млн ₽ в год."]
    intro = rng.choice([
        f"Вы — главный инженер фронтенда; продукт — {ctx}. Нужно утвердить стратегию тестов на год.",
        f"В продукте «{ctx}» спорят, во что вкладываться в тестах фронтенда; решение — за вами как за главным "
        f"инженером фронтенда.",
        f"Для продукта «{ctx}» пересматривают тесты фронтенда; главному инженеру фронтенда нужно выбрать стратегию.",
    ])
    stem = (f"{intro} По истории за год в релизы попадает ≈ {N['l']} дефектов логики компонентов, {N['i']} — "
            f"интеграции с API и {N['v']} — вёрстки. Дефект, ушедший к пользователям, стоит в среднем: логика — "
            f"{c['l']} тыс. ₽, интеграция — {c['i']} тыс. ₽, вёрстка — {c['v']} тыс. ₽. Стратегии (доли дефектов, "
            f"пойманных до релиза):\n" + "\n".join(rows) +
            "\n\nКакая стратегия даёт минимальную годовую цену (сопровождение, разбор нестабильных падений и ушедшие "
            "дефекты)?")
    expl = (f"Цена = сопровождение + разбор нестабильных ({R} × {F} ч × {h} тыс. ₽ = {fmt_num(flaky, 1)} млн ₽, только "
            f"у сквозных) + Σ по видам: число × (1 − доля пойманных) × цена ушедшего. Итоги: " +
            "; ".join(f"{NAMES[p]} — {fmt_num(full[p], 1)} млн ₽" for p in ORDER) +
            f". Минимум — {NAMES[good]}. Больше всего дефектов ловит {NAMES[most]}; без разбора нестабильных падений "
            f"вышло бы: {NAMES[no_flaky]}.")
    defects = {"логика": (N["l"], c["l"]), "интеграция": (N["i"], c["i"]), "вёрстка": (N["v"], c["v"])}
    ru = {"l": "логика", "i": "интеграция", "v": "вёрстка"}
    plans = {NAMES[p]: ({ru[t]: catch[p][t] for t in N}, upkeep[p], flaky if p == "e2e" else 0) for p in ORDER}
    program = PROGRAM.format(defects=defects, plans=plans)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[p] for p in ORDER if p != good], program=program, explanation=expl,
                       params={"N": N, "c": c, "e": [e_l, e_i, e_v], "k_i": k_i, "k_v": k_v, "M_c": M_c, "M_e": M_e,
                               "M_k": M_k, "M_v": M_v, "R": R, "F": F, "h": h, "good": good, "most": most,
                               "no_flaky": no_flaky},
                       note="Ответ проверяется программой: проход дефектов года для каждой стратегии.")
