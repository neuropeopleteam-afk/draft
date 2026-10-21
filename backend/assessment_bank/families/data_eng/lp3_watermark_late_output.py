"""data_eng.stream.lp3_watermark_late_output — predict_output: сколько событий попадёт в окно при водяном знаке.

Потоковая агрегация по времени события: окна по минуте [s, s+60). Водяной знак = максимальное время события,
виденное к этому моменту, минус допустимое опоздание L. Окно выдаётся (и закрывается), когда водяной знак
достигает его конца; событие окна, пришедшее после закрытия, отбрасывается. Вопрос — сколько событий войдёт
в итог заданного окна. Ловушки: посчитать по времени события без отбрасывания; посчитать по времени прихода;
закрывать окно по времени события текущей записи, а не по максимуму. Ответ — целое число.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.stream.lp3_watermark_late_output"
STREAMS = ["клики на витрине", "события оплаты", "телеметрия самокатов", "логи входа", "заказы такси",
           "показы рекламы", "просмотры видео"]

CALC = r'''
import re
L, target, ev = None, None, []
for l in DATA.splitlines():
    if l.startswith("допустимое опоздание"):
        L = int(re.search(r"(\d+)", l).group(1))
    elif l.startswith("окно"):
        h, m = re.search(r"(\d\d):(\d\d)", l).groups()
        target = int(h) * 3600 + int(m) * 60
    elif l.count("|") == 1 and not l.startswith("приход"):
        a, t = [x.strip() for x in l.split("|")]
        hh, mm, ss = map(int, t.split(":"))
        ev.append(hh * 3600 + mm * 60 + ss)
wm, closed, cnt = -10**9, False, 0
for t in ev:
    if target <= t < target + 60 and not closed:
        cnt += 1
    wm = max(wm, t - L)
    if wm >= target + 60:
        closed = True
print(cnt)
'''


def _t(s: int) -> str:
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _run(ev, target, L):
    wm, closed, cnt = -10**9, False, 0
    for t in ev:
        if target <= t < target + 60 and not closed:
            cnt += 1
        wm = max(wm, t - L)
        if wm >= target + 60:
            closed = True
    return cnt


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    stream = rng.choice(STREAMS)
    for _ in range(4000):
        h = rng.randint(8, 22)
        m0 = rng.randint(0, 50)
        target = h * 3600 + (m0 + 1) * 60
        L = rng.choice([10, 15, 20, 30])
        n = rng.randint(14, 20)
        ev = []
        t = target - 40
        for _ in range(n):
            t += rng.randint(2, 12)
            jitter = -rng.choice([0, 0, 0, 3, 8, 25, 40, 70]) if rng.random() < 0.45 else 0
            ev.append(t + jitter)
        good = _run(ev, target, L)
        all_in = sum(1 for x in ev if target <= x < target + 60)
        no_max = 0
        closed = False
        for x in ev:  # ошибка: закрывать по текущему событию, а не по максимуму
            if target <= x < target + 60 and not closed:
                no_max += 1
            if x - L >= target + 60:
                closed = True
        if good == all_in or good < 3 or all_in - good > 6:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"допустимое опоздание: {L} с", f"окно: {_t(target)[:5]}–{_t(target + 60)[:5]}", "",
             "приход | время события"]
    for i, x in enumerate(ev, 1):
        lines.append(f"{i} | {_t(x)}")
    block = "\n".join(lines)
    stem = (f"Поток «{stream}» агрегируется по времени события окнами по одной минуте. Водяной знак — максимальное "
            "время события, виденное к этому моменту, минус допустимое опоздание; окно выдаёт итог и закрывается, "
            "как только водяной знак достиг его конца, опоздавшие события закрытого окна отбрасываются. События "
            "приходят в порядке номеров (таблица ниже). Сколько событий войдёт в итог указанного окна? Ответ — "
            "целое число.")
    expl = (f"Идём по приходу, водяной знак = max(время события) − {L} с; окно {_t(target)[:5]} закрывается, когда "
            f"знак достигает {_t(target + 60)}. До закрытия в окно попали {good} событий; всего событий с временем в "
            f"окне — {all_in}, остальные пришли после закрытия и отброшены. Закрытие по текущему событию вместо "
            f"максимума даёт {no_max}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=stream,
                         accept=num_accept(good, ("событий", "события")),
                         params={"L": L, "target": target, "ev": ev, "all_in": all_in})
