"""qa.retry.t21_backoff_cap_output — predict_output (набор t21, порог Стажёра): простая функция расчёта паузы
между повторами с потолком и вызов её в цикле.

Функция умножает паузу на коэффициент и обрезает её потолком (`min`); цикл `for attempt in range(1, k)` вызывает её,
сохраняя результат в той же переменной, и печатает номер попытки и паузу. Ловушки: первая напечатанная пауза — уже умноженная, правая граница range не
входит, после достижения потолка пауза не растёт. Ключ — независимая модель (min от произведения и потолка) в
генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.retry.t21_backoff_cap_output"

CTX = [("повтор упавшего API-теста", "next_delay", "delay"), ("ожидание стенда перед прогоном", "next_pause", "pause"),
       ("перезапуск нестабильного UI-теста", "backoff", "wait"), ("повтор загрузки тестовых данных", "grow", "sec")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, var = rng.choice(CTX)
    for _ in range(200):
        factor = rng.choice([2, 2, 3])
        start = rng.randint(1, 5)
        stop = rng.randint(4, 6)          # попытки 1..stop-1
        n = stop - 1
        seq = [start * factor ** i for i in range(1, n + 1)]
        cap = rng.randint(seq[0] + 1, seq[-1] - 1) if seq[-1] - seq[0] > 2 else None
        if cap is None or cap in seq:
            continue
        if sum(1 for x in seq if x > cap) < 1:
            continue
        break
    else:
        raise RuntimeError("t21_backoff_cap: не собрались параметры")
    code = (f"def {fn}({var}):\n"
            f"    return min({var} * {factor}, {cap})\n"
            f"d = {start}\n"
            f"for attempt in range(1, {stop}):\n"
            f"    d = {fn}(d)\n"
            f"    print(attempt, d)")
    rows, d = [], start
    for a in range(1, stop):
        d = min(d * factor, cap)
        rows.append((a, d))
    out = "\n".join(f"{a} {x}" for a, x in rows)
    expl = (f"range(1, {stop}) даёт попытки 1…{stop - 1} (граница {stop} не входит). Перед первым print пауза уже "
            f"умножена: {start} * {factor} = {start * factor}. Далее каждая пауза — предыдущая * {factor}, но не больше "
            f"{cap}: " + ", ".join(str(x) for _, x in rows) + f". Ловушки — умножение до печати, граница range и "
            "потолок, после которого пауза не растёт.")
    stem = (f"Сценарий: {ctx}. Функция считает следующую паузу между попытками (в секундах) с ограничением сверху, "
            "цикл печатает номер попытки и паузу.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"start": start, "factor": factor, "cap": cap, "stop": stop}, language="python")
