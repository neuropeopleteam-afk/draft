"""data_eng.stream.tumbling_window_output — predict_output: окна по времени события и водяной знак.

Упрощённый обработчик потока (идея — как у Apache Flink и Kafka Streams: tumbling windows по event time,
водяной знак с ограниченной задержкой): окно [s, s + W); водяной знак после события = max(время событий) −
DELAY; окно закрывается и печатается, когда s + W ≤ водяной знак; событие, чьё окно уже за водяным знаком,
отбрасывается как опоздавшее; в конце потока оставшиеся окна закрываются. В каждом варианте — событие не по
порядку, которое ещё принимается, отброшенное опоздавшее и не меньше двух окон, закрытых посреди потока.
Агрегат — сумма или число событий. Ключ — независимая модель генератора; проверка — исполнение показанного кода
дословно в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.stream.tumbling_window_output"

CTX = [("выручка по оплатам", "sum", "amount"), ("число кликов по баннеру", "count", "clicks"),
       ("объём трафика CDN, МБ", "sum", "mb"), ("число ошибок 5xx", "count", "errors"),
       ("сумма пополнений кошелька", "sum", "amount"), ("число заказов такси", "count", "orders")]


def _code(window, delay, events, agg):
    add = "open_w.get(start, 0) + value" if agg == "sum" else "open_w.get(start, 0) + 1"
    ev = ",\n".join(f"    ({t}, {v})" for t, v in events)
    return "\n".join([
        f"WINDOW, DELAY = {window}, {delay}  # секунды",
        "",
        "EVENTS = [  # (время события, значение) в порядке поступления",
        ev,
        "]",
        "",
        "open_w, wm = {}, None",
        "for t, value in EVENTS:",
        "    start = t - t % WINDOW",
        "    if wm is not None and start + WINDOW <= wm:",
        "        print(\"late\", t)",
        "        continue",
        f"    open_w[start] = {add}",
        "    wm = t - DELAY if wm is None else max(wm, t - DELAY)",
        "    for s in sorted(open_w):",
        "        if s + WINDOW <= wm:",
        "            print(\"window\", s, open_w.pop(s))",
        "for s in sorted(open_w):  # конец потока",
        "    print(\"window\", s, open_w.pop(s))",
    ])


def _model(window, delay, events, agg):
    """Независимый расчёт: водяной знак как максимум префикса; окна закрываются по возрастанию начала."""
    out, acc, max_t, late, mid = [], {}, None, 0, 0
    for t, v in events:
        w = None if max_t is None else max_t - delay
        s = (t // window) * window
        if w is not None and s + window <= w:
            out.append(f"late {t}")
            late += 1
            continue
        acc[s] = acc.get(s, 0) + (v if agg == "sum" else 1)
        max_t = t if max_t is None else max(max_t, t)
        w = max_t - delay
        for s2 in sorted(k for k in acc if k + window <= w):
            out.append(f"window {s2} {acc.pop(s2)}")
            mid += 1
    for s2 in sorted(acc):
        out.append(f"window {s2} {acc[s2]}")
    return "\n".join(out), late, mid


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, agg, _name = rng.choice(CTX)
    for _ in range(5000):
        window = rng.choice([30, 60, 120])
        delay = rng.choice([d for d in (10, 15, 20, 30, 40) if d < window])
        n = rng.randint(8, 12)
        t, times = rng.randint(0, window - 1), []
        for _ in range(n):
            times.append(t)
            t += rng.randint(3, window // 2)
        vals = [rng.choice([1, 2, 3, 5, 10, 20, 50]) if agg == "sum" else 1 for _ in times]
        events = list(zip(times, vals))
        # 2–3 события приходят позже на 1–4 позиции
        for _ in range(rng.randint(2, 3)):
            i = rng.randrange(n - 1)
            e = events.pop(i)
            events.insert(min(n - 1, i + rng.randint(1, 4)), e)
        expected, late, mid = _model(window, delay, events, agg)
        seen_max, ooo_ok = None, False
        for tt, _v in events:
            if seen_max is not None and tt < seen_max and f"late {tt}" not in expected.split("\n"):
                ooo_ok = True
            seen_max = tt if seen_max is None else max(seen_max, tt)
        if late >= 1 and mid >= 2 and ooo_ok:
            break
    code = _code(window, delay, events, agg)
    what = "сумму значений" if agg == "sum" else "число событий"
    stem = (f"Упрощённый обработчик потока «{ctx}» считает {what} в неперекрывающихся окнах по времени события "
            f"длиной {window} с; водяной знак (watermark) — максимум времени уже принятых событий минус {delay} с. "
            "Что напечатает код? Ответ — строки вывода по порядку.")
    expl = ("Водяной знак растёт только от принятых событий. Окно [s, s + W) закрывается, как только s + W ≤ "
            "водяной знак; событие не по порядку принимается, пока его окно открыто, и отбрасывается (late), если "
            "окно уже за водяным знаком. Оставшиеся окна печатаются в конце потока.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals", expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="python",
                         params={"window": window, "delay": delay, "agg": agg, "late": late})
