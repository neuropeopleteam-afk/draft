"""mobile.startup.t21_startup_order_output — predict_output (набор t21, порог Senior): порядок шагов запуска
React Native-приложения — синхронный код, микрозадачи (then, queueMicrotask, await) и таймеры.

При запуске приложение восстанавливает сессию (async-функция с await), применяет флаги цепочкой Promise.then,
ставит событие аналитики через queueMicrotask и прячет заставку по setTimeout(…, 0). Что проследить: тело
async-функции до первого await выполняется синхронно; каждый then и каждое продолжение после await — отдельная
микрозадача, встающая в конец очереди в момент, когда предыдущий шаг выполнен (поэтому цепочки чередуются);
таймер выполняется только после опустошения очереди микрозадач, а микрозадача, поставленная из таймера, — до
следующего таймера. Ключ — модель очереди микро- и макрозадач в генераторе; проверка — исполнение показанного кода
в песочнице Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.startup.t21_startup_order_output"

CTX = ["приложение доставки еды", "банковское приложение", "приложение такси", "маркетплейс",
       "приложение фитнес-клуба"]
ASYNC_FN = [("restoreSession", "session"), ("hydrateStore", "store"), ("loadProfile", "profile")]
CHAIN = ["flags", "theme", "i18n"]
MICRO = ["metrics", "analytics", "crashlog"]
TIMER1 = ["splash", "deeplink", "pushToken"]
TIMER2 = ["banner", "rating", "update"]
START = ["boot", "launch", "init"]
END = ["mounted", "rendered", "ready"]


def _simulate(seq: list[tuple], afn_steps: list[str], start: str, end: str) -> tuple[list[str], dict]:
    log: list[str] = [start]
    micro: deque = deque()
    macro: deque = deque()
    phases = {"sync": [], "micro": [], "macro": []}
    cur = {"phase": "sync"}

    def emit(s):
        log.append(s)
        phases[cur["phase"]].append(s)

    phases["sync"].append(start)

    def run_chain(labels, i):
        emit(labels[i])
        if i + 1 < len(labels):
            micro.append(lambda: run_chain(labels, i + 1))

    def async_step(i):
        emit(afn_steps[i])
        if i + 1 < len(afn_steps):
            micro.append(lambda: async_step(i + 1))   # await null → продолжение через одну микрозадачу

    def timer(label, nested):
        emit(label)
        if nested:
            micro.append(lambda: emit(nested))

    for kind, payload in seq:
        if kind == "chain":
            micro.append(lambda p=payload: run_chain(p, 0))
        elif kind == "micro":
            micro.append(lambda p=payload: emit(p))
        elif kind == "call":
            async_step(0)
        elif kind == "timer":
            macro.append(lambda p=payload: timer(*p))
    emit(end)
    cur["phase"] = "micro"
    while micro:
        micro.popleft()()
    while macro:
        cur["phase"] = "macro"
        macro.popleft()()
        while micro:
            micro.popleft()()
    return log, phases


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn, fpre = rng.choice(ASYNC_FN)
    start, end = rng.choice(START), rng.choice(END)
    for _ in range(300):
        n_await = rng.randint(1, 2)
        afn_steps = [f"{fpre}:{w}" for w in ["read", "parse", "done"][:n_await + 1]]
        ch = rng.choice(CHAIN)
        chain = [f"{ch}:1", f"{ch}:2"][:rng.randint(1, 2)]
        if len(chain) == 1:
            chain = [ch]
        t1 = rng.choice(TIMER1)
        nested = f"{t1}:then" if rng.random() < 0.5 else None
        items = [("chain", chain), ("micro", rng.choice(MICRO)), ("call", None), ("timer", (t1, nested))]
        if rng.random() < 0.5:
            items.append(("timer", (rng.choice(TIMER2), None)))
        rng.shuffle(items)
        # код: определение async-функции, start, элементы, end
        lines = [f"async function {fn}() {{", f"  console.log('{afn_steps[0]}');"]
        for s in afn_steps[1:]:
            lines += ["  await null;", f"  console.log('{s}');"]
        lines += ["}", f"console.log('{start}');"]
        for kind, payload in items:
            if kind == "chain":
                if len(payload) == 1:
                    lines.append(f"Promise.resolve().then(() => console.log('{payload[0]}'));")
                else:
                    lines += ["Promise.resolve()"] + [f"  .then(() => console.log('{p}'))" for p in payload]
                    lines[-1] += ";"
            elif kind == "micro":
                lines.append(f"queueMicrotask(() => console.log('{payload}'));")
            elif kind == "call":
                lines.append(f"{fn}();")
            else:
                label, nst = payload
                if nst:
                    lines += ["setTimeout(() => {", f"  console.log('{label}');",
                              f"  Promise.resolve().then(() => console.log('{nst}'));", "}, 0);"]
                else:
                    lines.append(f"setTimeout(() => console.log('{label}'), 0);")
        lines.append(f"console.log('{end}');")
        if len(lines) <= 18:
            break
    else:
        raise RuntimeError("t21_startup_order: код не уложился в 18 строк")
    log, ph = _simulate(items, afn_steps, start, end)
    code = "\n".join(lines)
    out = "\n".join(log)
    expl = (f"Синхронно (до первого await тело {fn} выполняется сразу): {', '.join(ph['sync'])}. Затем очередь "
            f"микрозадач по порядку постановки; следующий then и продолжение после await встают в конец очереди "
            f"только когда выполнен предыдущий шаг: {', '.join(ph['micro'])}. Таймеры — после опустошения очереди "
            f"микрозадач, микрозадача из таймера выполняется до следующего таймера: {', '.join(ph['macro'])}.")
    stem = (f"Запуск React Native-приложения ({ctx}): восстановление данных в async-функции, цепочка промисов, "
            f"событие через queueMicrotask и таймеры. Код выполняется целиком при старте.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"items": [[k, p] for k, p in items], "afn": afn_steps}, language="javascript")
