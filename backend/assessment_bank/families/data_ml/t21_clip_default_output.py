"""data_ml.features.t21_clip_default_output — predict_output (набор t21, порог Стажёра): функция обрезки признака
по границам с верхней границей по умолчанию.

Функция clip(x, lo, hi=<по умолчанию>) возвращает lo, если x меньше lo, hi — если больше hi, иначе само x.
Программа вызывает её трижды: дважды без третьего аргумента (берётся значение по умолчанию) и один раз с явной
верхней границей. Ловушки чтения: какая граница возвращается, значение параметра по умолчанию, ранний return.
Ключ — независимый расчёт в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.features.t21_clip_default_output"

# (сюжет, имя функции, верхняя граница по умолчанию, диапазон «сырых» значений)
CTX = [("яркость пикселей после аугментации", "clip_pixel", 255, (-40, 320)),
       ("процент заполнения анкеты", "clip_pct", 100, (-20, 140)),
       ("оценка товара по шкале до 10", "clip_score", 10, (-3, 15)),
       ("возраст клиента из анкеты", "clip_age", 99, (-5, 140)),
       ("число покупок за месяц", "clip_orders", 50, (-5, 90))]


def _clip(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else hi if x > hi else x


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, hi_def, (rlo, rhi) = rng.choice(CTX)
    for _ in range(500):
        lo1 = rng.choice([0, 0, 1])
        lo2 = rng.randint(1, hi_def // 4)
        hi2 = rng.randint(hi_def // 2, hi_def - 1)
        lo3 = rng.choice([0, lo2])
        xs = [rng.randint(rlo, rhi) for _ in range(3)]
        calls = [(xs[0], lo1, None), (xs[1], lo2, hi2), (xs[2], lo3, None)]
        res = [_clip(x, lo, hi_def if hi is None else hi) for x, lo, hi in calls]
        kinds = {("low" if x < lo else "high" if x > (hi_def if hi is None else hi) else "mid")
                 for x, lo, hi in calls}
        # нужна хотя бы одна обрезка сверху по умолчанию и разные исходы
        if len(kinds) >= 2 and "high" in kinds and any(h is None and x > hi_def for x, _, h in calls):
            break
    else:
        raise RuntimeError("t21_clip_default: не собрались вызовы")
    order = list(range(3))
    rng.shuffle(order)
    calls = [calls[i] for i in order]
    res = [res[i] for i in order]
    args = [f"{fn}({x}, {lo})" if hi is None else f"{fn}({x}, {lo}, {hi})" for x, lo, hi in calls]
    code = (f"def {fn}(x, lo, hi={hi_def}):\n"
            "    if x < lo:\n"
            "        return lo\n"
            "    if x > hi:\n"
            "        return hi\n"
            "    return x\n"
            f"print({', '.join(args)})")
    out = " ".join(map(str, res))
    steps = []
    for (x, lo, hi), r in zip(calls, res):
        h = hi_def if hi is None else hi
        src = f"hi по умолчанию = {hi_def}" if hi is None else f"hi = {hi}"
        why = (f"{x} < {lo} → lo" if x < lo else f"{x} > {h} → hi" if x > h else f"{lo} ≤ {x} ≤ {h} → x")
        steps.append(f"{fn}({x}, …): {src}, {why} = {r}")
    expl = ("; ".join(steps) + f". Ловушка — забыть значение hi по умолчанию или вернуть x вместо границы. "
            f"Вывод: «{out}».")
    stem = (f"Предобработка признака «{ctx}»: функция обрезает выбросы по нижней и верхней границам, программа "
            f"применяет её к трём значениям.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"calls": [list(c) for c in calls], "hi_default": hi_def}, language="python")
