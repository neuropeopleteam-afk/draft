"""data_ml.metrics.t21_accuracy_count_output — predict_output (набор t21, порог Стажёра): доля верных ответов
классификатора через цикл со счётчиком.

Программа сравнивает по индексу истинные метки и предсказания модели, считает совпадения и печатает их число
и долю (accuracy). Ловушки чтения: сравнение позиция к позиции (а не «сколько каких меток»), деление «/» даёт
float (печатается, например, 0.75, а не 3/4). Длина выборки — 4, 5, 8 или 10, поэтому доля — короткая конечная
десятичная дробь. Ключ — независимый подсчёт в генераторе (дроби); проверка — исполнение показанного кода
в песочнице Python.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.metrics.t21_accuracy_count_output"

CTX = [("спам-фильтр почты", ["spam", "ham"]),
       ("модерация отзывов", ["ok", "toxic"]),
       ("тональность обращений в поддержку", ["pos", "neg", "neu"]),
       ("детектор брака на конвейере", [0, 1]),
       ("распознавание цифр на чеках", [1, 3, 4, 7, 9]),
       ("маршрутизация тикетов", ["bug", "billing", "other"])]
NAMES = [("y_true", "y_pred", "correct"), ("labels", "preds", "hits"), ("gold", "predicted", "matches"),
         ("actual", "model_out", "right")]


def _dec(fr: Fraction) -> str:
    """Точная конечная десятичная запись дроби — так её печатает float в Python (0.75, 0.5, 0.125)."""
    whole, rem = divmod(fr.numerator, fr.denominator)
    digits = ""
    while rem:
        rem *= 10
        d, rem = divmod(rem, fr.denominator)
        digits += str(d)
    return f"{whole}.{digits or '0'}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, classes = rng.choice(CTX)
    t, p, c = rng.choice(NAMES)
    for _ in range(200):
        n = rng.choice([4, 5, 8, 10])
        y_true = [rng.choice(classes) for _ in range(n)]
        y_pred = [y if rng.random() < 0.6 else rng.choice([k for k in classes if k != y]) for y in y_true]
        correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
        if 1 <= correct <= n - 1 and len(set(y_true)) >= 2:
            break
    else:
        raise RuntimeError("t21_accuracy_count: не собралась выборка")
    acc = Fraction(correct, n)
    acc_s = _dec(acc)
    assert acc_s == repr(float(acc))
    code = (f"{t} = {y_true!r}\n"
            f"{p} = {y_pred!r}\n"
            f"{c} = 0\n"
            f"for i in range(len({t})):\n"
            f"    if {t}[i] == {p}[i]:\n"
            f"        {c} += 1\n"
            f"print({c}, {c} / len({t}))")
    out = f"{correct} {acc_s}"
    pos = [str(i) for i in range(n) if y_true[i] == y_pred[i]]
    expl = (f"Сравниваются элементы с одинаковым индексом: совпадения на позициях {', '.join(pos)} — всего "
            f"{correct} из {n}. Деление «/» даёт float: {correct} / {n} = {acc_s}. Ловушка — считать метки "
            f"по отдельности (сколько каких классов), а не попарные совпадения. Вывод: «{out}».")
    stem = (f"Задача «{ctx}»: программа сравнивает истинные метки отложенной выборки с предсказаниями модели "
            f"и считает долю верных ответов.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "correct": correct}, language="python")
