"""analyst.uml.state_machine_output — predict_output: конечное состояние машины состояний после событий.

Машина состояний (текстовая запись UML: «источник --событие--> цель») и последовательность событий.
Событие, для которого в текущем состоянии нет перехода, отбрасывается (состояние не меняется). Нужно назвать
конечное состояние и число отброшенных событий. Варьируются контекст, порядок строк переходов, длина и состав
последовательности и правило/вопрос: «отбросить событие без перехода», «остановить обработку на нём»,
«сколько раз объект входил в состояние X». Ключ проверяется исполнением: Python разбирает показанную запись дословно.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block
from ._fsm_data import FSM, PARSE, fmt

FAMILY_ID = "analyst.uml.state_machine_output"

RUN_SKIP = r'''
state = INITIAL
ignored = 0
for ev in EVENTS:
    nxt = [d for s, e, d in T if s == state and e == ev]
    if nxt:
        state = nxt[0]
    else:
        ignored += 1
print(state, ignored)
'''

RUN_STOP = r'''
state = INITIAL
stopped = 0
for i, ev in enumerate(EVENTS, 1):
    nxt = [d for s, e, d in T if s == state and e == ev]
    if not nxt:
        stopped = i
        break
    state = nxt[0]
print(state, stopped)
'''

RUN_VISITS = r'''
state = INITIAL
entered = 0
for ev in EVENTS:
    nxt = [d for s, e, d in T if s == state and e == ev]
    if nxt:
        state = nxt[0]
        if state == TARGET:
            entered += 1
print(state, entered)
'''

# правило обработки события без перехода и вопрос
MODES = ["skip", "stop", "visits"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(FSM))
    F = FSM[ctx]
    trans = list(F["transitions"])
    rng.shuffle(trans)
    model = "\n".join(fmt(t) for t in trans)
    mode = MODES[seed % 3] if seed % 7 else rng.choice(MODES)
    for _ in range(500):
        n = rng.randint(6, 8)
        evs, state, ign = [], F["initial"], 0
        for _ in range(n):
            out = [t for t in trans if t[0] == state]
            if out and rng.random() < 0.7:
                t = rng.choice(out)
                evs.append(t[1])
                state = t[2]
            else:
                bad = [e for e in F["events"] if not any(t[0] == state and t[1] == e for t in trans)]
                if not bad:
                    continue
                evs.append(rng.choice(bad))
                ign += 1
        if 1 <= ign <= 3 and len(evs) >= 6:
            break
    else:
        raise RuntimeError("нет последовательности")
    visited = []
    st = F["initial"]
    for ev in evs:
        nxt = [t[2] for t in trans if t[0] == st and t[1] == ev]
        if nxt:
            st = nxt[0]
            visited.append(st)
    target = rng.choice(sorted(set(visited))) if visited else F["initial"]
    if mode == "skip":
        out_s = f"{state} {ign}"
        run, extra = RUN_SKIP, ""
        rule = "Событие, для которого в текущем состоянии нет перехода, отбрасывается, состояние не меняется."
        ask = (f"В каком состоянии окажется объект и сколько событий будет отброшено? Ответ — название состояния и "
               f"число через пробел, например `{F['initial']} 0`.")
        why = f"Итог: «{state}», отброшено событий — {ign}."
    elif mode == "stop":
        st, stop_at = F["initial"], 0
        for i, ev in enumerate(evs, 1):
            nxt = [t[2] for t in trans if t[0] == st and t[1] == ev]
            if not nxt:
                stop_at = i
                break
            st = nxt[0]
        out_s = f"{st} {stop_at}"
        run, extra = RUN_STOP, ""
        rule = ("Событие, для которого в текущем состоянии нет перехода, — ошибка: обработка останавливается на нём, "
                "объект остаётся в текущем состоянии, следующие события не обрабатываются.")
        ask = (f"В каком состоянии останется объект и на каком по счёту событии остановится обработка? Ответ — "
               f"название состояния и номер события через пробел (0 — если ошибок не было), например "
               f"`{F['initial']} 0`.")
        why = f"Итог: «{st}», обработка остановилась на событии № {stop_at}."
    else:
        st, cnt = F["initial"], 0
        for ev in evs:
            nxt = [t[2] for t in trans if t[0] == st and t[1] == ev]
            if nxt:
                st = nxt[0]
                cnt += st == target
        out_s = f"{st} {cnt}"
        run, extra = RUN_VISITS, f"TARGET = {target!r}\n"
        rule = "Событие, для которого в текущем состоянии нет перехода, отбрасывается, состояние не меняется."
        ask = (f"В каком состоянии окажется объект и сколько раз он входил в состояние «{target}» (начальное "
               f"пребывание не считается)? Ответ — название состояния и число через пробел, например "
               f"`{F['initial']} 0`.")
        why = f"Итог: «{st}», входов в «{target}» — {cnt}."
    prog = (py_literal_block("MODEL", model) + PARSE + f"INITIAL = {F['initial']!r}\nEVENTS = {evs!r}\n" + extra
            + run)
    checks = [Check(name="run_fsm", runner="python", program=prog, expect="stdout_equals", expected_stdout=out_s)]
    stem = (f"Машина состояний «{ctx}» (текстовая запись UML; переход «А --событие--> Б»). Начальное состояние — "
            f"«{F['initial']}». {rule} Пришли события по порядку: {', '.join(evs)}. {ask}")
    ak = AnswerKey(kind="output", value=out_s,
                   explanation=(f"Идём по событиям от «{F['initial']}», для каждого ищем переход из текущего "
                                f"состояния. {why}"))
    return build_variant(FAMILY_ID, seed, stem=stem, code=model, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         params={"events": evs, "mode": mode, "target": target})
