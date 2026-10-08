"""Числа в серверных текстах — как в интерфейсе (ui.tsx num/signed): десятичная запятая и минус «−».

Тексты объяснений и доказательств (θ в решении теста, в приглашении, в подборке, в профиле для ATS и в PDF) уходят
в интерфейс и наружу как готовые строки, поэтому формат задаётся здесь, а не только при показе.

Округление — одно на весь продукт (Ф3, 08.10): «половина — от нуля» по десятичной записи числа, как
``Intl.NumberFormat`` (``toLocaleString``) в ui.tsx num/signed. Обычный ``f"{0.715:.2f}"`` даёт «0.71» (двоичное
0,71499…), а интерфейс — «0,72»: из-за этого одна и та же погрешность выглядела «± 0,72» на экране итога и «± 0,71»
в подборке. θ и погрешность итога теста округляются один раз — ``theta_round`` в движке (bank_engine, мини-тест,
заглушка) — и дальше везде показываются одинаково: «+1,40 ± 0,72».
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import math

THETA_DIGITS = 2  # θ и погрешность итога теста — два знака после запятой (хранение и показ)


def round_half(x, d: int = 2) -> float | None:
    """round_half(0.715) → 0.72, round_half(-1.005) → −1.01 (как num в интерфейсе); None/NaN/inf → None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return float(Decimal(repr(v)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def theta_round(theta, se) -> tuple[float | None, float | None]:
    """Единственное место округления θ и погрешности итога теста (движки пишут их в сессию, факты и паспорт)."""
    return round_half(theta, THETA_DIGITS), round_half(se, THETA_DIGITS)


def ru_num(x, d: int = 2, sign: bool = False) -> str:
    """ru_num(1.756) → «1,76»; ru_num(-0.1, sign=True) → «−0,10»; ru_num(0.5, sign=True) → «+0,50».
    Знак «+» — только у положительных (как signed в ui.tsx); ноль — «0,00»."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    q = Decimal(repr(v)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    s = f"{q:.{d}f}"
    return (("+" if sign and v > 0 else "") + s).replace(".", ",").replace("-", "−")


def theta_se(theta, se=None) -> str:
    """Оценка уровня с погрешностью: «+1,27 ± 0,49»; без погрешности — только «+1,27»."""
    return ru_num(theta, sign=True) + ("" if se is None else f" ± {ru_num(se)}")


def quoted(title: str | None) -> str:
    """Название в кавычках «…»; у факта кубка кавычки уже внутри («Кубок «Платёжный шлюз»») — без вторых."""
    return title if title and "«" in title else f"«{title or ''}»"
