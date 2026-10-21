"""qa.retry.t21_retry_loop_output — predict_output (набор t21, порог Junior): цикл с enumerate, continue и break —
политика повторов запроса в автотесте.

Записанные ответы сервера перебираются по попыткам: 429 — `continue` (повтор без учёта ретрая), код < 500 — `break`
(успех или ошибка клиента — повторять нечего), 5xx — счётчик ретраев. После цикла печатаются номер последней попытки,
число ретраев и последний код. Ловушки: 429 не увеличивает счётчик, 4xx тоже обрывает цикл, нумерация попыток с 1,
переменные цикла сохраняют последние значения. Ключ — независимая модель в генераторе; проверка — исполнение кода.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.retry.t21_retry_loop_output"

CTX = ["API-тест создания заказа", "тест загрузки отчёта", "смоук-проверка шлюза оплаты",
       "тест синхронизации профиля", "проверка вебхука доставки"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    var = rng.choice(["responses", "replies", "codes"])
    cnt = rng.choice(["retries", "retried", "errors"])
    for _ in range(300):
        n = rng.randint(4, 7)
        resp = [rng.choice([500, 502, 503, 504, 429, 429, 200, 201, 204, 404, 400, 409]) for _ in range(n)]
        # модель
        retries, last_attempt, last_code = 0, None, None
        for i, c in enumerate(resp, 1):
            last_attempt, last_code = i, c
            if c == 429:
                continue
            if c < 500:
                break
            retries += 1
        stop_idx = last_attempt
        if 429 in resp[:stop_idx] and retries >= 1 and (stop_idx < n or rng.random() < 0.25):
            break
    else:
        raise RuntimeError("t21_retry_loop: не собрался список")
    code = (f"{var} = {resp}\n"
            f"{cnt} = 0\n"
            f"for attempt, code in enumerate({var}, 1):\n"
            "    if code == 429:\n"
            "        continue\n"
            "    if code < 500:\n"
            "        break\n"
            f"    {cnt} += 1\n"
            f"print(attempt, {cnt}, code)")
    out = f"{last_attempt} {retries} {last_code}"
    steps = []
    for i, c in enumerate(resp[:stop_idx], 1):
        steps.append(f"{i}: {c} → " + ("continue" if c == 429 else ("break" if c < 500 else f"{cnt} += 1")))
    tail = ("цикл оборван break" if last_code != 429 and last_code < 500 else "список закончился")
    expl = ("Попытки с 1: " + "; ".join(steps) + f". Итог: {tail}, attempt = {last_attempt}, {cnt} = {retries}, "
            f"code = {last_code}. Ловушки — 429 пропускает увеличение счётчика, любой код < 500 (и 4xx) "
            "обрывает цикл, после цикла переменные хранят последние значения.")
    stem = (f"Повторы запроса ({ctx}): программа перебирает заранее записанные ответы сервера по попыткам и "
            "считает ретраи.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"responses": resp}, language="python")
