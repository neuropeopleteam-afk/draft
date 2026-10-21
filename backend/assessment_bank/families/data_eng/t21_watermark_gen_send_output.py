"""data_eng.stream.t21_watermark_gen_send_output — predict_output (набор t21, порог Senior): водяной знак потока
в генераторе — next() для запуска, send() возвращает СЛЕДУЮЩЕЕ выданное значение, return — через StopIteration.value.

Генератор держит водяной знак (максимальное время события) и считает опоздавшие события (время не больше текущего
знака — `<=`, или строго меньше — `<`, по варианту). Ловушки: первый next() выдаёт стартовое значение; send(ts)
возвращает знак уже ПОСЛЕ обработки ts; событие, равное знаку, считается опоздавшим только при `<=`; итог return
приходит в e.value. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.stream.t21_watermark_gen_send_output"

CTX = ["поток кликов с сайта", "события мобильного приложения", "телеметрия датчиков склада",
       "поток платёжных уведомлений", "журнал действий пользователей"]
FN = ["watermark", "tracker", "event_clock", "late_counter"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn = rng.choice(FN)
    op = rng.choice(["<=", "<"])
    for _ in range(500):
        start = rng.randrange(100, 900, 10)
        k = rng.randint(3, 5)
        ts = []
        wm = start
        for _ in range(k):
            r = rng.random()
            if r < 0.45:
                t = wm + rng.randint(1, 12)
            elif r < 0.7:
                t = wm
            else:
                t = wm - rng.randint(1, 15)
            ts.append(t)
            wm = max(wm, t)
        wm, late, outs = start, 0, []
        for t in ts:
            if (t <= wm) if op == "<=" else (t < wm):
                late += 1
            wm = max(wm, t)
            outs.append(wm)
        has_eq = any(t == w for t, w in zip(ts, [start] + outs[:-1]))
        has_old = any(t < w for t, w in zip(ts, [start] + outs[:-1]))
        if has_eq and has_old and late >= 1 and len(set(outs)) >= 2:
            break
    else:
        raise RuntimeError("t21_watermark_gen_send: не собрался поток")
    lst = ", ".join(str(t) for t in ts)
    code = (f"def {fn}(wm):\n"
            "    late = 0\n"
            "    while True:\n"
            "        ts = yield wm\n"
            "        if ts is None:\n"
            "            return late\n"
            f"        if ts {op} wm:\n"
            "            late += 1\n"
            "        wm = max(wm, ts)\n"
            f"g = {fn}({start})\n"
            "print(next(g))\n"
            f"for ts in [{lst}]:\n"
            "    print(g.send(ts))\n"
            "try:\n"
            "    g.send(None)\n"
            "except StopIteration as e:\n"
            "    print(\"late\", e.value)")
    out = "\n".join([str(start)] + [str(w) for w in outs] + [f"late {late}"])
    eq_txt = ("событие, равное текущему знаку, тоже считается опоздавшим (`<=`)" if op == "<=" else
              "событие, равное текущему знаку, не считается опоздавшим (`<` строгое)")
    expl = (f"next(g) запускает генератор до первого yield и выдаёт стартовый знак {start}. Каждый send(ts) "
            f"возобновляет генератор: ts обрабатывается, знак обновляется max(), и send возвращает уже новый знак: "
            + ", ".join(f"{t}→{w}" for t, w in zip(ts, outs))
            + f". {eq_txt[0].upper() + eq_txt[1:]}; опоздавших {late}. send(None) доходит до return, и значение "
              f"приходит в StopIteration.value: «late {late}».")
    stem = (f"Обработчик «{ctx}» отслеживает водяной знак потока генератором; программа подаёт в него времена "
            "событий (в секундах).")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"op": op, "start": start, "events": ts}, language="python")
