"""frontend.ui.t21_badge_concat_output — predict_output (набор t21, порог Стажёра): сложение чисел со строкой
слева направо в подписях счётчика.

Два счётчика интерфейса (непрочитанные, товары в корзине и т. п.) склеиваются в подписи тремя способами:
строка + число + число (склейка цифр), число + число + строка (сначала сумма), строка + (число + число) или
строка + число − число (NaN). Ловушка — оператор `+` выполняется слева направо, и после строки он склеивает,
а не складывает; вычитание из строки даёт NaN. Ключ — независимая модель в генераторе; проверка — исполнение
показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.ui.t21_badge_concat_output"

CTX = [("мессенджер", "unread", "mentions", "Новых"), ("почтовый клиент", "inbox", "important", "Писем"),
       ("интернет-магазин", "inCart", "favorites", "Товаров"), ("лента соцсети", "likes", "reposts", "Реакций"),
       ("таск-трекер", "todo", "review", "Задач")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, a_name, b_name, label = rng.choice(CTX)
    a = rng.randint(1, 19)
    b = rng.randint(1, 19)
    third = rng.choice(["sum", "nan"])
    lines = [
        ("concat", f"console.log(\"{label}: \" + {a_name} + {b_name});", f"{label}: {a}{b}",
         f"«\"{label}: \" + {a_name}» — уже строка, второй + дописывает цифры {b}: «{label}: {a}{b}»"),
        ("sum_first", f"console.log({a_name} + {b_name} + \" шт.\");", f"{a + b} шт.",
         f"«{a_name} + {b_name}» — два числа, сначала сумма {a + b}, затем склейка: «{a + b} шт.»"),
    ]
    if third == "sum":
        lines.append(("paren", f"console.log(\"Всего: \" + ({a_name} + {b_name}));", f"Всего: {a + b}",
                      f"скобки вычисляются первыми: {a} + {b} = {a + b}, затем склейка: «Всего: {a + b}»"))
    else:
        lines.append(("nan", f"console.log(\"Разница: \" + {a_name} - {b_name});", "NaN",
                      f"«\"Разница: \" + {a_name}» даёт строку «Разница: {a}», вычитание числа из такой строки "
                      f"— NaN"))
    rng.shuffle(lines)
    decl = [f"const {a_name} = {a};", f"const {b_name} = {b};"]
    code = "\n".join(decl + [ln[1] for ln in lines])
    out = "\n".join(ln[2] for ln in lines)
    expl = ("Оператор + выполняется слева направо; если хотя бы один операнд — строка, он склеивает. "
            + "; ".join(ln[3] for ln in lines) + ".")
    stem = f"Интерфейс ({ctx}): программа собирает подписи для счётчика из двух чисел."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"a": a, "b": b, "order": [ln[0] for ln in lines]}, language="javascript")
