"""security.tokens.lp3_revocation_window_output — predict_output: окно использования украденной сессии после отзыва.

Злоумышленник украл refresh-токен и обновляет access-токен, как только текущий истекает. В момент отзыва
(обнаружена повторная попытка использовать старый refresh — отзывается вся цепочка) у него на руках последний
access-токен. Сервис A проверяет JWT локально (подпись и срок) — отозванный, но не истёкший токен работает до exp.
Сервис B спрашивает сервер авторизации (introspection) и кэширует ответ «активен» на c минут — в худшем случае
работает ещё min(c, остаток срока токена). Ловушки: «окно = TTL» без учёта момента последнего обновления;
забыть кэш introspection (ответ 0 для B); не ограничить кэш сроком токена. Ответ — два числа через пробел.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.tokens.lp3_revocation_window_output"
APPS = ["интернет-банк", "маркетплейс", "медицинская платформа", "корпоративный портал", "сервис доставки",
        "онлайн-школа"]

CALC = r'''
import re
v = {}
for l in DATA.splitlines():
    m = re.match(r"^([^:]+):\s*(\d+)", l)
    if m:
        v[m.group(1).strip()] = int(m.group(2))
ttl, c = v["срок access-токена, мин"], v["кэш introspection в сервисе B, мин"]
t0, t1 = v["кража refresh-токена, минута"], v["отзыв цепочки токенов, минута"]
last = t0 + ((t1 - t0) // ttl) * ttl
if last == t1:
    last -= ttl
left = last + ttl - t1
print(left, min(c, left))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    app = rng.choice(APPS)
    for _ in range(3000):
        ttl = rng.choice([5, 10, 15, 30, 60])
        c = rng.choice([1, 2, 5, 10, 15])
        t0 = rng.randint(0, 120)
        t1 = t0 + rng.randint(ttl + 1, 8 * ttl)
        last = t0 + ((t1 - t0) // ttl) * ttl
        if last == t1:
            continue
        left = last + ttl - t1
        b = min(c, left)
        if left == ttl or b == c and rng.random() < 0.3 or left in (0,):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"срок access-токена, мин: {ttl}", f"кэш introspection в сервисе B, мин: {c}",
             f"кража refresh-токена, минута: {t0}", f"отзыв цепочки токенов, минута: {t1}"]
    block = "\n".join(lines)
    stem = (f"Расследование в продукте «{app}». Украден refresh-токен пользователя; с момента кражи злоумышленник "
            "сразу получает access-токен и обновляет его ровно в момент истечения предыдущего. Когда легитимный "
            "клиент повторно предъявил уже использованный refresh-токен, сервер авторизации отозвал всю цепочку "
            "(минуты отсчитываются от начала суток наблюдения). Сервис A проверяет access-токен (JWT) локально — "
            "подпись и срок; сервис B спрашивает сервер авторизации и кэширует ответ «токен активен» на указанное "
            "время. Сколько минут после отзыва злоумышленник в худшем случае ещё может вызывать сервис A и сервис "
            "B? Ответ — два целых числа через пробел: A B.")
    expl = (f"Обновления: {t0}, {t0 + ttl}, … последнее до отзыва — минута {last}; токен живёт до {last + ttl}. "
            f"Сервис A не знает об отзыве: {last + ttl} − {t1} = {left} мин. Сервис B в худшем случае закэшировал "
            f"«активен» прямо перед отзывом: min({c}, {left}) = {b} мин. Ошибки: «окно = срок токена» ({ttl}), "
            "забыть кэш (0 для B), не ограничить кэш сроком токена. Вывод: короткий срок access-токена и "
            "подписка сервисов на события отзыва.")
    out = f"{left} {b}"
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=out, expl=expl, ctx=app,
                         accept=[f"{left}, {b}", f"{left};{b}", f"A {left} B {b}", f"{left} мин {b} мин"],
                         params={"ttl": ttl, "c": c, "t0": t0, "t1": t1})
