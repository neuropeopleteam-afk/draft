"""frontend.state.t21_batch_flush_output — predict_output (набор t21, порог Senior): пакетная отрисовка стора
через queueMicrotask, then и setTimeout.

Мини-стор: `set(v)` меняет значение и, если отрисовка ещё не запланирована, ставит одну микрозадачу «render»
(флаг scheduled сбрасывается в ней). Синхронный код несколько раз вызывает set, печатает значение; рядом —
`Promise.resolve().then(…)` с печатью или с ещё одним set и `setTimeout(() => set(…), 0)`. Ловушки: подряд идущие set
дают одну отрисовку с последним значением; микрозадачи выполняются в порядке постановки — then, поставленный до
первого set, печатает раньше render; set внутри then или таймера планирует новую отрисовку; таймер — после всех
микрозадач. Ключ — модель очередей в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from collections import deque

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.state.t21_batch_flush_output"

CTX = [("счётчик корзины", "count"), ("номер страницы таблицы", "page"), ("громкость плеера", "volume"),
       ("число выбранных строк", "selected"), ("масштаб карты", "zoom")]


def _simulate(stmts, var):
    out = []
    micro, macro = deque(), deque()
    st = {"v": 0, "scheduled": False}

    def set_(v):
        st["v"] = v
        if st["scheduled"]:
            return
        st["scheduled"] = True

        def render():
            st["scheduled"] = False
            out.append(f"render {st['v']}")
        micro.append(render)

    def drain():
        while micro:
            micro.popleft()()

    for kind, arg in stmts:
        if kind == "set":
            set_(arg)
        elif kind == "log":
            out.append(f"sync {st['v']}")
        elif kind == "then_log":
            micro.append(lambda: out.append(f"then {st['v']}"))
        elif kind == "then_set":
            micro.append(lambda a=arg: set_(a))
        elif kind == "timer_set":
            macro.append(lambda a=arg: set_(a))
    drain()
    while macro:
        macro.popleft()()
        drain()
    return out


def _js(kind, arg):
    return {"set": f"set({arg});", "log": "console.log(\"sync\", {v});",
            "then_log": "Promise.resolve().then(() => console.log(\"then\", {v}));",
            "then_set": f"Promise.resolve().then(() => set({arg}));",
            "timer_set": f"setTimeout(() => set({arg}), 0);"}[kind]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var = rng.choice(CTX)
    for _ in range(300):
        vals = rng.sample(range(1, 10), 5)
        n_set = rng.randint(2, 3)
        stmts = [("set", vals[i]) for i in range(n_set)]
        extra = [("then_log", None), ("log", None)]
        extra.append(rng.choice([("then_set", vals[3]), ("timer_set", vals[3])]))
        if rng.random() < 0.5:
            extra.append(("timer_set", vals[4]) if extra[-1][0] == "then_set" else ("then_set", vals[4]))
        # вставляем дополнительные операторы в случайные позиции, сохраняя порядок set
        for item in extra:
            stmts.insert(rng.randint(0, len(stmts)), item)
        kinds = [k for k, _a in stmts]
        if kinds.index("then_log") > kinds.index("set") and rng.random() < 0.5:
            continue  # чаще then до первого set — ловушка порядка микрозадач
        if kinds[-1] == "set" and rng.random() < 0.5:
            continue
        out = _simulate(stmts, var)
        if 4 <= len(out) <= 7:
            break
    else:
        raise RuntimeError("t21_batch_flush: не собран вариант")
    body = [f"let {var} = 0;", "let scheduled = false;", "function set(v) {", f"  {var} = v;",
            "  if (scheduled) return;", "  scheduled = true;", "  queueMicrotask(() => {",
            "    scheduled = false;", f"    console.log(\"render\", {var});", "  });", "}"]
    code = "\n".join(body + [_js(k, a).replace("{v}", var) for k, a in stmts])
    out_s = "\n".join(out)
    first_set = kinds.index("set")
    sync_sets = [a for k, a in stmts if k == "set"]
    notes = [f"синхронные set({'), set('.join(map(str, sync_sets))}) ставят одну микрозадачу render — флаг scheduled "
             f"уже поднят, повторные set только меняют значение"]
    if kinds.index("then_log") < first_set:
        notes.append("then с печатью поставлен в очередь раньше первого set, поэтому выполняется до render")
    else:
        notes.append("then с печатью поставлен после первого set — render выполняется раньше него")
    if "then_set" in kinds:
        if kinds.index("then_set") < first_set:
            notes.append("then с set поставлен в очередь раньше render: к моменту его выполнения флаг ещё поднят, "
                         "поэтому set только меняет значение, и render печатает уже новое")
        else:
            notes.append("then с set выполняется после первой отрисовки (флаг уже сброшен) и планирует "
                         "новую микрозадачу render")
    if "timer_set" in kinds:
        notes.append("таймер срабатывает после всех микрозадач, его set планирует ещё одну отрисовку")
    expl = ("Сначала весь синхронный код, затем микрозадачи в порядке постановки, затем таймеры (после каждого — его "
            "микрозадачи). " + "; ".join(notes) + ". Порядок: " + " → ".join(out) + ".")
    stem = (f"Интерфейс ({ctx}): стор откладывает отрисовку до конца текущей синхронной работы, чтобы несколько "
            f"изменений подряд дали одну отрисовку.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out_s, explanation=expl, context=ctx,
                          params={"stmts": [[k, a] for k, a in stmts]}, language="javascript")
