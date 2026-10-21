"""mobile.config.lp3_remote_config_delay_output — predict_output: когда пользователь увидит новое значение флага.

Удалённая конфигурация: приложение при открытии применяет значение, загруженное в ПРОШЛЫЙ раз (активация при
следующем запуске), и в фоне загружает новое, но только если с прошлой загрузки прошло не меньше минимального
интервала. Флаг переключили в момент T. По времени открытий приложения нужно найти минуту открытия, на котором
пользователь впервые увидит новое значение. Ловушки: «при первом открытии после T» (забыта активация при следующем
запуске); забыть минимальный интервал загрузки. Ответ — минута (как в таблице).
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.config.lp3_remote_config_delay_output"
FLAGS = ["новый экран оплаты", "отключение старого API", "баннер акции", "лимит загрузки фото", "тёмная тема"]

CALC = r'''
import re
v, opens = {}, []
for l in DATA.splitlines():
    m = re.match(r"^([^:]+):\s*(\d+)", l)
    if l.startswith("открытия"):
        opens = [int(x) for x in l.split(":", 1)[1].split(";")]
    elif m:
        v[m.group(1).strip()] = int(m.group(2))
T, mi, last = v["флаг переключён, минута"], v["минимальный интервал загрузки, мин"], v["последняя загрузка, минута"]
have_new = False
for t in opens:
    if have_new:
        print(t)
        break
    if t - last >= mi:
        last = t
        if t >= T:
            have_new = True
'''


def _sim(opens, T, mi, last):
    have_new = False
    for t in opens:
        if have_new:
            return t
        if t - last >= mi:
            last = t
            if t >= T:
                have_new = True
    return None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    flag = rng.choice(FLAGS)
    for _ in range(3000):
        mi = rng.choice([30, 60, 120, 240, 720])
        last = rng.randint(0, 200)
        T = last + rng.randint(5, 300)
        n = rng.randint(7, 11)
        t, opens = last + rng.randint(1, 40), []
        for _ in range(n):
            opens.append(t)
            t += rng.choice([3, 10, 25, 45, 90, 180, 400])
        good = _sim(opens, T, mi, last)
        if good is None:
            continue
        naive = next((x for x in opens if x >= T), None)
        no_min = _sim(opens, T, 0, last)
        if good in (naive, no_min):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"флаг переключён, минута: {T}", f"минимальный интервал загрузки, мин: {mi}",
                       f"последняя загрузка, минута: {last}", "открытия приложения, минута: " + "; ".join(map(str, opens))])
    stem = (f"Флаг «{flag}» в удалённой конфигурации переключили (минута в блоке ниже). Приложение при каждом открытии "
            "сразу применяет значение из последней удачной загрузки, а затем загружает конфигурацию в фоне — только "
            "если с последней загрузки прошло не меньше минимального интервала; загруженное применится при "
            "следующем открытии. На каком открытии (укажите минуту) пользователь впервые увидит новое значение? "
            "Ответ — целое число.")
    expl = (f"Идём по открытиям: загрузка происходит, только если прошло ≥ {mi} мин с прошлой; первая загрузка не "
            f"раньше минуты {T} приносит новое значение, а применится оно на следующем открытии — минута {good}. "
            f"«Первое открытие после переключения» — {naive}; без минимального интервала — {no_min}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=flag,
                         accept=[f"{good} мин", f"минута {good}"], params={"T": T, "mi": mi, "last": last, "opens": opens})
