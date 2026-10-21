"""data_ml.mlops.lp3_retrain_period_output — predict_output: период переобучения модели с минимальной ценой.

После переобучения качество модели падает на d п.п. в неделю (дрейф данных), каждый п.п. потери стоит V тыс. ₽
в неделю, переобучение с разметкой — C тыс. ₽. При периоде T недель средние потери в неделю =
(C + V · d · (0 + 1 + … + (T − 1))) / T. Нужен целый T от 1 до 26 с минимальной средней ценой (при равенстве —
меньший T). Ловушки: формула √(2C / (V·d)) с округлением (непрерывное приближение даёт другой целый ответ);
считать потерю в неделю T как d · T; переобучать «раз в месяц по привычке». Ответ — целое число недель.
"""
from __future__ import annotations

import math

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.mlops.lp3_retrain_period_output"
MODELS = ["рекомендации товаров", "скоринг заявок", "прогноз спроса", "антифрод", "ранжирование поиска"]

CALC = r'''
import re
v = {}
for l in DATA.splitlines():
    m = re.match(r"^([^:]+):\s*([\d,]+)", l)
    if m:
        v[m.group(1).strip()] = float(m.group(2).replace(",", "."))
C, V, d = v["переобучение, тыс. ₽"], v["потеря 1 п.п. в неделю, тыс. ₽"], v["падение качества, п.п. в неделю"]
best = min(range(1, 27), key=lambda T: ((C + V * d * T * (T - 1) / 2) / T, T))
print(best)
'''


def _n(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    model = rng.choice(MODELS)
    for _ in range(3000):
        C = rng.randint(6, 70) * 10
        V = rng.randint(4, 35)
        d = rng.choice([0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0])
        f = lambda T: (C + V * d * T * (T - 1) / 2) / T  # noqa: E731
        good = min(range(1, 27), key=lambda T: (f(T), T))
        if good in (1, 26):
            continue
        approx = round(math.sqrt(2 * C / (V * d)))
        lin = min(range(1, 27), key=lambda T: ((C + V * d * T * (T + 1) / 2) / T, T))
        if good == approx and rng.random() < 0.75:
            continue
        if abs(f(good) - min(f(T) for T in range(1, 27) if T != good)) < 0.05:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"переобучение, тыс. ₽: {_n(C)}", f"потеря 1 п.п. в неделю, тыс. ₽: {_n(V)}",
                       f"падение качества, п.п. в неделю: {_n(d)}"])
    stem = (f"Модель «{model}» после переобучения теряет качество из-за дрейфа данных равномерно (блок ниже): в первую "
            "неделю после переобучения потеря 0, во вторую — одно падение, в третью — два и т. д. Переобучение с "
            "разметкой стоит фиксированную сумму. Каждые сколько недель (целое от 1 до 26) переобучать, чтобы средняя "
            "цена в неделю (переобучение плюс потери) была минимальной? При равной цене — реже не надо, берите "
            "меньший период. Ответ — целое число недель.")
    expl = (f"Средняя цена в неделю при периоде T: (C + V · d · T(T − 1)/2) / T, C = {_n(C)}, V · d = {_n(V * d)}. "
            f"Перебор T = 1…26: минимум при T = {good}. Непрерывное приближение √(2C/(V·d)) ≈ "
            f"{_n(round(math.sqrt(2 * C / (V * d)), 2))} → {approx}; если считать потерю с первой недели — {lin}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=model,
                         accept=num_accept(good, ("недель", "недели", "неделя")), params={"C": C, "V": V, "d": d})
