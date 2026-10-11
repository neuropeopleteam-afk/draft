"""data_eng.stream.lead_watermark_mcq — mcq_concept (Lead): результат окна по времени события с watermark.

Поток событий (время события, время прихода, сумма) в порядке прихода. Окна — неперекрывающиеся по W минут
по времени события, [s, e). Watermark после каждого события = максимум увиденного времени события − L.
Окно выдаёт результат и закрывается, как только watermark ≥ e; события окна, пришедшие позже, отбрасываются.
Вопрос — сумма, которую выдаст заданное окно.

Дистракторы (одной формы — «сумма = N»):
  * no_drop — учтены все события окна, включая опоздавшие (нет отбрасывания);
  * processing_time — окно по времени прихода, а не события;
  * inclusive_end — граница окна включена: событие ровно в e засчитано в окно.
Ключ проверяется исполнением: программа-модель проигрывает поток событие за событием (watermark, закрытие
окон, отбрасывание опоздавших) и печатает букву варианта с полученной суммой.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.stream.lead_watermark_mcq"

CONTEXTS = [("платежи", "сумма платежа"), ("заказы", "сумма заказа"), ("показы рекламы", "стоимость показа"),
            ("поездки такси", "стоимость поездки"), ("пополнения кошелька", "сумма пополнения"),
            ("продажи билетов", "цена билета")]

MODEL = """def simulate(events, W, L, start):
    # events: (id, t_event, t_arrival, amount) в порядке прихода; время — секунды от 00:00
    wm = None
    open_w, closed, result = {}, set(), {}
    for _id, te, ta, amt in events:
        ws = te // (W * 60) * (W * 60)
        if ws in closed:
            continue                      # опоздало: окно уже выдало результат
        open_w[ws] = open_w.get(ws, 0) + amt
        mx = te if wm is None else max(wm + L * 60, te)
        wm = mx - L * 60
        for s in sorted(open_w):
            if wm >= s + W * 60:
                result[s] = open_w.pop(s)
                closed.add(s)
    return result.get(start, open_w.get(start))
"""

PROGRAM = MODEL.replace("{", "{{").replace("}", "}}") + """
events = {events}
got = simulate(events, {W}, {L}, {start})
opts = __OPTS__
hit = [k for k, t in opts.items() if int(t.split("= ")[1].split(" ")[0].replace(" ", "")) == got]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _hms(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def _simulate(events, W, L, start):
    ns: dict = {}
    exec(MODEL, ns)                 # та же модель, что в проверке
    return ns["simulate"](events, W, L, start)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, what = rng.choice(CONTEXTS)
    for _ in range(3000):
        W = rng.choice([5, 10])
        L = rng.choice([1, 2, 3])
        hour = rng.choice([9, 12, 15, 18, 21])
        start = hour * 3600 + rng.choice([1, 2, 3]) * W * 60
        end = start + W * 60
        n = rng.choice([8, 9, 10])
        evs = []
        for i in range(n):
            te = start + rng.randint(-W * 60 // 2, W * 60 + W * 60 // 2)
            delay = rng.choice([0, 5, 20, 40, 70, 100]) if rng.random() < 0.75 else rng.choice([240, 330, 420, 540])
            evs.append([te, te + delay, rng.choice(range(10, 100, 5))])
        evs[rng.randrange(n)][0] = end                       # событие ровно на границе окна
        for e in evs:
            e[1] = max(e[1], e[0])
        evs.sort(key=lambda e: (e[1], e[0]))
        events = [(i + 1, te, ta, a) for i, (te, ta, a) in enumerate(evs)]
        good = _simulate(events, W, L, start)
        if good is None or _close_time(events, W, L, start)[0] is None:
            continue                                         # окно должно закрыться в пределах показанного потока
        no_drop = sum(a for _, te, _, a in events if start <= te < end)
        proc = sum(a for _, _, ta, a in events if start <= ta < end)
        # граница включена: то же моделирование, но событие ровно в e относится к окну [s, e]
        incl = good + sum(a for i, te, _, a in events if te == end and _counted(events, W, L, start, i))
        vals = {"good": good, "no_drop": no_drop, "processing_time": proc, "inclusive_end": incl}
        dropped = no_drop - good
        if len(set(vals.values())) == 4 and dropped > 0 and min(vals.values()) > 0:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    text = {k: f"сумма = {v}" for k, v in vals.items()}
    table = "\n".join(f"{i:>2} | {_hms(te)} | {_hms(ta)} | {a}" for i, te, ta, a in events)
    mm = lambda x: f"{x} {plural(x, 'минута', 'минуты', 'минут')}"
    stem = (f"Потоковая обработка: {ctx}. Окна по времени события — неперекрывающиеся по {mm(W)}, [начало, конец). "
            f"Watermark после каждого события = максимум увиденного времени события − {mm(L)}. Окно выдаёт результат "
            f"(сумма поля «{what}») и закрывается, как только watermark ≥ конца окна; события закрытого окна, "
            f"пришедшие позже, отбрасываются. События в порядке прихода:\n\n"
            f"№ | время события | время прихода | {what}\n{table}\n\n"
            f"Какой результат выдаст окно [{_hms(start)}, {_hms(end)})?")
    program = PROGRAM.format(events=repr(events), W=W, L=L, start=start)
    late = [i for i, te, ta, a in events if start <= te < end and not _counted(events, W, L, start, i)]
    expl = (f"Проигрываем поток: watermark растёт с максимумом времени события; окно [{_hms(start)}, {_hms(end)}) "
            f"закрывается, когда watermark ≥ {_hms(end)}, то есть после события со временем ≥ {_hms(end + L * 60)}. "
            f"В результат входят события окна, пришедшие до закрытия: сумма = {good}; опоздавшие ("
            f"№ {', '.join(map(str, late))}) отброшены. Без отбрасывания — {no_drop}; по времени прихода — {proc}; "
            f"событие ровно в {_hms(end)} относится к следующему окну (с ним — {incl}).")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=text["good"],
                       distractors=[text["no_drop"], text["processing_time"], text["inclusive_end"]],
                       program=program, explanation=expl,
                       params={"W": W, "L": L, "start": _hms(start), "n": len(events), "vals": vals},
                       note="Ответ проверяется программой-моделью: поток проигрывается событие за событием.")


def _close_time(events, W, L, start):
    """Время прихода события, после которого окно закрылось (None — не закрылось)."""
    end = start + W * 60
    mx = None
    for _id, te, ta, _a in events:
        mx = te if mx is None else max(mx, te)
        if mx - L * 60 >= end:
            return ta, _id
    return None, None


def _counted(events, W, L, start, eid):
    ct, cid = _close_time(events, W, L, start)
    if ct is None:
        return True
    order = [e[0] for e in events]
    return order.index(eid) < order.index(cid)
