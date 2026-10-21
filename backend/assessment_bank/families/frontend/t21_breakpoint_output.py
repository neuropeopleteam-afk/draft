"""frontend.layout.t21_breakpoint_output — predict_output (набор t21, порог Стажёра): цепочка if с return для
брейкпоинта адаптивной вёрстки.

Функция по ширине окна возвращает класс макета (три порога, четыре класса); программа печатает результат для трёх
ширин, одна из которых ровно на пороге, другая — рядом с порогом. Ловушки: первая сработавшая проверка завершает
функцию; строгое или нестрогое сравнение решает, куда попадает ширина на границе. Ключ — независимая модель
в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.layout.t21_breakpoint_output"

SETS = [("сетка интернет-магазина", [576, 768, 992], ["xs", "sm", "md", "lg"]),
        ("личный кабинет", [480, 768, 1024], ["phone", "tablet", "laptop", "desktop"]),
        ("дашборд аналитики", [600, 905, 1240], ["compact", "medium", "expanded", "large"]),
        ("лендинг", [640, 1024, 1280], ["mobile", "tablet", "desktop", "wide"])]
FUNCS = [("breakpoint", "width"), ("layoutFor", "w"), ("sizeClass", "vw")]
OTHER = [320, 360, 375, 390, 414, 1366, 1440, 1536, 1920]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, ts, labels = rng.choice(SETS)
    fn, arg = rng.choice(FUNCS)
    style = rng.choice(["asc_lt", "asc_le", "desc_ge", "desc_gt"])
    strict_low = style in ("asc_le", "desc_gt")  # ширина ровно на пороге уходит в нижний класс
    for _ in range(200):
        on = rng.choice(ts)
        near = rng.choice(ts) + rng.choice([-1, 1])
        other = rng.choice(OTHER)
        widths = [on, near, other]
        rng.shuffle(widths)
        if len(set(widths)) == 3:
            break
    if style.startswith("asc"):
        op = "<" if style == "asc_lt" else "<="
        body = [f"  if ({arg} {op} {t}) return \"{labels[i]}\";" for i, t in enumerate(ts)]
        body.append(f"  return \"{labels[3]}\";")
    else:
        op = ">=" if style == "desc_ge" else ">"
        body = [f"  if ({arg} {op} {ts[i]}) return \"{labels[i + 1]}\";" for i in (2, 1, 0)]
        body.append(f"  return \"{labels[0]}\";")

    def cls(w: int) -> str:
        return labels[sum(1 for t in ts if (w > t if strict_low else w >= t))]

    res = [cls(w) for w in widths]
    code = "\n".join([f"function {fn}({arg}) {{"] + body + ["}",
                                                           f"console.log({', '.join(f'{fn}({w})' for w in widths)});"])
    out = " ".join(res)
    edge = (f"ширина {on} ровно на пороге: сравнение «{op}» "
            + ("истинно" if (style in ("asc_le", "desc_ge")) else "ложно") + f", поэтому класс «{cls(on)}»")
    expl = ("Проверки идут сверху вниз, первая истинная возвращает класс и завершает функцию. "
            + "; ".join(f"{w} → {c}" for w, c in zip(widths, res)) + f". Ловушка — {edge}. "
            + f"console.log печатает результаты через пробел: «{out}».")
    stem = f"Адаптивная вёрстка ({ctx}): функция выбирает класс макета по ширине окна."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"widths": widths, "style": style}, language="javascript")
