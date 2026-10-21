"""security.token.t21_ttl_expiry_output — predict_output (набор t21, порог Стажёра): приоритет `*` над `+` и
строгое сравнение `<` на границе срока действия токена.

Сервис авторизации считает время истечения токена `exp = iat + ttl_min * 60` и проверяет его в несколько моментов
`now`: `now < exp` — «valid», иначе «expired» и сколько секунд прошло после exp. Ловушки чтения: умножение
выполняется раньше сложения (минуты переводятся в секунды, затем прибавляются к iat); сравнение строгое — в момент
ровно `exp` токен уже «expired» (граница есть в большинстве вариантов). Ключ — независимый расчёт в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.token.t21_ttl_expiry_output"

CTX = ["онлайн-банк", "личный кабинет оператора связи", "портал единого входа", "API доставки",
       "сервис онлайн-записи к врачу", "внутренняя CRM", "мобильный кошелёк"]
NAMES = [("iat", "ttl_min", "exp", "now"), ("issued", "ttl_minutes", "expires", "t"),
         ("iat", "lifetime_min", "exp", "check_at"), ("issued_at", "ttl_min", "expires_at", "now")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    iv, tv, ev, nv = rng.choice(NAMES)
    iat = rng.randrange(1000, 9000, 50)
    ttl_min = rng.choice([2, 3, 4, 5, 10, 15])
    exp = iat + ttl_min * 60
    moments = {exp + rng.choice([30, 60, 90, 120, 300])}
    moments.add(exp - rng.choice([1, 10, 30, 60, 90]))
    if rng.random() < 0.75:
        moments.add(exp)
    if rng.random() < 0.5:
        moments.add(iat + rng.choice([0, 15, 45, 60]))
    if len(moments) < 3:
        moments.add(exp + rng.choice([1, 5, 600, 900]))
    times = sorted(moments)
    if rng.random() < 0.4:  # проверки из журнала — не обязательно по возрастанию
        rng.shuffle(times)
    if rng.random() < 0.5:
        expr = f"{iv} + {tv} * 60"
    else:
        expr = f"{tv} * 60 + {iv}"
    code = (f"{iv} = {iat}\n"
            f"{tv} = {ttl_min}\n"
            f"{ev} = {expr}\n"
            f"for {nv} in {times}:\n"
            f"    if {nv} < {ev}:\n"
            f'        print({nv}, "valid")\n'
            "    else:\n"
            f'        print({nv}, "expired", {nv} - {ev})')
    lines = [f"{t} valid" if t < exp else f"{t} expired {t - exp}" for t in times]
    out = "\n".join(lines)
    edge = (f"В момент ровно {exp} условие строгое ({exp} < {exp} ложно) — уже «expired», разница 0. "
            if exp in times else "")
    calc = (f"{iat} + {ttl_min}·60 = {iat} + {ttl_min * 60}" if expr.startswith(iv)
            else f"{ttl_min}·60 + {iat} = {ttl_min * 60} + {iat}")
    expl = (f"Умножение выполняется раньше сложения: {ev} = {calc} = {exp}. "
            f"Моменты меньше {exp} — «valid», остальные — «expired» и {nv} − {ev}. {edge}"
            f"Вывод по строкам: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Сервис авторизации ({ctx}) проверяет срок действия токена доступа в несколько моментов времени; "
            "все значения — секунды по часам сервиса.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"iat": iat, "ttl_min": ttl_min, "times": times}, language="python")
