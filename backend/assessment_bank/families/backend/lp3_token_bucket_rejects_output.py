"""backend.ratelimit.lp3_token_bucket_rejects_output — predict_output: сколько запросов отклонит token bucket.

Лимит по клиенту — «ведро» ёмкостью B, пополняется на r токенов в секунду непрерывно; запрос берёт токен, нет
токена — 429. В начале ведро полное. По журналу запросов (время в секундах) нужно посчитать отклонённые.
Ловушки: считать по окну «не больше B·… в секунду» (фиксированное окно); пополнять токены целыми порциями раз в
секунду; забыть, что ведро не наполняется выше B. Ответ — целое число.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.ratelimit.lp3_token_bucket_rejects_output"
CLIENTS = ["мобильное приложение партнёра", "интеграция маркетплейса", "бот поддержки", "B2B-клиент выгрузки",
           "виджет на сайте партнёра"]

CALC = r'''
import re
B = r = None
ts = []
for l in DATA.splitlines():
    if l.startswith("ёмкость ведра"):
        B = int(re.search(r"(\d+)", l).group(1))
    elif l.startswith("пополнение"):
        r = float(re.search(r"([\d,]+)", l).group(1).replace(",", "."))
    elif l.startswith("запросы"):
        ts = [float(x.replace(",", ".")) for x in l.split(":", 1)[1].split(";")]
tok, last, rej = float(B), 0.0, 0
for t in ts:
    tok = min(B, tok + (t - last) * r)
    last = t
    if tok >= 1 - 1e-9:
        tok -= 1
    else:
        rej += 1
print(rej)
'''


def _sim(ts, B, r):
    tok, last, rej = float(B), 0.0, 0
    for t in ts:
        tok = min(B, tok + (t - last) * r)
        last = t
        if tok >= 1 - 1e-9:
            tok -= 1
        else:
            rej += 1
    return rej


def _f(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    client = rng.choice(CLIENTS)
    for _ in range(3000):
        B = rng.randint(3, 8)
        r = rng.choice([0.5, 1, 1.5, 2, 2.5])
        n = rng.randint(14, 22)
        t, ts = 0.0, []
        for _ in range(n):
            t += rng.choice([0.0, 0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.5, 2.5])
            ts.append(round(t, 1))
        good = _sim(ts, B, r)
        # ошибка: фиксированное окно в 1 с — не больше max(1, r) запросов в каждой секунде сверх стартового B
        ints = []  # ошибка: пополнение целыми порциями раз в секунду
        tok, last_s, rej2 = B, 0, 0
        for x in ts:
            s = int(x)
            tok = min(B, tok + (s - last_s) * int(r))
            last_s = s
            if tok >= 1:
                tok -= 1
            else:
                rej2 += 1
        nocap = 0
        tok, last = float(B), 0.0
        for x in ts:
            tok = tok + (x - last) * r
            last = x
            if tok >= 1 - 1e-9:
                tok -= 1
            else:
                nocap += 1
        if not 2 <= good <= n - 4 or good in (rej2, nocap):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"ёмкость ведра: {B}", f"пополнение: {_f(r)} токена в секунду",
                       "запросы (секунды от начала): " + "; ".join(_f(x) for x in ts)])
    stem = (f"Клиент «{client}» ограничен алгоритмом token bucket: ведро указанной ёмкости, в начале полное, токены "
            "добавляются непрерывно с заданной скоростью, но не выше ёмкости; каждый запрос забирает один токен, "
            "если токена нет — ответ 429 (запрос не ставится в очередь и токен не расходует). Сколько запросов из "
            "журнала получат 429? Ответ — целое число.")
    expl = (f"Моделируем по журналу: перед каждым запросом токены = min({B}, токены + Δt · {_f(r)}); есть ≥ 1 — "
            f"расходуем, иначе 429. Итого отклонено {good}. Пополнение целыми порциями раз в секунду даёт {rej2}, "
            f"ведро без верхней границы — {nocap}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=client,
                         accept=num_accept(good, ("запросов", "запроса")), params={"B": B, "r": r, "ts": ts})
