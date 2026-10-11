"""analyst.uml.state_machine_output — predict_output: конечное состояние машины состояний после событий.

Машина состояний (текстовая запись UML: «источник --событие--> цель») и последовательность событий.
Событие, для которого в текущем состоянии нет перехода, отбрасывается (состояние не меняется). Нужно назвать
конечное состояние и число отброшенных событий. Варьируются контекст, порядок строк переходов, длина и состав
последовательности. Ключ проверяется исполнением: Python разбирает показанную запись дословно.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block
from ._fsm_data import FSM, PARSE, fmt

FAMILY_ID = "analyst.uml.state_machine_output"

RUN = r'''
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


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(FSM))
    F = FSM[ctx]
    trans = list(F["transitions"])
    rng.shuffle(trans)
    model = "\n".join(fmt(t) for t in trans)
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
    out_s = f"{state} {ign}"
    prog = py_literal_block("MODEL", model) + PARSE + f"INITIAL = {F['initial']!r}\nEVENTS = {evs!r}\n" + RUN
    checks = [Check(name="run_fsm", runner="python", program=prog, expect="stdout_equals", expected_stdout=out_s)]
    stem = (f"Машина состояний «{ctx}» (текстовая запись UML; переход «А --событие--> Б»). Начальное состояние — "
            f"«{F['initial']}». Событие, для которого в текущем состоянии нет перехода, отбрасывается, состояние "
            f"не меняется. Пришли события по порядку: {', '.join(evs)}. В каком состоянии окажется объект и "
            f"сколько событий будет отброшено? Ответ — название состояния и число через пробел, например "
            f"`{F['initial']} 0`.")
    ak = AnswerKey(kind="output", value=out_s,
                   explanation=(f"Идём по событиям от «{F['initial']}», для каждого ищем переход из текущего "
                                f"состояния. Итог: «{state}», отброшено событий — {ign}."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=model, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         params={"events": evs})
