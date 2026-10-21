"""backend.http.t21_timeout_budget_output — predict_output (набор t21, порог Стажёра): приоритет операций и деление `/`.

Клиент внешнего API считает худшее время запроса с повторами. Первая строка — выражение без скобок
(`connect + read * retries`: умножение выполняется раньше сложения), вторая — то же со скобками, переведённое
в секунды делением `/ 1000` (результат всегда float: `1.8`, `2.0`). Ключ — независимый расчёт в генераторе
целыми числами и форматирование десятичной дроби; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.http.t21_timeout_budget_output"

CTX = [("сервис доставки", "delivery"), ("платёжный шлюз", "payments"), ("сервис уведомлений", "notify"),
       ("поиск по каталогу", "search"), ("сервис курсов валют", "rates"), ("геокодер адресов", "geo")]
# (имя этапа подключения, имя этапа чтения, имя числа попыток)
NAMES = [("connect_ms", "read_ms", "retries"), ("dial_ms", "response_ms", "attempts"),
         ("handshake_ms", "read_ms", "tries"), ("connect_ms", "wait_ms", "attempts")]


def _seconds(ms: int) -> str:
    """Как Python печатает ms / 1000 для целого ms (не больше трёх знаков после точки)."""
    frac = f"{ms % 1000:03d}".rstrip("0") or "0"
    return f"{ms // 1000}.{frac}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    c_name, r_name, n_name = rng.choice(NAMES)
    connect = rng.randrange(50, 310, 10)
    read = rng.randrange(150, 950, 50)
    retries = rng.randint(2, 5)
    total_var = rng.choice(["total", "worst", "budget"])
    code = (f"{c_name} = {connect}\n"
            f"{r_name} = {read}\n"
            f"{n_name} = {retries}\n"
            f"{total_var} = {c_name} + {r_name} * {n_name}\n"
            f"print({total_var})\n"
            f"print(({c_name} + {r_name}) * {n_name} / 1000)")
    first = connect + read * retries
    second_ms = (connect + read) * retries
    out = f"{first}\n{_seconds(second_ms)}"
    expl = (f"Умножение выполняется раньше сложения: {connect} + {read} · {retries} = {connect} + {read * retries} = "
            f"{first}. Во второй строке скобки: ({connect} + {read}) · {retries} = {second_ms}; деление `/` в Python 3 "
            f"всегда даёт float, поэтому печатается {_seconds(second_ms)} (а не {second_ms // 1000}).")
    stem = (f"Клиент сервиса «{ctx}» ({svc}) ходит во внешний API с повторами; программа оценивает время запроса "
            "в миллисекундах и в секундах.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"connect": connect, "read": read, "retries": retries}, language="python")
