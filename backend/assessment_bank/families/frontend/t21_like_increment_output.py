"""frontend.ui.t21_like_increment_output — predict_output (набор t21, порог Стажёра): постфиксный и префиксный
инкремент / декремент в счётчике интерфейса.

Счётчик (лайки, количество товара, номер слайда) меняется выражениями `x++`, `++x`, `x--`, `--x` и `x += k`;
результаты некоторых выражений сохраняются в константы и печатаются вместе с итоговым значением. Ловушка:
постфиксная форма возвращает значение ДО изменения, префиксная — после. Ключ — независимая модель в генераторе;
проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.ui.t21_like_increment_output"

CTX = [("кнопка «Нравится»", "likes", (12, 140)), ("счётчик товара в корзине", "qty", (1, 9)),
       ("карусель баннеров", "slide", (0, 6)), ("счётчик непрочитанных", "unread", (3, 60)),
       ("пошаговая форма", "step", (1, 5))]
NAMES = ["shown", "saved", "logged", "badge", "label", "value"]
OPS = {"post_inc": ("{v}++", "значение до увеличения"), "pre_inc": ("++{v}", "значение после увеличения"),
       "post_dec": ("{v}--", "значение до уменьшения"), "pre_dec": ("--{v}", "значение после уменьшения")}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, (lo, hi) = rng.choice(CTX)
    x = rng.randint(lo, hi)
    start = x
    n_assign = rng.randint(2, 3)
    kinds = [rng.choice(["post_inc", "pre_inc"])] + [rng.choice(list(OPS)) for _ in range(n_assign - 1)]
    if not any(k.startswith("post") for k in kinds):
        kinds[rng.randrange(len(kinds))] = rng.choice(["post_inc", "post_dec"])
    names = rng.sample(NAMES, n_assign)
    lines, trace, vals = [f"let {var} = {x};"], [], []
    plain_at = rng.randint(1, n_assign) if rng.random() < 0.5 else None
    plain_k = rng.choice([2, 3, 5])
    for i, (k, nm) in enumerate(zip(kinds, names)):
        if plain_at == i:
            x += plain_k
            lines.append(f"{var} += {plain_k};")
            trace.append(f"{var} += {plain_k} → {var} = {x}")
        expr, why = OPS[k]
        old = x
        x = x + 1 if k.endswith("inc") else x - 1
        v = old if k.startswith("post") else x
        vals.append(v)
        lines.append(f"const {nm} = {expr.format(v=var)};")
        trace.append(f"{nm} = {expr.format(v=var)} — {why}: {v}, {var} = {x}")
    if plain_at == n_assign:
        x += plain_k
        lines.append(f"{var} += {plain_k};")
        trace.append(f"{var} += {plain_k} → {var} = {x}")
    lines.append(f"console.log({', '.join(names)}, {var});")
    code = "\n".join(lines)
    out = " ".join(map(str, vals + [x]))
    expl = (f"Начальное значение {start}. " + "; ".join(trace) +
            f". Постфиксная форма (x++) возвращает старое значение, префиксная (++x) — новое. Вывод: «{out}».")
    stem = f"Интерфейс ({ctx}): программа меняет счётчик и запоминает промежуточные значения."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"start": start, "kinds": kinds, "plain_at": plain_at}, language="javascript")
