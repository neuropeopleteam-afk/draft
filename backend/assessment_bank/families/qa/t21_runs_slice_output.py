"""qa.runs.t21_runs_slice_output — predict_output (набор t21, порог Стажёра): индексы и срезы списка.

Список номеров сборок, на которых упал смоук-тест; программа печатает части списка для отчёта: срез [a:b], хвост
[-k:], начало [:k], срез без последнего элемента [a:-1], элемент по отрицательному индексу. Ловушки: правая граница
среза не включается, индексация с нуля, отрицательные индексы. Ключ — независимая модель среза (через диапазоны
индексов) в генераторе; проверка — исполнение показанного кода.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.runs.t21_runs_slice_output"

CTX = [("смоук-тест авторизации", "builds"), ("тест оплаты картой", "failed_builds"),
       ("тест поиска по каталогу", "red_builds"), ("тест экспорта отчёта", "broken")]


def _pick(lst, lo, hi):
    """Элементы с индексами lo..hi-1 (модель среза с нормализованными границами)."""
    return [lst[i] for i in range(len(lst)) if lo <= i < hi]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var = rng.choice(CTX)
    n = rng.randint(5, 7)
    start = rng.randint(120, 880)
    builds, cur = [], start
    for _ in range(n):
        builds.append(cur)
        cur += rng.randint(1, 6)
    ops = []
    a = rng.randint(1, n - 3)
    b = rng.randint(a + 1, n - 1)
    span = f"только индекс {a}" if b - a == 1 else f"индексы {a}…{b - 1}"
    ops.append((f"{var}[{a}:{b}]", _pick(builds, a, b), f"[{a}:{b}] — {span} (правая граница {b} не входит)"))
    k = rng.randint(2, 3)
    tail = rng.choice(["neg_tail", "head", "mid_neg"])
    if tail == "neg_tail":
        ops.append((f"{var}[-{k}:]", _pick(builds, n - k, n), f"[-{k}:] — последние {k} элемента"))
    elif tail == "head":
        ops.append((f"{var}[:{k}]", _pick(builds, 0, k), f"[:{k}] — первые {k} элемента (индексы 0…{k - 1})"))
    else:
        c = rng.randint(1, 2)
        ops.append((f"{var}[{c}:-1]", _pick(builds, c, n - 1),
                    f"[{c}:-1] — с индекса {c} до последнего, не включая его"))
    j = rng.randint(2, min(3, n - 1))
    single = rng.choice(["neg", "pos"])
    if single == "neg":
        ops.append((f"{var}[-{j}]", builds[n - j], f"[-{j}] — {j}-й с конца элемент"))
    else:
        ops.append((f"{var}[{j}]", builds[j], f"[{j}] — элемент с индексом {j} (это {j + 1}-й по счёту)"))
    rng.shuffle(ops)
    code = "\n".join([f"{var} = {builds}"] + [f"print({o[0]})" for o in ops])
    out = "\n".join(str(o[1]) for o in ops)
    expl = ("Список: " + str(builds) + ". " + "; ".join(f"{o[2]}: {o[1]}" for o in ops)
            + ". Ловушки — индексация с нуля, правая граница среза не включается, отрицательные индексы "
              "считаются с конца; срез печатается как список в квадратных скобках.")
    stem = (f"Отчёт ночного регресса: в списке — номера сборок, на которых падал {ctx}, по возрастанию. "
            "Программа выбирает части списка для сводки.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"builds": builds, "ops": [o[0] for o in ops]}, language="python")
