"""common.arch.queue_workers_mcq — mcq_concept (Lead): сколько обработчиков нужно очереди под требование к ожиданию.

Задачи приходят случайно (поток Пуассона) с интенсивностью λ в секунду, обработка занимает в среднем 1/μ
(экспоненциально), обработчиков c (модель M/M/c). Требование — среднее ожидание в очереди не больше W мс.
Нужно минимальное c. Ключ — формула Эрланга C: P(ждать) = C(c, a), a = λ/μ; Wq = C(c, a) / (cμ − λ).

Дистракторы (все — «N обработчиков»):
  * full_load — ⌈a⌉ (+1, если a целое): загрузка почти 100 %, очередь растёт без предела или ожидание огромно;
  * rule_80 — ⌈a / 0,8⌉: «держим загрузку 80 %» — при малом W мало, при большом — лишнее;
  * double — ⌈2a⌉: двукратный запас «на всякий случай» (не минимум).
Ключ проверяется исполнением: программа считает Эрланг C через рекуррентную формулу Эрланга B (иной путь,
чем прямая сумма в генераторе) и перебирает c от ⌈a⌉ вверх.
"""
from __future__ import annotations

import math

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "common.arch.queue_workers_mcq"

CONTEXTS = ["генерация PDF-отчётов", "проверка платежей на мошенничество", "распознавание документов",
            "отправка уведомлений", "пересчёт цен", "сборка превью видео"]

PROGRAM = """import math
lam, mu, W = {lam}, {mu}, {W}
a = lam / mu
def erlang_c(c):
    b = 1.0
    for k in range(1, c + 1):          # рекуррентная формула Эрланга B
        b = a * b / (k + a * b)
    rho = a / c
    return b / (1 - rho + rho * b)
c = max(1, math.floor(a) + 1)
while erlang_c(c) / (c * mu - lam) * 1000 > W:
    c += 1
opts = __OPTS__
hit = [k for k, t in opts.items() if int(t.split(" ")[0]) == c]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _erlang_c_direct(c: int, a: float) -> float:
    s = sum(a ** k / math.factorial(k) for k in range(c))
    top = a ** c / math.factorial(c) * c / (c - a)
    return top / (s + top)


def _min_c(lam: float, mu: float, W: float) -> tuple[int, float]:
    a = lam / mu
    c = math.floor(a) + 1
    while True:
        wq = _erlang_c_direct(c, a) / (c * mu - lam) * 1000
        if wq <= W:
            return c, wq
        c += 1


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    for _ in range(500):
        service_ms = rng.choice([50, 80, 120, 200, 400, 800])
        mu = 1000 / service_ms
        lam = rng.choice([20, 35, 50, 80, 120, 200])
        a = lam / mu
        W = rng.choice([1, 5, 20, 50, 200])
        if not 4 <= a <= 60:
            continue
        good, wq = _min_c(lam, mu, W)
        full = math.ceil(a) + (1 if a == int(a) else 0)
        r80 = math.ceil(a / 0.8)
        dbl = math.ceil(2 * a)
        vals = {"good": good, "full_load": full, "rule_80": r80, "double": dbl}
        if len(set(vals.values())) == 4 and good != full:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    word = lambda n: f"{n} {plural(n, 'обработчик', 'обработчика', 'обработчиков')}"
    text = {k: word(v) for k, v in vals.items()}
    stem = (f"Очередь задач «{ctx}»: задачи приходят случайно и независимо, в среднем {lam} в секунду; обработка "
            f"одной занимает в среднем {service_ms} мс (время случайное, экспоненциальное распределение). Обработчики "
            f"берут задачи из общей очереди. Требование продукта: среднее ожидание задачи в очереди — не больше "
            f"{W} мс. Какое минимальное число обработчиков его выполняет?")
    program = PROGRAM.format(lam=lam, mu=mu, W=W)
    c_wq = lambda c: _erlang_c_direct(c, a) / (c * mu - lam) * 1000 if c > a else float("inf")
    def wtxt(c):
        w = c_wq(c)
        return "очередь растёт без предела" if w == float("inf") else f"ожидание ≈ {fmt_num(w, 1)} мс"
    expl = (f"Нагрузка a = λ/μ = {lam} × {fmt_num(service_ms / 1000, 2)} = {fmt_num(a, 1)}. Модель M/M/c: среднее ожидание "
            f"Wq = C(c, a) / (cμ − λ), C — формула Эрланга C. Минимальное c с Wq ≤ {W} мс — {good} "
            f"(ожидание ≈ {fmt_num(wq, 2)} мс). Почти полная загрузка ({full}): {wtxt(full)}; правило «80 %» ({r80}): "
            f"{wtxt(r80)}; двукратный запас ({dbl}): "
            + ("выполняет требование, но не минимален." if dbl > good else f"{wtxt(dbl)} — мало при таком требовании."))
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=text["good"],
                       distractors=[text["full_load"], text["rule_80"], text["double"]], program=program,
                       explanation=expl, params={"lam": lam, "service_ms": service_ms, "W": W, "vals": vals},
                       note="Ответ проверяется программой: формула Эрланга C через рекурсию Эрланга B.")
