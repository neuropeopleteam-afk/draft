"""mobile.ui.t21_dp_px_output — predict_output (набор t21, порог Стажёра): перевод размеров макета из dp в
пиксели экрана — приоритет умножения над сложением.

Программа на JavaScript (логика React Native-экрана) считает ширину элемента в физических пикселях для экрана
заданной плотности: в первом выражении на плотность умножается только размер элемента (скобок нет), во втором —
вся сумма в скобках. Ловушка чтения: `*` выполняется раньше `+`, поэтому отступы в первом выражении остаются в dp.
Ключ — независимый расчёт в генераторе (целая арифметика в четвертях); проверка — исполнение показанного кода в
песочнице Node.js.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.ui.t21_dp_px_output"

# (сюжет, имя размера элемента, имя отступа)
CTX = [("карточка товара в каталоге", "imageDp", "paddingDp"),
       ("строка списка чатов", "avatarDp", "gapDp"),
       ("кнопка оплаты на экране корзины", "iconDp", "marginDp"),
       ("плитка на главном экране", "tileDp", "spacingDp"),
       ("превью видео в ленте", "thumbDp", "insetDp")]
DENSITIES = ["1.5", "2", "2.5", "2.75", "3", "3.5", "4"]
SIZES = [16, 20, 24, 28, 32, 36, 40, 44, 48, 56, 64]
PADS = [4, 6, 8, 10, 12, 14, 16]


def _fmt(x: Fraction) -> str:
    """Как Node печатает число: целое — без точки, иначе короткая десятичная запись."""
    if x.denominator == 1:
        return str(x.numerator)
    s = f"{float(x):.4f}".rstrip("0")
    return s


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, size_name, pad_name = rng.choice(CTX)
    dens_s = rng.choice(DENSITIES)
    dens = Fraction(dens_s)
    size = rng.choice(SIZES)
    pad = rng.choice(PADS)
    res = rng.choice(["rowPx", "widthPx", "totalPx"])
    # форма выражения без скобок: в каждой на плотность умножается только размер элемента
    shape = rng.choice(["double_first", "double_last", "sides"])
    if shape == "double_first":
        expr1 = f"{pad_name} * 2 + {size_name} * density"
        expr2 = f"({pad_name} * 2 + {size_name}) * density"
        trace1 = f"{pad}·2 + {size}·{dens_s.replace('.', ',')} = {pad * 2} + {_fmt(size * dens)}"
    elif shape == "double_last":
        expr1 = f"{size_name} * density + {pad_name} * 2"
        expr2 = f"({size_name} + {pad_name} * 2) * density"
        trace1 = f"{size}·{dens_s.replace('.', ',')} + {pad}·2 = {_fmt(size * dens)} + {pad * 2}"
    else:
        expr1 = f"{pad_name} + {size_name} * density + {pad_name}"
        expr2 = f"({pad_name} + {size_name} + {pad_name}) * density"
        trace1 = f"{pad} + {size}·{dens_s.replace('.', ',')} + {pad} = {pad} + {_fmt(size * dens)} + {pad}"
    v1 = pad * 2 + size * dens
    v2 = (pad * 2 + size) * dens
    decl = [f"const density = {dens_s};", f"const {size_name} = {size};", f"const {pad_name} = {pad};"]
    if rng.random() < 0.5:
        decl[1], decl[2] = decl[2], decl[1]
    code = "\n".join(decl + [f"const {res} = {expr1};",
                             f"const fixedPx = {expr2};",
                             f"console.log({res}, fixedPx);"])
    out = f"{_fmt(v1)} {_fmt(v2)}"
    expl = (f"Умножение выполняется раньше сложения: в {res} на плотность умножается только {size_name}: "
            f"{trace1} = {_fmt(v1)} (отступы остались в dp). Во втором выражении скобки: "
            f"{pad * 2 + size}·{dens_s.replace('.', ',')} = {_fmt(v2)}. console.log печатает через пробел: "
            f"«{out}».")
    stem = (f"React Native-экран, {ctx}: программа переводит размеры макета из dp в физические пиксели для "
            f"экрана с плотностью {dens_s.replace('.', ',')}.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"density": dens_s, "size": size, "pad": pad, "shape": shape},
                          language="javascript")
