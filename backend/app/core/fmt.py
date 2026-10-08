"""Числа в серверных текстах — как в интерфейсе (ui.tsx num/signed): десятичная запятая и минус «−».

Тексты объяснений и доказательств (θ в решении теста, в приглашении, в подборке, в профиле для ATS и в PDF) уходят
в интерфейс и наружу как готовые строки, поэтому формат задаётся здесь, а не только при показе.
"""
from __future__ import annotations


def ru_num(x, d: int = 2, sign: bool = False) -> str:
    """ru_num(1.756) → «1,76»; ru_num(-0.1, sign=True) → «−0,10»; ru_num(0.5, sign=True) → «+0,50»."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    s = f"{v:+.{d}f}" if sign else f"{v:.{d}f}"
    return s.replace(".", ",").replace("-", "−")


def theta_se(theta, se=None) -> str:
    """Оценка уровня с погрешностью: «+1,27 ± 0,49»; без погрешности — только «+1,27»."""
    return ru_num(theta, sign=True) + ("" if se is None else f" ± {ru_num(se)}")


def quoted(title: str | None) -> str:
    """Название в кавычках «…»; у факта кубка кавычки уже внутри («Кубок «Платёжный шлюз»») — без вторых."""
    return title if title and "«" in title else f"«{title or ''}»"
