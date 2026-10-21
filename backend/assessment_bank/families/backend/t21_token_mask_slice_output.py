"""backend.logs.t21_token_mask_slice_output — predict_output (набор t21, порог Стажёра): срезы строки с начала
и с конца.

Перед записью в лог сервис маскирует токен доступа: оставляет первые h и последние t символов
(`token[:h] + "..." + token[-t:]`), а во второй строке печатает часть токена по срезу `token[a:b]` — например,
окружение (live / test) из префикса. Ловушки: индексы с нуля, правая граница среза не включается,
отрицательный срез считается с конца. Ключ — независимая модель среза (посимвольный перебор) в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.logs.t21_token_mask_slice_output"

CTX = [("API заказов", "orders"), ("шлюз оплаты", "payments"), ("сервис профилей", "profiles"),
       ("биллинг", "billing"), ("сервис рассылок", "mailer"), ("склад", "warehouse")]
PREFIXES = ["app_live_", "app_test_", "svc_prod_", "svc_dev_", "tok_prod_", "tok_dev_", "key_live_", "key_test_"]
HEX = "0123456789abcdef"


def _take(s: str, start: int, stop: int) -> str:
    """Срез s[start:stop] для неотрицательных границ — посимвольно, без синтаксиса срезов."""
    return "".join(ch for i, ch in enumerate(s) if start <= i < stop)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    prefix = rng.choice(PREFIXES)
    body = "".join(rng.choice(HEX) for _ in range(rng.randint(10, 14)))
    token = prefix + body
    h = rng.randint(2, 4)
    t = rng.randint(3, 5)
    sep = prefix.index("_")
    # вторая строка: «окружение» между подчёркиваниями или кусок тела токена
    if rng.random() < 0.6:
        a, b = sep + 1, prefix.index("_", sep + 1)
        b += rng.choice([0, 1])  # иногда захватываем и второе подчёркивание
    else:
        a = len(prefix) + rng.randint(0, 3)
        b = a + rng.randint(3, 5)
    var = rng.choice(["token", "api_key", "secret"])
    code = (f'{var} = "{token}"\n'
            f"masked = {var}[:{h}] + \"...\" + {var}[-{t}:]\n"
            "print(masked)\n"
            f"print({var}[{a}:{b}])")
    n = len(token)
    head = _take(token, 0, h)
    tail = _take(token, n - t, n)
    mid = _take(token, a, b)
    masked = head + "..." + tail
    out = f"{masked}\n{mid}"
    expl = (f"Строка из {n} символов. [:{h}] — символы с индексами 0…{h - 1}: «{head}»; [-{t}:] — последние {t}: "
            f"«{tail}», вместе «{masked}». [{a}:{b}] — индексы {a}…{b - 1} (правая граница не включается): «{mid}».")
    stem = (f"Сервис «{ctx}» ({svc}) перед записью в лог маскирует токен доступа и отдельно печатает часть "
            "токена по срезу.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"token": token, "h": h, "t": t, "a": a, "b": b}, language="python")
