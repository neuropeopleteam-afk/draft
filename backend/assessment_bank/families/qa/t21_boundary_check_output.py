"""qa.boundary.t21_boundary_check_output — predict_output (набор t21, порог Стажёра): функция валидации с if и
сравнениями на граничных значениях.

Поле принимает значения из диапазона; функция возвращает "reject" вне диапазона и "ok" внутри. В части вариантов одна
из границ проверяется строгим/нестрогим сравнением «не в ту сторону» (`<=` вместо `<`, `>=` вместо `>`), и граничное
значение отклоняется. Программа прогоняет функцию на значениях у границ (классические тест-кейсы граничных значений).
Ключ — независимая модель (интервал допустимых значений) в генераторе; проверка — исполнение показанного кода.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.boundary.t21_boundary_check_output"

# (контекст, имя функции, аргумент, варианты нижней границы, варианты верхней)
FIELDS = [("количество товаров в корзине", "check_qty", "qty", [1, 1, 2], [20, 50, 99]),
          ("возраст при регистрации", "check_age", "age", [14, 16, 18], [65, 80, 99]),
          ("длина пароля", "check_length", "length", [6, 8, 10], [32, 64, 72]),
          ("число гостей в бронировании", "check_guests", "guests", [1, 2], [6, 8, 10, 12]),
          ("сумма перевода в тысячах", "check_amount", "amount", [1, 5, 10], [100, 300, 500])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, arg, los, his = rng.choice(FIELDS)
    lo, hi = rng.choice(los), rng.choice(his)
    mode = rng.choice(["inclusive", "lo_strict", "hi_strict"])
    lo_op = "<=" if mode == "lo_strict" else "<"
    hi_op = ">=" if mode == "hi_strict" else ">"
    for _ in range(100):
        k = rng.randint(4, 5)
        vals = sorted(rng.sample([lo - 1, lo, lo + 1, hi - 1, hi, hi + 1], k))
        needs = {"inclusive": [lo, hi], "lo_strict": [lo], "hi_strict": [hi]}[mode]
        if all(x in vals for x in needs) and (lo - 1 in vals or hi + 1 in vals):
            break
    ok_lo = lo + 1 if mode == "lo_strict" else lo
    ok_hi = hi - 1 if mode == "hi_strict" else hi
    res = ["ok" if ok_lo <= x <= ok_hi else "reject" for x in vals]
    code = (f"def {fn}({arg}):\n"
            f"    if {arg} {lo_op} {lo} or {arg} {hi_op} {hi}:\n"
            f"        return \"reject\"\n"
            f"    return \"ok\"\n"
            f"for v in {vals}:\n"
            f"    print(v, {fn}(v))")
    out = "\n".join(f"{x} {r}" for x, r in zip(vals, res))
    note = {"inclusive": f"обе границы включены: {lo} и {hi} проходят",
            "lo_strict": f"условие {arg} <= {lo} отклоняет и саму нижнюю границу {lo}",
            "hi_strict": f"условие {arg} >= {hi} отклоняет и саму верхнюю границу {hi}"}[mode]
    expl = (f"Функция возвращает \"ok\" только для {ok_lo} ≤ {arg} ≤ {ok_hi}: {note}. По значениям: "
            + ", ".join(f"{x} → {r}" for x, r in zip(vals, res))
            + ". Ловушка — строгое или нестрогое сравнение на самой границе.")
    stem = (f"Проверка граничных значений: поле «{ctx}» должно принимать значения от {lo} до {hi} включительно. "
            "Программа прогоняет функцию валидации на значениях у границ.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"lo": lo, "hi": hi, "mode": mode, "values": vals}, language="python")
