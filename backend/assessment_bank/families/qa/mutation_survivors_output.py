"""qa.mutation.survivors_output — predict_output: какие мутанты переживут набор тестов.

Порог Middle/Senior. Правило «значение HIGH при x ≥ T, иначе LOW» и 2–3 теста-точки. Пять мутантов фиксированного
состава: граница `>` вместо `>=`, порог выше T, порог ниже T, одинаковые ветки, эквивалентный мутант
(`not x < T`). Нужно для каждого мутанта понять, найдётся ли тест, на котором он отличается (покрытие границы,
эквивалентные мутанты). Буквы мутантов перемешиваются; набор тестов меняется — меняется и ответ.
Ключ — независимая модель в генераторе (интервалы, где мутант отличается), сверяется с исполнением показанного кода.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import output_variant

FAMILY_ID = "qa.mutation.survivors_output"

# (контекст, функция, аргумент, HIGH, LOW, порог, шаг)
CONTEXTS = [("доставка интернет-магазина", "shipping_fee", "total", 0, 300, 3000, 100),
            ("скидка постоянного клиента", "discount_pct", "orders", 10, 0, 5, 1),
            ("тариф парковки", "hour_rate", "minutes", 150, 100, 60, 5),
            ("категория билета", "ticket_price", "age", 900, 450, 14, 1),
            ("бонус продавца", "bonus", "deals", 5000, 0, 20, 1),
            ("проверка пароля", "strength", "length", 2, 1, 12, 1)]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, x, hi, lo, t0, step = rng.choice(CONTEXTS)
    t = t0 + step * rng.randint(-2, 3)
    up = t + step * rng.randint(1, 3)
    down = t - step * rng.randint(1, 3)
    mutants = [("boundary", f"lambda {x}: {hi} if {x} > {t} else {lo}", lambda v: hi if v > t else lo),
               ("up", f"lambda {x}: {hi} if {x} >= {up} else {lo}", lambda v: hi if v >= up else lo),
               ("down", f"lambda {x}: {hi} if {x} >= {down} else {lo}", lambda v: hi if v >= down else lo),
               ("same", f"lambda {x}: {hi} if {x} >= {t} else {hi}", lambda v: hi),
               ("equiv", f"lambda {x}: {hi} if not {x} < {t} else {lo}", lambda v: hi if not v < t else lo)]
    rng.shuffle(mutants)
    names = "ABCDE"
    orig = lambda v: hi if v >= t else lo
    pool = {"far_below": max(0, down - step * rng.randint(2, 6)), "near_below": t - step,
            "at": t, "near_above": t + step, "far_above": up + step * rng.randint(1, 5)}
    picks = ["far_below", "far_above"] if rng.random() < 0.4 else []
    picks += rng.sample(["near_below", "at", "near_above", "far_below", "far_above"], 3 - len(picks) // 2)
    pts = sorted({pool[p] for p in picks})
    rng.shuffle(pts)
    tests = [(v, orig(v)) for v in pts]
    alive = sorted(names[i] for i, (_, _, f) in enumerate(mutants) if all(f(v) == want for v, want in tests))
    expected = ",".join(alive) if alive else "-"
    lines = [f"def {fn}({x}):", f"    if {x} >= {t}:", f"        return {hi}", f"    return {lo}", "", "",
             "MUTANTS = {"]
    lines += [f'    "{names[i]}": {src},' for i, (_, src, _) in enumerate(mutants)]
    lines += ["}", f"TESTS = {tests!r}", "",
              f"assert all({fn}(v) == want for v, want in TESTS)",
              "alive = sorted(n for n, f in MUTANTS.items() if all(f(v) == want for v, want in TESTS))",
              'print(",".join(alive) if alive else "-")']
    code = "\n".join(lines) + "\n"
    kinds = {names[i]: k for i, (k, _, _) in enumerate(mutants)}
    eq = next(n for n, k in kinds.items() if k == "equiv")
    stem = (f"Мутационное тестирование ({ctx}). Для `{fn}` есть набор тестов `TESTS` и пять мутантов. "
            f"Мутант «выживает», если все тесты на нём проходят. Что напечатает программа?")
    why = (f"Мутант убит, если хотя бы на одной точке теста его результат отличается от исходного. «>» вместо «>=» "
           f"отличается только в точке {t}; порог {up} — на [{t}, {up}); порог {down} — на [{down}, {t}); "
           f"одинаковые ветки — ниже {t}; мутант {eq} эквивалентен исходному и не убивается никаким тестом. "
           f"Точки тестов: {', '.join(str(v) for v in pts)}. Выжили: {expected}.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, expected=expected, context=ctx, why=why,
                          params={"kinds": kinds, "tests": tests, "threshold": t})
