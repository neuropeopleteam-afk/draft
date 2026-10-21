"""frontend.layout.t21_grid_width_output — predict_output (набор t21, порог Стажёра): приоритет операций в формуле
ширины ряда карточек.

Программа считает ширину ряда: поля по краям, ширина карточек и промежутки между ними; результат печатается
с единицей «px». Ловушка — приоритет операций: в половине вариантов промежутки записаны как `gap * cards - 1`
(сначала умножение, потом вычитается единица, а не один промежуток), в остальных — со скобками или через
(ширина + промежуток) × число − промежуток. Ключ — независимое вычисление в генераторе; проверка — исполнение
показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.layout.t21_grid_width_output"

CTX = [("лента товаров", "cards", "cardWidth"), ("галерея фотографий", "photos", "photoWidth"),
       ("доска задач", "columns", "columnWidth"), ("витрина тарифов", "plans", "planWidth"),
       ("подборка видео", "tiles", "tileWidth")]
GAPS = ["gap", "gutter", "spacing"]
PADS = ["padding", "inset", "sidePad"]
RESULT = ["rowWidth", "total", "width"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, n_name, w_name = rng.choice(CTX)
    g_name, p_name, r_name = rng.choice(GAPS), rng.choice(PADS), rng.choice(RESULT)
    n = rng.randint(3, 6)
    w = rng.choice(range(160, 321, 20))
    g = rng.choice([8, 12, 16, 20, 24])
    p = rng.choice([12, 16, 20, 24, 32])
    form = rng.choice(["trap", "trap", "trap_rev", "paren", "factor"])
    if form == "trap":
        expr = f"{p_name} * 2 + {n_name} * {w_name} + {g_name} * {n_name} - 1"
        val = p * 2 + n * w + g * n - 1
        trace = (f"{p_name} * 2 = {p * 2}, {n_name} * {w_name} = {n * w}, {g_name} * {n_name} = {g * n}; "
                 f"затем слева направо: {p * 2} + {n * w} + {g * n} − 1 = {val}. Ловушка: «− 1» относится ко всей "
                 f"сумме, а не к числу промежутков — умножение выполняется раньше вычитания, и вычитается единица, "
                 f"а не один промежуток")
    elif form == "trap_rev":
        expr = f"{n_name} * {w_name} + {g_name} * {n_name} - 1 + {p_name} * 2"
        val = n * w + g * n - 1 + p * 2
        trace = (f"{n_name} * {w_name} = {n * w}, {g_name} * {n_name} = {g * n}, {p_name} * 2 = {p * 2}; "
                 f"затем слева направо: {n * w} + {g * n} − 1 + {p * 2} = {val}. Ловушка: умножение выполняется "
                 f"раньше вычитания, поэтому вычитается единица, а не один промежуток")
    elif form == "paren":
        expr = f"{p_name} * 2 + {n_name} * {w_name} + {g_name} * ({n_name} - 1)"
        val = p * 2 + n * w + g * (n - 1)
        trace = (f"{p_name} * 2 = {p * 2}, {n_name} * {w_name} = {n * w}, скобки: {n_name} − 1 = {n - 1}, "
                 f"{g_name} * {n - 1} = {g * (n - 1)}; сумма {p * 2} + {n * w} + {g * (n - 1)} = {val}")
    else:
        expr = f"({w_name} + {g_name}) * {n_name} - {g_name} + {p_name} * 2"
        val = (w + g) * n - g + p * 2
        trace = (f"скобки: {w} + {g} = {w + g}, умножить на {n}: {(w + g) * n}; {p_name} * 2 = {p * 2}; "
                 f"слева направо: {(w + g) * n} − {g} + {p * 2} = {val}")
    decl = [f"const {n_name} = {n};", f"const {w_name} = {w};", f"const {g_name} = {g};", f"const {p_name} = {p};"]
    rng.shuffle(decl)
    code = "\n".join(decl + [f"const {r_name} = {expr};", f"console.log({r_name} + \"px\");"])
    out = f"{val}px"
    expl = (f"Скобки и умножения выполняются раньше сложения и вычитания, а те — слева направо: {trace}. "
            f"Число складывается со строкой «px» — получается строка «{out}».")
    stem = f"Вёрстка ({ctx}): программа считает ширину ряда карточек с промежутками и полями по краям."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "w": w, "gap": g, "pad": p, "form": form}, language="javascript")
