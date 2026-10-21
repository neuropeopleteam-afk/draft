"""mobile.state.t21_render_batch_output — predict_output (набор t21, порог Senior): пакетная перерисовка
экрана через queueMicrotask и порядок очереди микрозадач.

Мини-хранилище состояния React Native-экрана: setState сливает патч в состояние и, если перерисовка ещё не
запланирована, ставит её в очередь микрозадач (флаг scheduled). Обновления приходят синхронно, из
Promise.then / queueMicrotask и из setTimeout. Что проследить: синхронные вызовы схлопываются в одну перерисовку
с последним значением; микрозадача, поставленная ДО первой перерисовки, попадает в тот же пакет (и перерисовка
показывает её значение), поставленная ПОСЛЕ — даёт отдельную перерисовку; таймер — всегда после всех микрозадач.
Ключ — модель очереди микро- и макрозадач в генераторе; проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.state.t21_render_batch_output"

CTX = [("счётчик непрочитанных в чате", "unread"), ("номер страницы ленты", "page"),
       ("число товаров в корзине", "cartCount"), ("прогресс загрузки фото", "progress"),
       ("номер шага онбординга", "step")]


def _simulate(ops: list[tuple], field: str) -> list[str]:
    """ops: ('sync', v) | ('then', v) | ('micro', v) | ('timer', [v, ...]) в порядке появления в коде."""
    log: list[str] = []
    st = {"v": 0, "scheduled": False}
    micro: deque = deque()
    macro: deque = deque()

    def render():
        st["scheduled"] = False
        log.append(f"render {st['v']}")

    def set_state(v):
        st["v"] = v
        if st["scheduled"]:
            return
        st["scheduled"] = True
        micro.append(render)

    for kind, val in ops:
        if kind == "sync":
            set_state(val)
        elif kind in ("then", "micro"):
            micro.append(lambda v=val: set_state(v))
        else:
            macro.append(lambda vs=val: [set_state(v) for v in vs])
    log.append(f"sync {st['v']}")

    def drain():
        while micro:
            micro.popleft()()
    drain()
    while macro:
        macro.popleft()()
        drain()
    return log


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, field = rng.choice(CTX)
    for _ in range(300):
        n_sync = rng.randint(2, 3)
        n_async = rng.randint(1, 2)
        kinds = ["sync"] * n_sync + [rng.choice(["then", "micro"]) for _ in range(n_async)]
        rng.shuffle(kinds)
        if kinds[0] != "sync" and rng.random() < 0.5:
            continue  # чаще первым идёт синхронный вызов, но не всегда
        timer_pos = rng.randint(0, len(kinds))
        vals = rng.sample(range(1, 30), len(kinds) + 2)
        ops = [(k, vals[i]) for i, k in enumerate(kinds)]
        tvals = [vals[-2]] if rng.random() < 0.5 else [vals[-2], vals[-1]]
        ops.insert(timer_pos, ("timer", tvals))
        # ловушка должна быть: хотя бы одна микрозадача с обновлением (до или после первой перерисовки)
        first_sync = next(i for i, (k, _v) in enumerate(ops) if k == "sync")
        before = any(k in ("then", "micro") for k, _v in ops[:first_sync])
        after = any(k in ("then", "micro") for k, _v in ops[first_sync:])
        if before or after:
            break
    log = _simulate(ops, field)
    lines = [f"let state = {{ {field}: 0 }};",
             "let scheduled = false;",
             "function setState(patch) {",
             "  state = { ...state, ...patch };",
             "  if (scheduled) return;",
             "  scheduled = true;",
             "  queueMicrotask(() => {",
             "    scheduled = false;",
             f"    console.log('render', state.{field});",
             "  });",
             "}"]
    for kind, val in ops:
        if kind == "sync":
            lines.append(f"setState({{ {field}: {val} }});")
        elif kind == "then":
            lines.append(f"Promise.resolve().then(() => setState({{ {field}: {val} }}));")
        elif kind == "micro":
            lines.append(f"queueMicrotask(() => setState({{ {field}: {val} }}));")
        else:
            body = " ".join(f"setState({{ {field}: {v} }});" for v in val)
            lines.append(f"setTimeout(() => {{ {body} }}, 0);")
    lines.append(f"console.log('sync', state.{field});")
    code = "\n".join(lines)
    out = "\n".join(log)
    first_sync = next(i for i, (k, _v) in enumerate(ops) if k == "sync")
    pre = [v for k, v in ops[:first_sync] if k in ("then", "micro")]
    post = [v for k, v in ops[first_sync:] if k in ("then", "micro")]
    parts = [f"Синхронно все вызовы setState сливаются, перерисовка ставится в очередь микрозадач один раз — при "
             f"первом вызове (scheduled = true); console.log('sync') видит последнее синхронное значение."]
    if pre:
        w = ("Обновление " + str(pre[0]) + " поставлено") if len(pre) == 1 else \
            ("Обновления " + ", ".join(map(str, pre)) + " поставлены")
        parts.append(f"{w} в очередь микрозадач раньше перерисовки: выполняется первым, флаг ещё поднят — новая "
                     f"перерисовка не ставится, и первая перерисовка показывает уже значение {pre[-1]}.")
    if post:
        if len(post) == 1:
            parts.append(f"Обновление {post[0]} стоит в очереди после перерисовки: к его выполнению флаг уже "
                         f"сброшен, поэтому оно ставит ещё одну перерисовку в конец очереди микрозадач.")
        else:
            parts.append(f"Обновления {', '.join(map(str, post))} стоят в очереди после перерисовки: первое из "
                         f"них (флаг уже сброшен) ставит ещё одну перерисовку в конец очереди, следующие попадают "
                         f"в неё же — она покажет {post[-1]}.")
    parts.append("Таймер выполняется после всех микрозадач; вызовы внутри него снова схлопываются в одну "
                 "перерисовку.")
    expl = " ".join(parts) + f" Вывод: {' / '.join(log)}."
    stem = (f"Мини-хранилище состояния React Native-экрана ({ctx}): setState сливает изменения и планирует одну "
            f"перерисовку через queueMicrotask; обновления приходят синхронно, из промисов и из таймера.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"ops": [[k, v] for k, v in ops]}, language="javascript")
