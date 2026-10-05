"""Модель цикла событий для семейств frontend: синхронный код → микрозадачи → таймеры.

Описание программы — список инструкций; по нему строится JS-код и вычисляется порядок
вывода. Кроме верной модели есть «ошибочные ментальные модели» — из них получаются
правдоподобные дистракторы:

* timers_first — таймеры с нулевой задержкой выполняются раньше промисов;
* chain_eager — вся цепочка .then выполняется подряд, без возврата в очередь;
* await_sync — await не приостанавливает async-функцию;
* executor_async — тело исполнителя new Promise выполняется асинхронно;
* qm_macro — queueMicrotask работает как setTimeout;
* source_order — всё выводится в порядке строк кода.
"""
from __future__ import annotations

from collections import deque

WRONG_MODELS = ["timers_first", "chain_eager", "await_sync", "executor_async", "qm_macro",
                "source_order"]


def js_lines(stmts: list[tuple]) -> list[str]:
    head, body = [], []
    for st in stmts:
        k = st[0]
        if k == "log":
            body.append(f"console.log('{st[1]}');")
        elif k == "timeout":
            body.append(f"setTimeout(() => console.log('{st[1]}'), 0);")
        elif k == "then1":
            body.append(f"Promise.resolve().then(() => console.log('{st[1]}'));")
        elif k == "then2":
            body.append(f"Promise.resolve()\n  .then(() => console.log('{st[1]}'))\n"
                        f"  .then(() => console.log('{st[2]}'));")
        elif k == "qm":
            body.append(f"queueMicrotask(() => console.log('{st[1]}'));")
        elif k == "async":
            head.append(f"async function {st[4]}() {{\n  console.log('{st[1]}');\n  await null;\n"
                        f"  console.log('{st[2]}');\n}}")
            body.append(f"{st[4]}().then(() => console.log('{st[3]}'));")
        elif k == "timeout_micro":
            body.append(f"setTimeout(() => {{\n  console.log('{st[1]}');\n"
                        f"  Promise.resolve().then(() => console.log('{st[2]}'));\n}}, 0);")
        elif k == "executor":
            body.append(f"new Promise((resolve) => {{\n  console.log('{st[1]}');\n  resolve();\n"
                        f"}}).then(() => console.log('{st[2]}'));")
        else:
            raise ValueError(k)
    return head + ([""] if head else []) + body


def simulate(stmts: list[tuple], model: str | set[str] = "correct") -> list[str]:
    m = {model} if isinstance(model, str) else set(model)
    out: list[str] = []
    if "source_order" in m:
        for st in stmts:
            out.extend(st[1:4] if st[0] == "async" else st[1:])
        return out
    micro: deque = deque()
    timers: list = []
    q = micro.append
    log = lambda x: (lambda: out.append(x))  # noqa: E731

    for st in stmts:
        k = st[0]
        if k == "log":
            out.append(st[1])
        elif k == "timeout":
            timers.append(log(st[1]))
        elif k == "then1":
            q(log(st[1]))
        elif k == "then2":
            x, y = st[1], st[2]
            if "chain_eager" in m:
                q(lambda x=x, y=y: (out.append(x), out.append(y)))
            else:
                q(lambda x=x, y=y: (out.append(x), q(log(y))))
        elif k == "qm":
            (timers.append if "qm_macro" in m else q)(log(st[1]))
        elif k == "async":
            x, y, z = st[1], st[2], st[3]
            out.append(x)
            if "await_sync" in m:
                out.append(y)
                q(log(z))
            else:
                q(lambda y=y, z=z: (out.append(y), q(log(z))))
        elif k == "timeout_micro":
            x, y = st[1], st[2]
            timers.append(lambda x=x, y=y: (out.append(x), q(log(y))))
        elif k == "executor":
            x, y = st[1], st[2]
            if "executor_async" in m:
                q(lambda x=x, y=y: (out.append(x), q(log(y))))
            else:
                out.append(x)
                q(log(y))

    def drain():
        while micro:
            micro.popleft()()

    if "timers_first" in m:
        for t in timers:
            t()
        drain()
        return out
    drain()
    for t in timers:
        t()
        drain()
    return out


def n_labels(stmts: list[tuple]) -> int:
    return sum(3 if st[0] == "async" else len(st) - 1 for st in stmts)
