"""mobile.js.retry_backoff_output — predict_output: задержки повторов с экспоненциальным ростом и потолком.

Клиент мобильного приложения повторяет запрос при ошибке сети: задержка удваивается от базовой, ограничена
потолком, число попыток ограничено; при ответе сервера с заголовком Retry-After задержка берётся из него.
Нужно предсказать, что напечатает показанный код (задержки по попыткам). Один подтип; варьируются база,
множитель, потолок, число попыток, попытка с Retry-After. Ключ — независимый расчёт на Python, сверенный с
исполнением показанного кода в Node.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "mobile.js.retry_backoff_output"

CTX = ["отправка фото в чат", "синхронизация заметок", "загрузка ленты", "отправка геопозиции курьера",
       "выгрузка чеков", "обновление остатков склада"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    base = rng.choice([200, 250, 300, 400, 500])
    factor = rng.choice([2, 3])
    cap = rng.choice([2000, 3000, 4000, 5000])
    attempts = rng.randint(5, 6)
    ra_at = rng.randint(2, attempts - 1)
    ra_sec = rng.choice([1, 2, 3])
    fn = rng.choice(["retryDelay", "nextDelay", "backoff"])
    code = (f"const BASE_MS = {base};\nconst MAX_MS = {cap};\n\n"
            f"function {fn}(attempt, retryAfterSec) {{\n"
            f"  if (retryAfterSec !== undefined) return retryAfterSec * 1000;\n"
            f"  return Math.min(MAX_MS, BASE_MS * {factor} ** (attempt - 1));\n}}\n\n"
            f"const delays = [];\nfor (let attempt = 1; attempt <= {attempts}; attempt++) {{\n"
            f"  const retryAfter = attempt === {ra_at} ? {ra_sec} : undefined;\n"
            f"  delays.push({fn}(attempt, retryAfter));\n}}\nconsole.log(delays.join(' '));")
    exp = []
    for a in range(1, attempts + 1):
        exp.append(ra_sec * 1000 if a == ra_at else min(cap, base * factor ** (a - 1)))
    out = " ".join(map(str, exp))
    checks = [Check(name="run", runner="node", program=code, expect="stdout_equals", expected_stdout=out)]
    stem = (f"Мобильное приложение ({ctx}) повторяет запрос после ошибки сети. На попытке {ra_at} сервер ответил "
            f"503 с заголовком `Retry-After: {ra_sec}`. Что напечатает код? Ответ — числа через пробел, как в "
            f"выводе.")
    ak = AnswerKey(kind="output", value=out,
                   explanation=(f"Задержка — BASE·{factor}^(attempt−1), но не больше {cap} мс; на попытке {ra_at} "
                                f"берётся Retry-After: {ra_sec} с = {ra_sec * 1000} мс (экспонента при этом не "
                                f"сбрасывается и не сдвигается). Вывод: {out}."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"base": base, "factor": factor, "cap": cap, "attempts": attempts, "ra_at": ra_at})
