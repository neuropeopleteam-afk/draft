"""frontend.state.t21_shallow_copy_output — predict_output (набор t21, порог Senior): обновление состояния
интерфейса поверхностной копией `{ ...state }` и мемоизированный селектор, который сравнивает массив по ссылке.

Селектор запоминает последний массив и результат (длину или последний элемент) и пересчитывает только при новой
ссылке (`arr !== last`). Редьюсер сначала делает `const next = { ...state }` и мутирует `next.<массив>` (push /
unshift / pop), затем переприсваивает скалярное поле `next.<поле> = …`; после этого — правильное обновление
`{ ...next | state, <массив>: [...src.<массив>, x] | src.<массив>.concat(x) | src.<массив>.slice(1) }`.
Что проследить: spread копирует только верхний уровень — массив общий, мутация видна и через state; скалярное поле
у state не меняется; селектор по той же ссылке возвращает УСТАРЕВШЕЕ значение (не пересчитывает), а новый массив
пересчитывает (calls растёт); `state === next` — false, `state.<массив> === next.<массив>` — true; аргументы
console.log вычисляются слева направо (calls читается после вызова селектора). Ключ — независимая модель ссылок
(списки Python как общие объекты) в генераторе; проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.state.t21_shallow_copy_output"

# (контекст, условие, имя массива, имя поля, значения поля, элементы массива)
CTX = [("список задач",
        "Редьюсер экрана задач обновляет состояние, а значок над списком берёт значение из мемоизированного "
        "селектора; программа печатает результаты селектора и сравнения состояний.",
        "todos", "filter", ["all", "active", "done"], ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]),
       ("чат",
        "Экран чата хранит сообщения в состоянии компонента, а подпись над лентой берёт значение из мемоизированного "
        "селектора; программа печатает результаты селектора и сравнения состояний.",
        "messages", "draft", ["hello", "typing", "sent"], ["m1", "m2", "m3", "m4", "m5", "m6", "m7"]),
       ("таблица заказов",
        "Таблица заказов в админке хранит строки и сортировку в состоянии, а итог над таблицей считает "
        "мемоизированный селектор; программа печатает его результаты и сравнения состояний.",
        "rows", "sortBy", ["date", "price", "status"], [101, 102, 103, 104, 105, 106, 107]),
       ("корзина",
        "Корзина магазина обновляет состояние после действий покупателя, а значок корзины берёт значение из "
        "мемоизированного селектора; программа печатает результаты селектора и сравнения состояний.",
        "lines", "coupon", ["none", "SALE10", "VIP5"], ["A12", "B07", "C33", "D41", "E05", "F18", "G90"]),
       ("фильтр тегов",
        "Панель фильтров хранит выбранные теги и строку поиска в состоянии, а подпись над панелью берёт значение из "
        "мемоизированного селектора; программа печатает результаты селектора и сравнения состояний.",
        "tags", "query", ["react", "hooks", "memo"], ["perf", "a11y", "i18n", "seo", "ux", "api", "css"])]
MEMO_NAMES = [("last", "cached", "calls"), ("prevArr", "prevValue", "runs"), ("seen", "memo", "hits")]
FN_NAMES = {"len": ["count", "badgeCount", "selectCount"], "last": ["lastItem", "preview", "selectLast"]}


def _js(v) -> str:
    """Как console.log печатает значение-аргумент."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _lit(v) -> str:
    return f'"{v}"' if isinstance(v, str) else str(v)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem, A, F, fvals, pool = rng.choice(CTX)
    kind = "len" if rng.random() < 0.6 else "last"
    lv, cv, kv = rng.choice(MEMO_NAMES)
    fn = rng.choice(FN_NAMES[kind])
    elems = rng.sample(pool, 6)
    init = elems[:rng.randint(2, 3)]
    fresh = [e for e in elems if e not in init]
    f0, f1 = rng.sample(fvals, 2)
    op = rng.choice(["push1", "push1", "push2", "unshift", "pop"])
    src = "next" if rng.random() < 0.7 else "state"
    upd = rng.choice(["append", "append", "concat", "slice"])

    # --- независимая модель: списки Python — общие объекты, как массивы JS -------------------------------------
    memo = {"last": None, "cached": None, "calls": 0}

    def sel(arr: list):
        if arr is not memo["last"]:
            memo["calls"] += 1
            memo["last"] = arr
            memo["cached"] = len(arr) if kind == "len" else arr[-1]
        return memo["cached"]

    state = {F: f0, A: list(init)}
    out = [_js(sel(state[A]))]
    first_val = out[0]
    nxt = dict(state)                      # { ...state } — копия верхнего уровня
    if op == "push1":
        x = fresh.pop(0)
        nxt[A].append(x)
        op_code = f"next.{A}.push({_lit(x)});"
    elif op == "push2":
        x, y = fresh.pop(0), fresh.pop(0)
        nxt[A].extend([x, y])
        op_code = f"next.{A}.push({_lit(x)}, {_lit(y)});"
    elif op == "unshift":
        x = fresh.pop(0)
        nxt[A].insert(0, x)
        op_code = f"next.{A}.unshift({_lit(x)});"
    else:
        nxt[A].pop()
        op_code = f"next.{A}.pop();"
    nxt[F] = f1
    # строка 11: селектор по той же ссылке + два значения
    extra11 = rng.sample([f"next.{A}.length", f"state.{A}.length", f"state.{F}", f"next.{F}"], 2)
    env = {f"next.{A}.length": lambda: len(nxt[A]), f"state.{A}.length": lambda: len(state[A]),
           f"state.{F}": lambda: state[F], f"next.{F}": lambda: nxt[F]}
    line11 = [_js(sel(nxt[A]))] + [_js(env[e]()) for e in extra11]
    out.append(" ".join(line11))
    stale = line11[0]
    # правильное обновление — новый массив
    s_obj = nxt if src == "next" else state
    z = fresh.pop(0)
    if upd == "append":
        new_arr = s_obj[A] + [z]
        upd_code = f"[...{src}.{A}, {_lit(z)}]"
    elif upd == "concat":
        new_arr = s_obj[A] + [z]
        upd_code = f"{src}.{A}.concat({_lit(z)})"
    else:
        if len(s_obj[A]) < 2:
            new_arr = s_obj[A] + [z]
            upd, upd_code = "append", f"[...{src}.{A}, {_lit(z)}]"
        else:
            new_arr = s_obj[A][1:]
            upd_code = f"{src}.{A}.slice(1)"
    fixed = dict(s_obj)
    fixed[A] = new_arr
    with_ff = rng.random() < 0.4
    v13 = _js(sel(fixed[A]))
    line13 = [v13, _js(memo["calls"])] + ([_js(fixed[F])] if with_ff else [])
    out.append(" ".join(line13))
    cmp_pool = [f"state.{A}.length", "state === next", f"next.{A} === fixed.{A}", f"state.{F} === next.{F}"]
    picks = [f"state.{A} === next.{A}"] + rng.sample(cmp_pool, 2)
    rng.shuffle(picks)
    cmp_val = {f"state.{A}.length": len(state[A]), "state === next": state is nxt,
               f"state.{A} === next.{A}": state[A] is nxt[A], f"next.{A} === fixed.{A}": nxt[A] is fixed[A],
               f"state.{F} === next.{F}": state[F] == nxt[F]}
    out.append(" ".join(_js(cmp_val[p]) for p in picks))

    # --- показанный код ----------------------------------------------------------------------------------------
    body = "cached = arr.length;" if kind == "len" else "cached = arr[arr.length - 1];"
    body = body.replace("cached", cv)
    mut = [op_code, f'next.{F} = "{f1}";']
    if rng.random() < 0.35:
        mut.reverse()
    lines = [f"let {lv} = null, {cv} = null, {kv} = 0;",
             f"const {fn} = (arr) => {{",
             f"  if (arr !== {lv}) {{ {kv}++; {lv} = arr; {body} }}",
             f"  return {cv};",
             "};",
             f"const state = {{ {F}: \"{f0}\", {A}: [{', '.join(_lit(e) for e in init)}] }};",
             f"console.log({fn}(state.{A}));",
             "const next = { ...state };",
             *mut,
             f"console.log({fn}(next.{A}), {', '.join(extra11)});",
             f"const fixed = {{ ...{src}, {A}: {upd_code} }};",
             f"console.log({fn}(fixed.{A}), {kv}" + (f", fixed.{F});" if with_ff else ");"),
             f"console.log({', '.join(picks)});"]
    code = "\n".join(lines)
    key = "\n".join(out)

    what = "длину" if kind == "len" else "последний элемент"
    op_txt = {"push1": "push", "push2": "push", "unshift": "unshift", "pop": "pop"}[op]
    src_txt = (f"из state, а state.{A} — тот же мутированный массив" if src == "state" else "из next")
    actual = _js(len(nxt[A]) if kind == "len" else nxt[A][-1])
    what_nom = "длина" if kind == "len" else "последний элемент"
    stale_txt = (f"запомненное {stale}, хотя сейчас {what_nom} массива — {actual}" if actual != stale else
                 f"запомненное {stale} (совпадает с текущим только случайно)")
    expl = (f"Селектор {fn} запоминает массив и его {what} и пересчитывает только при новой ссылке. "
            f"1) {fn}(state.{A}) → {first_val} (вызовов 1). "
            f"2) {{ ...state }} копирует только верхний уровень: next.{A} — тот же массив, что state.{A}, поэтому "
            f"{op_txt} меняет и state.{A} (теперь длина {len(state[A])}), а next.{F} = \"{f1}\" у state поле не "
            f"трогает (state.{F} = \"{state[F]}\"). Ссылка на массив не изменилась — селектор не пересчитывает "
            f"и возвращает {stale_txt}; строка: «{out[1]}». "
            f"3) fixed строится {src_txt}; {upd_code} создаёт НОВЫЙ массив ({', '.join(_js(e) for e in new_arr)}), "
            f"селектор пересчитывает → {v13}, вызовов {memo['calls']} (аргументы console.log вычисляются слева "
            f"направо); строка: «{out[2]}». "
            f"4) state === next — false (новый объект), state.{A} === next.{A} — true (общий массив), "
            f"next.{A} === fixed.{A} — false"
            + (f", state.{F} === next.{F} — false (поле переприсвоено только у next)"
               if f"state.{F} === next.{F}" in picks else "")
            + (f", state.{A}.length — {len(state[A])} (мутация через общий массив)"
               if f"state.{A}.length" in picks else "")
            + f"; строка: «{out[3]}». Вывод:\n{key}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=key, explanation=expl, context=ctx,
                          params={"kind": kind, "op": op, "src": src, "upd": upd, "init": init},
                          language="javascript")
