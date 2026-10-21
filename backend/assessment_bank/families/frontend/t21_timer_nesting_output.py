"""frontend.async.t21_timer_nesting_output — predict_output (набор t21, порог Senior): опрос через рекурсивный
setTimeout — куда встаёт перепланированный таймер и что выполняется между двумя колбэками таймеров.

Функция опроса увеличивает счётчик, печатает шаг, ставит микрозадачу проверки (then или queueMicrotask) и, пока
счётчик меньше N, перепланирует себя через setTimeout(poll, 0). Опрос запускается прямым вызовом poll() (первый шаг —
синхронно) или таймером; рядом — разовые таймеры, синхронный лог и then, который сам ставит ещё один таймер.
Ловушки: перепланированный опрос встаёт в КОНЕЦ очереди таймеров — после уже поставленных разовых таймеров и после
таймера, поставленного из микрозадачи; микрозадача проверки выполняется сразу после своего шага опроса, до
следующего таймера; при прямом вызове poll() первая проверка печатается только после всего синхронного кода.
Каркас отличается от плоской последовательности запуска (mobile.startup.t21_startup_order_output): здесь таймер
перепланирует сам себя. Ключ — модель очередей микро- и макрозадач в генераторе; проверка — исполнение показанного
кода в Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.async.t21_timer_nesting_output"

# (сюжет, имя функции опроса, метка шага, метка проверки, разовые метки, (метка then, метка таймера из then), sync)
CTX = [("виджет уведомлений", "poll", "poll", "badge", ["toast", "sound"], ("init", "hint"), "start"),
       ("статус заказа", "refresh", "fetch", "render", ["banner", "tooltip"], ("restore", "promo"), "mount"),
       ("загрузка файла", "checkUpload", "check", "progress", ["spinner", "notice"], ("auth", "retry"), "ready"),
       ("чат поддержки", "pollChat", "pull", "unread", ["typing", "avatar"], ("session", "greet"), "open"),
       ("лента новостей", "loadMore", "page", "paint", ["skeleton", "ads"], ("cache", "prefetch"), "boot")]
CNT = ["n", "tries", "step", "count"]


def _simulate(items, n_max, inner_kind, resched_first):
    out = []
    micro, macro = deque(), deque()
    st = {"n": 0}

    def poll(step_lbl, chk_lbl):
        st["n"] += 1
        out.append(f"{step_lbl} {st['n']}")

        def check():
            out.append(f"{chk_lbl} {st['n']}")

        def resched():
            if st["n"] < n_max:
                macro.append(lambda: poll(step_lbl, chk_lbl))
        if resched_first:
            resched()
            micro.append(check)
        else:
            micro.append(check)
            resched()

    for kind, a, b in items:
        if kind == "poll_call":
            poll(a, b)
        elif kind == "poll_timer":
            macro.append(lambda a=a, b=b: poll(a, b))
        elif kind == "timer":
            macro.append(lambda a=a: out.append(a))
        elif kind == "sync":
            out.append(a)
        elif kind == "then_timer":
            def cb(a=a, b=b):
                out.append(a)
                macro.append(lambda: out.append(b))
            micro.append(cb)
    while micro:
        micro.popleft()()
    while macro:
        macro.popleft()()
        while micro:
            micro.popleft()()
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, step_lbl, chk_lbl, singles, (then_lbl, then_t_lbl), sync_lbl = rng.choice(CTX)
    cv = rng.choice(CNT)
    for _ in range(500):
        n_max = rng.choice([2, 3, 3])
        inner_kind = rng.choice(["then", "qm"])
        resched_first = rng.random() < 0.5
        start = rng.choice(["poll_call", "poll_timer"])
        k_single = rng.choice([1, 2])
        items = [(start, step_lbl, chk_lbl), ("sync", sync_lbl, None), ("then_timer", then_lbl, then_t_lbl)]
        items += [("timer", s, None) for s in rng.sample(singles, k_single)]
        rng.shuffle(items)
        out = _simulate(items, n_max, inner_kind, resched_first)
        if not 8 <= len(out) <= 11:
            continue
        kinds = [it[0] for it in items]
        if kinds[0] == "sync":
            continue
        # хотя бы один разовый таймер поставлен после запуска опроса — иначе нечего «обгонять»
        if not any(k == "timer" for k in kinds[kinds.index(start) + 1:]) and rng.random() < 0.7:
            continue
        break
    else:
        raise RuntimeError("t21_timer_nesting: не собран вариант")
    inner = (f'Promise.resolve().then(() => console.log("{chk_lbl}", {cv}));' if inner_kind == "then"
             else f'queueMicrotask(() => console.log("{chk_lbl}", {cv}));')
    resched = f"if ({cv} < {n_max}) setTimeout({fn}, 0);"
    body = [f"let {cv} = 0;", f"function {fn}() {{", f"  {cv}++;", f'  console.log("{step_lbl}", {cv});']
    body += [f"  {resched}", f"  {inner}"] if resched_first else [f"  {inner}", f"  {resched}"]
    body.append("}")
    top = []
    for kind, a, b in items:
        if kind == "poll_call":
            top.append(f"{fn}();")
        elif kind == "poll_timer":
            top.append(f"setTimeout({fn}, 0);")
        elif kind == "timer":
            top.append(f'setTimeout(() => console.log("{a}"), 0);')
        elif kind == "sync":
            top.append(f'console.log("{a}");')
        elif kind == "then_timer":
            top += ["Promise.resolve().then(() => {", f'  console.log("{a}");',
                    f'  setTimeout(() => console.log("{b}"), 0);', "});"]
    code = "\n".join(body + top)
    out_s = "\n".join(out)
    if start == "poll_call":
        start_note = (f"{fn}() вызван напрямую: шаг «{step_lbl} 1» печатается синхронно, его проверка — только после "
                      f"всего синхронного кода, а таймер шага 2 ставится ещё в синхронном коде — на место вызова: "
                      f"раньше таймеров ниже по коду и раньше таймера «{then_t_lbl}» из then; следующие шаги "
                      f"перепланируются из колбэка таймера и встают в конец очереди")
    else:
        start_note = (f"Первый шаг {fn} запускается таймером на своём месте по коду; к моменту его выполнения в "
                      f"очереди уже стоят все разовые таймеры и таймер «{then_t_lbl}» из then, поэтому "
                      f"setTimeout({fn}, 0) ставит каждый следующий шаг в конец очереди — после них")
    expl = (f"Сначала синхронный код, затем микрозадачи, затем таймеры по одному, и после каждого таймера — его "
            f"микрозадачи. {start_note}. Микрозадача проверки выполняется сразу после своего шага, до следующего "
            f"таймера. Опрос делает {n_max} шага. Порядок: " + " → ".join(out) + ".")
    stem = (f"Интерфейс ({ctx}): функция {fn} опрашивает сервер шагами через таймер, рядом — разовые таймеры "
            f"и обработчики промисов; каждый шаг печатает свою метку.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out_s, explanation=expl, context=ctx,
                          params={"items": [list(it) for it in items], "n_max": n_max, "inner": inner_kind,
                                  "resched_first": resched_first}, language="javascript")
