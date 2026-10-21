"""frontend.ui.t21_progress_while_output — predict_output (набор t21, порог Стажёра): цикл while со счётчиком
кадров анимации.

Значение (ширина полосы, прозрачность, прокрутка, угол) растёт на шаг за кадр, пока не дойдёт до предела;
программа печатает число кадров и итоговое значение. Ловушки: значение «перелетает» предел на последнем шаге;
при `<=` и точном попадании в предел выполняется ещё один кадр. Ключ — независимая модель в генераторе;
проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.ui.t21_progress_while_output"

# контекст, переменная, варианты старта, варианты шага, варианты предела
CTX = [("полоса загрузки", "width", [0, 5, 10, 15, 20], [7, 8, 9, 12, 15, 16, 18, 20, 25], [100]),
       ("плавное появление окна", "opacity", [0, 10, 20], [6, 8, 12, 14, 16, 20, 30], [100]),
       ("прокрутка к якорю", "scrollY", [0, 40, 80, 120], [35, 45, 60, 70, 75, 90, 110], [400, 480, 600]),
       ("вращение спиннера", "angle", [0, 15, 30], [25, 40, 45, 50, 70, 80, 90], [360]),
       ("анимация счётчика", "shown", [0, 3, 5], [11, 13, 17, 19, 23, 25], [100, 150, 200])]
COUNTERS = ["frames", "ticks", "steps", "count", "moves"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, starts, steps, limits = rng.choice(CTX)
    cnt = rng.choice(COUNTERS)
    for _ in range(200):
        start, limit = rng.choice(starts), rng.choice(limits)
        exact = [s for s in steps if (limit - start) % s == 0]
        step = rng.choice(exact) if exact and rng.random() < 0.45 else rng.choice(steps)
        op = rng.choice(["<", "<="])
        x, k = start, 0
        while (x < limit) if op == "<" else (x <= limit):
            x += step
            k += 1
        if 3 <= k <= 14:
            break
    else:
        raise RuntimeError("t21_progress_while: не подобраны шаг и предел")
    code = "\n".join([f"let {var} = {start};", f"let {cnt} = 0;", f"while ({var} {op} {limit}) {{",
                      f"  {var} += {step};", f"  {cnt}++;", "}", f"console.log({cnt}, {var});"])
    out = f"{k} {x}"
    seq = [start + step * i for i in range(1, k + 1)]
    shown = ", ".join(map(str, seq)) if k <= 8 else ", ".join(map(str, seq[:3])) + ", …, " + ", ".join(
        map(str, seq[-2:]))
    if x == limit:
        why = f"на {k}-м кадре значение ровно {limit}: условие «{var} < {limit}» ложно, цикл останавливается"
    elif op == "<=" and x - step == limit:
        why = (f"значение {limit} ещё проходит условие «{var} <= {limit}», поэтому выполняется ещё один кадр "
               f"и значение становится {x}")
    else:
        why = f"последний шаг перескакивает предел: {x - step} + {step} = {x}, после чего условие ложно"
    expl = (f"Значения после каждого кадра: {shown}. Ловушка — {why}. "
            f"console.log печатает счётчик и значение через пробел: «{out}».")
    stem = (f"Анимация ({ctx}): на каждом кадре значение увеличивается на шаг, пока выполняется условие цикла; "
            f"программа считает кадры.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"start": start, "step": step, "limit": limit, "op": op}, language="javascript")
