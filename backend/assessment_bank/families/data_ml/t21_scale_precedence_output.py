"""data_ml.features.t21_scale_precedence_output — predict_output (набор t21, порог Стажёра): нормировка признака
двумя записями формулы — со скобками и без них.

Программа считает стандартизованное значение признака (x − mean) / std или масштаб к [0, 1] (x − lo) / (hi − lo)
и рядом ту же формулу без скобок вокруг числителя. Ловушки чтения: приоритет операций — деление выполняется раньше
вычитания (x − mean / std = x − (mean / std)), и «/» всегда даёт float (печатается 2.0, а не 2). Числа подобраны так,
что оба результата — короткие конечные десятичные дроби. Ключ — независимый расчёт дробями в генераторе; проверка —
исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.features.t21_scale_precedence_output"

CTX = [("возраст клиента", "age", (18, 70)), ("сумма чека", "amount", (100, 900)),
       ("длительность сессии в минутах", "minutes", (2, 60)), ("число заказов за месяц", "orders", (1, 40)),
       ("температура датчика", "temp", (20, 90))]


def _dec(fr: Fraction) -> str:
    """Точная конечная десятичная запись дроби — так её печатает float в Python (2.0, -1.25, 0.375)."""
    sign = "-" if fr < 0 else ""
    fr = abs(fr)
    whole, rem = divmod(fr.numerator, fr.denominator)
    digits = ""
    while rem:
        rem *= 10
        d, rem = divmod(rem, fr.denominator)
        digits += str(d)
    return f"{sign}{whole}.{digits or '0'}"


def _short(fr: Fraction) -> bool:
    s = _dec(fr)
    return len(s.split(".")[1]) <= 3 and s == repr(float(fr))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, (lo_v, hi_v) = rng.choice(CTX)
    kind = rng.choice(["z", "minmax"])
    for _ in range(500):
        if kind == "z":
            std = rng.choice([2, 4, 5, 8, 10])
            mean = rng.randint(lo_v, hi_v)
            x = rng.randint(lo_v, hi_v)
            good = Fraction(x - mean, std)
            other = x - Fraction(mean, std)
            names = ("mean", mean, "std", std)
        else:
            lo = rng.randint(lo_v, (lo_v + hi_v) // 2)
            span = rng.choice([s for s in (4, 5, 8, 10, 20, 25, 40, 50, 80, 100) if lo + s <= hi_v * 2])
            hi = lo + span
            x = rng.randint(lo, hi)
            good = Fraction(x - lo, hi - lo)
            other = x - Fraction(lo, hi - lo)
            names = ("lo", lo, "hi", hi)
        if x == names[1] or good == other or not (_short(good) and _short(other)):
            continue
        break
    else:
        raise RuntimeError("t21_scale_precedence: не собрались числа")
    a_name, a_val, b_name, b_val = names
    r1, r2 = ("z1", "z2") if kind == "z" else ("s1", "s2")
    if kind == "z":
        f1, f2 = f"(x - mean) / std", f"x - mean / std"
        trace = (f"{r1} = ({x} − {mean}) / {std} = {_dec(good)}; в {r2} сначала деление: mean / std = "
                 f"{_dec(Fraction(mean, std))}, затем {x} − {_dec(Fraction(mean, std))} = {_dec(other)}")
    else:
        f1, f2 = f"(x - lo) / (hi - lo)", f"x - lo / (hi - lo)"
        trace = (f"{r1} = ({x} − {lo}) / ({hi} − {lo}) = {_dec(good)}; в {r2} сначала деление: lo / (hi − lo) = "
                 f"{_dec(Fraction(lo, hi - lo))}, затем {x} − {_dec(Fraction(lo, hi - lo))} = {_dec(other)}")
    code = (f"x = {x}\n"
            f"{a_name} = {a_val}\n"
            f"{b_name} = {b_val}\n"
            f"{r1} = {f1}\n"
            f"{r2} = {f2}\n"
            f"print({r1}, {r2})")
    out = f"{_dec(good)} {_dec(other)}"
    tail = (" «/» всегда даёт float, поэтому целый результат печатается с «.0»."
            if good.denominator == 1 or other.denominator == 1 else "")
    expl = f"{trace}. Деление выполняется раньше вычитания.{tail} Вывод: «{out}»."
    what = "стандартизует" if kind == "z" else "масштабирует к отрезку [0, 1]"
    stem = (f"Признак «{ctx}» ({var}): программа {what} одно значение признака, записав формулу двумя способами.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"kind": kind, "x": x, a_name: a_val, b_name: b_val}, language="python")
