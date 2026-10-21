"""frontend.state.t21_batch_flush_output — predict_output (набор t21, порог Senior): буфер событий аналитики
с отправкой пакета по размеру или по таймеру — setTimeout / clearTimeout и микрозадачи.

`track(e)` кладёт событие в буфер; если набралось LIMIT событий — пакет отправляется сразу (flush("size")),
иначе первый же track пакета заводит таймер setTimeout(() => flush("timer"), 0). flush снимает таймер
(clearTimeout) и печатает пакет. События приходят из синхронного кода, из микрозадач (Promise.then /
queueMicrotask) и из таймеров. Ловушки: события из микрозадач попадают в пакет раньше, чем сработает таймер
отправки; таймер-событие, поставленное ДО таймера отправки, успевает в тот же пакет, поставленное после — нет;
отправка по размеру отменяет таймер, и следующее событие заводит новый. Каркас отличается от пакетной перерисовки
через флаг и queueMicrotask (mobile.state.t21_render_batch_output): здесь окно пакета — макрозадача, есть порог
размера и отмена таймера. Ключ — модель очередей и таймеров в генераторе; проверка — исполнение показанного кода
в Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.state.t21_batch_flush_output"

CTX = [("аналитика каталога", ["view", "click", "scroll", "filter", "sort", "share"]),
       ("события плеера", ["play", "pause", "seek", "mute", "like", "next"]),
       ("метрики формы оплаты", ["focus", "input", "blur", "submit", "error", "retry"]),
       ("события чата", ["open", "type", "send", "read", "react", "close"]),
       ("аналитика ленты", ["load", "swipe", "like", "save", "hide", "share"])]
BUF = [("buf", "timer"), ("queue", "handle"), ("batch", "tid"), ("pending", "timerId")]


PHASE_RU = {"sync": "в синхронном коде", "micro": "в микрозадаче", "timer": "в колбэке таймера"}


def _simulate(stmts, limit, trace=None):
    out = []
    micro, macro = deque(), deque()
    st = {"buf": [], "timer": None, "next_id": 1, "phase": "sync"}
    cancelled = set()

    def set_timeout(fn):
        tid = st["next_id"]
        st["next_id"] += 1
        macro.append((tid, fn))
        return tid

    def flush(reason):
        if st["timer"] is not None:
            cancelled.add(st["timer"])
        st["timer"] = None
        out.append(f"{reason} {','.join(st['buf'])}")
        if trace is not None:
            trace.append(f"«{out[-1]}» — {PHASE_RU[st['phase']]}")
        st["buf"] = []

    def track(e):
        st["buf"].append(e)
        if len(st["buf"]) >= limit:
            flush("size")
        elif st["timer"] is None:
            st["timer"] = set_timeout(lambda: flush("timer"))

    for kind, arg in stmts:
        if kind == "sync":
            track(arg)
        elif kind in ("then", "qm"):
            micro.append(lambda a=arg: track(a))
        elif kind == "timer":
            set_timeout(lambda a=arg: track(a))
        elif kind == "log":
            out.append(f"queued {len(st['buf'])}")
    st["phase"] = "micro"
    while micro:
        micro.popleft()()
    while macro:
        tid, fn = macro.popleft()
        if tid in cancelled:
            continue
        st["phase"] = "timer"
        fn()
        st["phase"] = "micro"
        while micro:
            micro.popleft()()
    return out


def _js(kind, arg, bv):
    return {"sync": f'track("{arg}");',
            "then": f'Promise.resolve().then(() => track("{arg}"));',
            "qm": f'queueMicrotask(() => track("{arg}"));',
            "timer": f'setTimeout(() => track("{arg}"), 0);',
            "log": f'console.log("queued", {bv}.length);'}[kind]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, words = rng.choice(CTX)
    bv, tv = rng.choice(BUF)
    for _ in range(500):
        n = rng.choice([4, 5, 5])
        names = rng.sample(words, n)
        kinds = ["sync", rng.choice(["then", "qm"]), "timer"]
        kinds += [rng.choice(["sync", "sync", "then", "qm", "timer"]) for _ in range(n - 3)]
        rng.shuffle(kinds)
        stmts = list(zip(kinds, names))
        stmts.insert(rng.randint(1, len(stmts)), ("log", None))
        limit = rng.choice([2, 3, 3, 4])
        out = _simulate(stmts, limit)
        reasons = [o.split()[0] for o in out if not o.startswith("queued")]
        if "size" not in reasons or "timer" not in reasons:
            continue
        if not 3 <= len(out) <= 5:
            continue
        # ловушка порядка таймеров: хотя бы одно таймер-событие встало в очередь до таймера отправки
        first_sync = kinds.index("sync")
        if not any(k == "timer" for k in kinds[:first_sync]) and rng.random() < 0.6:
            continue
        break
    else:
        raise RuntimeError("t21_batch_flush: не собран вариант")
    body = [f"const {bv} = [];", f"let {tv} = null;",
            "function flush(reason) {", f"  clearTimeout({tv});", f"  {tv} = null;",
            f'  console.log(reason, {bv}.splice(0).join(","));', "}",
            "function track(e) {", f"  {bv}.push(e);", f'  if ({bv}.length >= {limit}) flush("size");',
            f'  else if (!{tv}) {tv} = setTimeout(() => flush("timer"), 0);', "}"]
    code = "\n".join(body + [_js(k, a, bv) for k, a in stmts])
    out_s = "\n".join(out)
    trace: list[str] = []
    _simulate(stmts, limit, trace)
    src_ru = {"sync": "синхронно", "then": "из then", "qm": "из queueMicrotask", "timer": "из таймера"}
    order = ", ".join(f"{a} ({src_ru[k]})" for k, a in stmts if k != "log")
    expl = (f"Порядок прихода событий: сначала синхронные, затем микрозадачи (then и queueMicrotask — одна очередь, "
            f"в порядке постановки), затем таймеры в порядке постановки; после каждого таймера — его микрозадачи. "
            f"В коде: {order}. Первый track пакета заводит таймер отправки; таймер-событие, поставленное раньше "
            f"него, успевает в тот же пакет. Когда в буфере {limit} — flush(\"size\") отправляет пакет сразу и "
            f"clearTimeout отменяет таймер, следующее событие заводит новый. «queued» печатает длину буфера в "
            f"момент синхронного кода. Отправки: " + "; ".join(trace) + ". Вывод: " + " → ".join(out) + ".")
    stem = (f"Интерфейс ({ctx}): события копятся в буфере и отправляются пакетом — по размеру или по таймеру.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out_s, explanation=expl, context=ctx,
                          params={"stmts": [[k, a] for k, a in stmts], "limit": limit}, language="javascript")
