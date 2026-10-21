"""backend.http.t21_backoff_default_arg_output — predict_output (набор t21, порог Стажёра): простая функция
с параметром по умолчанию.

Функция задержки перед повтором запроса: `base * 2 ** attempt`, base по умолчанию задан в сигнатуре. Вызовы:
с одним аргументом (берётся base по умолчанию), с двумя позиционными и с именованным base. Ловушки: 2 ** 0 = 1,
возведение в степень выполняется раньше умножения, именованный аргумент заменяет значение по умолчанию.
Ключ — независимый расчёт в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.http.t21_backoff_default_arg_output"

CTX = [("платёжный шлюз", "payments"), ("рассылка вебхуков", "webhooks"),
       ("синхронизация остатков", "stock"), ("сервис доставки", "delivery"),
       ("загрузка файлов", "uploads"), ("сервис уведомлений", "notify")]
FUNCS = ["delay_ms", "backoff_ms", "retry_delay", "wait_ms"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    fn = rng.choice(FUNCS)
    base = rng.choice([50, 100, 150, 200, 250, 300])
    other = rng.choice([b for b in (10, 20, 25, 40, 50, 75) if b != base])
    calls = []  # (текст вызова, attempt, base)
    a1 = rng.choice([0, 0, 1])
    calls.append((f"{fn}({a1})", a1, base))
    a2 = rng.randint(2, 4)
    calls.append((f"{fn}({a2})", a2, base))
    a3 = rng.randint(1, 4)
    if rng.random() < 0.5:
        calls.append((f"{fn}({a3}, {other})", a3, other))
    else:
        calls.append((f"{fn}({a3}, base={other})", a3, other))
    rng.shuffle(calls)
    code = (f"def {fn}(attempt, base={base}):\n"
            "    return base * 2 ** attempt\n"
            + "\n".join(f"print({c})" for c, _, _ in calls))
    vals = [b * (1 << a) for _, a, b in calls]
    out = "\n".join(str(v) for v in vals)
    parts = [f"{c} = {b} · 2^{a} = {b} · {1 << a} = {v}" for (c, a, b), v in zip(calls, vals)]
    trap = "2 ** 0 = 1, а " if a1 == 0 else ""
    expl = ("Степень выполняется раньше умножения; без второго аргумента base = " + str(base) + ". "
            + "; ".join(parts) + f". Ловушка: {trap}переданный base заменяет значение по умолчанию.")
    stem = (f"Компонент «{ctx}» ({svc}) повторяет неудачные запросы к соседнему сервису с растущей задержкой; "
            "программа печатает задержку для нескольких попыток.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"base": base, "calls": [c for c, _, _ in calls]}, language="python")
