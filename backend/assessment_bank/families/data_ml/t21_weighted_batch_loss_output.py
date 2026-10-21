"""data_ml.batches.t21_weighted_batch_loss_output — predict_output (набор t21, порог Стажёра): средняя потеря
за эпоху по батчам разного размера — цикл с двумя накопителями.

Программа проходит по парам (размер батча, средняя потеря на батче), накапливает сумму size * loss и число
примеров и печатает число примеров и среднюю потерю на пример. Последний батч неполный, поэтому ответ — взвешенное
среднее, а не среднее арифметическое потерь батчей. Потери — кратные 1/8 (точно представимы в float), числа
подобраны так, что результат — короткая конечная десятичная дробь. Ключ — независимый расчёт дробями в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.batches.t21_weighted_batch_loss_output"

CTX = ["классификатор изображений товаров", "модель оттока клиентов", "ранжирование поисковой выдачи",
       "распознавание речи в колл-центре", "прогноз спроса на складе"]
NAMES = [("batches", "total", "count"), ("epoch_log", "loss_sum", "seen"), ("history", "acc", "n"),
         ("stats", "weighted", "examples")]


def _dec(fr: Fraction) -> str:
    """Точная конечная десятичная запись дроби — так её печатает float в Python (0.5625, 1.0)."""
    whole, rem = divmod(fr.numerator, fr.denominator)
    digits = ""
    while rem:
        rem *= 10
        d, rem = divmod(rem, fr.denominator)
        digits += str(d)
    return f"{whole}.{digits or '0'}"


def _terminating(fr: Fraction) -> bool:
    d = fr.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    bv, tv, cv = rng.choice(NAMES)
    for _ in range(1000):
        bs = rng.choice([8, 16, 32, 64])
        k = rng.randint(2, 3)
        last = rng.choice([s for s in range(4, bs, 4)])
        sizes = [bs] * k + [last]
        eighths = [rng.randint(2, 14) for _ in sizes]
        total = sum(s * Fraction(e, 8) for s, e in zip(sizes, eighths))
        cnt = sum(sizes)
        mean = total / cnt
        simple = sum(Fraction(e, 8) for e in eighths) / len(sizes)
        s = _dec(mean) if _terminating(mean) else ""
        if not s or len(s.split(".")[1]) > 4 or s != repr(float(mean)) or mean == simple:
            continue
        break
    else:
        raise RuntimeError("t21_weighted_batch_loss: не собрались батчи")
    pairs = [(sz, float(Fraction(e, 8))) for sz, e in zip(sizes, eighths)]
    code = (f"{bv} = {pairs}\n"
            f"{tv} = 0\n"
            f"{cv} = 0\n"
            f"for size, loss in {bv}:\n"
            f"    {tv} += size * loss\n"
            f"    {cv} += size\n"
            f"print({cv}, {tv} / {cv})")
    out = f"{cnt} {s}"
    parts = " + ".join(f"{sz}·{l}" for sz, l in pairs)
    expl = (f"Сумма потерь по примерам: {parts} = {_dec(total)}; примеров {cnt}. Среднее на пример: "
            f"{_dec(total)} / {cnt} = {s}. Ловушка — взять среднее арифметическое потерь батчей "
            f"(здесь было бы {_dec(simple) if _terminating(simple) else '≈' + str(round(float(simple), 4))}): "
            f"неполный последний батч весит меньше. Вывод: «{out}».")
    stem = (f"Обучение модели «{ctx}»: в журнале эпохи для каждого батча записаны его размер и средняя потеря; "
            f"программа считает среднюю потерю за эпоху.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"sizes": sizes, "loss_eighths": eighths}, language="python")
