"""frontend.async.t21_timer_nesting_output — predict_output (набор t21, порог Senior): вложенные таймеры
и микрозадачи — что выполняется между двумя setTimeout(…, 0).

Верхний уровень: синхронный лог, два таймера с нулевой задержкой, then и queueMicrotask; внутри колбэка таймера
ставится микрозадача (then или queueMicrotask) и/или ещё один таймер, внутри then — таймер или ещё одна микрозадача.
Ловушки: микрозадачи выполняются полностью после синхронного кода и после КАЖДОГО колбэка таймера (до следующего
таймера); таймер, поставленный из микрозадачи или из таймера, встаёт в конец очереди таймеров; then и
queueMicrotask — одна очередь в порядке постановки. Ключ — модель очередей в генераторе; проверка — исполнение
показанного кода в Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.async.t21_timer_nesting_output"

CTX = [("виджет уведомлений", ["poll", "badge", "toast", "sound", "count"]),
       ("поле поиска", ["input", "suggest", "fetch", "render", "focus"]),
       ("галерея", ["thumb", "lazy", "zoom", "swipe", "caption"]),
       ("форма оплаты", ["mask", "check", "submit", "spinner", "receipt"])]


def _simulate(top):
    """top: список узлов верхнего уровня. Узел: (kind, label, children); kind ∈ sync/timeout/then/qm."""
    out, micro, macro = [], deque(), deque()

    def schedule(node):
        kind, label, children = node

        def body():
            out.append(label)
            for ch in children:
                schedule(ch)
        if kind == "sync":
            body()
        elif kind == "timeout":
            macro.append(body)
        else:
            micro.append(body)

    for node in top:
        schedule(node)
    while micro:
        micro.popleft()()
    while macro:
        macro.popleft()()
        while micro:
            micro.popleft()()
    return out


def _js(node, ind=""):
    kind, label, children = node
    log = f"console.log(\"{label}\");"
    if kind == "sync":
        return [ind + log]
    head = {"timeout": "setTimeout(() => ", "then": "Promise.resolve().then(() => ",
            "qm": "queueMicrotask(() => "}[kind]
    tail = ", 0);" if kind == "timeout" else ");"
    if not children:
        return [ind + head + log[:-1] + tail]
    lines = [ind + head + "{", ind + "  " + log]
    for ch in children:
        lines += _js(ch, ind + "  ")
    lines.append(ind + "}" + tail)
    return lines


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, words = rng.choice(CTX)
    for _ in range(300):
        labels = iter(rng.sample([f"{w} {i}" for w in words for i in (1, 2)], 9))
        t1_kids = [(rng.choice(["then", "qm"]), next(labels), [])]
        if rng.random() < 0.5:
            t1_kids.append(("timeout", next(labels), []))
            rng.shuffle(t1_kids)
        then_kids = [(rng.choice(["timeout", "qm", "then"]), next(labels), [])]
        top = [("timeout", next(labels), t1_kids), ("timeout", next(labels), []),
               ("then", next(labels), then_kids), ("sync", next(labels), [])]
        if rng.random() < 0.6:
            top.append(("qm", next(labels), []))
        rng.shuffle(top)
        out = _simulate(top)
        # синхронный лог не первым строкой кода и первый таймер не обязательно первым — иначе слишком прямолинейно
        if [n[0] for n in top][0] == "sync":
            continue
        break
    else:
        raise RuntimeError("t21_timer_nesting: не собран вариант")
    code_lines = []
    for node in top:
        code_lines += _js(node)
    code = "\n".join(code_lines)
    out_s = "\n".join(out)
    expl = ("Сначала синхронный код, затем все микрозадачи (then и queueMicrotask — одна очередь, в порядке "
            "постановки; микрозадача, поставленная из микрозадачи, выполняется в том же проходе), затем таймеры по "
            "одному: после каждого колбэка таймера сразу выполняются его микрозадачи, а новый таймер встаёт в конец "
            "очереди таймеров. Порядок: " + " → ".join(out) + ".")
    stem = (f"Интерфейс ({ctx}): обработчики откладывают часть работы через таймеры и микрозадачи; каждый шаг "
            f"печатает свою метку.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out_s, explanation=expl, context=ctx,
                          params={"kinds": [[n[0], [c[0] for c in n[2]]] for n in top]}, language="javascript")
