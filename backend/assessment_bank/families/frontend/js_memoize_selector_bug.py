"""frontend.js.memoize_selector_bug — find_bug: мемоизация селектора (memoizeOne) для рендера."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.memoize_selector_bug"

SELECTORS = [
    ("selectVisibleOrders", "orders, status", "orders.filter((o) => o.status === status)", "список заказов"),
    ("selectCheapProducts", "products, maxPrice", "products.filter((p) => p.price <= maxPrice)", "каталог товаров"),
    ("selectUnread", "messages, folder", "messages.filter((m) => m.folder === folder && !m.read)", "почтовый клиент"),
    ("selectTeamTasks", "tasks, assignee", "tasks.filter((t) => t.assignee === assignee)", "трекер задач"),
    ("selectActiveUsers", "users, role", "users.filter((u) => u.role === role && u.active)", "админ-панель"),
]
DECOYS = [["const byDate = (a, b) => a.createdAt - b.createdAt;"],
          ["const isEmptyList = (list) => !list || list.length === 0;"],
          ["function toIds(list) {", "  return list.map((x) => x.id);", "}"],
          ["const byTitle = (a, b) => a.title.localeCompare(b.title);"],
          ["const pluralRu = (n) => (n % 10 === 1 && n % 100 !== 11 ? 'запись' : 'записи');"]]
SYMPTOM = {
    "stale": ("после смены фильтра при тех же данных список на экране иногда не обновляется — "
              "показывается результат прошлого фильтра"),
    "recompute": ("фильтрация выполняется при каждом рендере, даже если ни данные, ни фильтр не "
                  "менялись: счётчик вызовов растёт, а дочерние компоненты под React.memo "
                  "перерисовываются, потому что каждый раз получают новый массив"),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sel, params, expr, ctx = rng.choice(SELECTORS)
    la, lr = rng.choice([("lastArgs", "lastResult"), ("prevArgs", "cached"), ("savedArgs", "savedResult"),
                         ("memoArgs", "memoResult")])
    mname = rng.choice(["memoizeOne", "memoizeLast"])
    cmp_is = rng.random() < 0.5
    cmp = (lambda a, b: f"Object.is({a}, {b})") if cmp_is else (lambda a, b: f"{a} === {b}")
    subtype = rng.choice(["some", "return_fn", "length_neg", "compare_first"])
    flag = rng.choice(["same", "hit", "unchanged"])
    good = {
        "same3": f"      args.every((a, i) => {cmp('a', la + '[i]')});",
        "same2": f"      args.length === {la}.length &&",
        "ret": f"    if ({flag}) return {lr};",
    }
    bad = dict(good)
    if subtype == "some":
        bad["same3"] = f"      args.some((a, i) => {cmp('a', la + '[i]')});"
    elif subtype == "compare_first":
        bad["same3"] = f"      args.every((a) => {cmp('a', la + '[0]')});"
    elif subtype == "length_neg":
        bad["same2"] = f"      args.length !== {la}.length &&"
    else:
        bad["ret"] = f"    if ({flag}) return fn(...args);"

    def body(g):
        return [f"function {mname}(fn) {{", f"  let {la} = null;", f"  let {lr};",
                "  return (...args) => {", f"    const {flag} = {la} !== null &&", g["same2"],
                g["same3"], g["ret"], f"    {lr} = fn(...args);", f"    {la} = args;",
                f"    return {lr};", "  };", "}", "",
                f"const {sel} = {mname}(({params}) =>", f"  {expr});"]
    decoy = rng.choice(DECOYS)
    decoy_first = rng.random() < 0.4

    def assemble(g):
        b = body(g)
        return "\n".join((decoy + [""] + b) if decoy_first else (b + [""] + decoy))
    buggy, fixed = assemble(bad), assemble(good)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    test = """
        let calls = 0;
        const sel = MNAME((items, q) => { calls += 1; return items.filter((x) => x.k === q); });
        const items = [{ k: 'a' }, { k: 'b' }, { k: 'a' }];
        const r1 = sel(items, 'a');
        const r2 = sel(items, 'a');
        __assert(r1 === r2 && calls === 1, 'повторный вызов с теми же аргументами пересчитан');
        const r3 = sel(items, 'b');
        __assert(r3.length === 1 && calls === 2, 'смена фильтра не пересчитана');
        const items2 = [...items, { k: 'b' }];
        const r4 = sel(items2, 'b');
        __assert(r4.length === 2 && calls === 3, 'новые данные не пересчитаны');
        __assert(sel(items2, 'b') === r4 && calls === 3, 'кэш последнего вызова не работает');
    """
    test = test.replace("MNAME", mname)
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    symptom = SYMPTOM["stale" if subtype == "some" else "recompute"]
    stem = (f"Селектор `{sel}` ({ctx}) вызывается в теле React-компонента при каждом рендере и "
            f"мемоизирован через `{mname}`: результат должен пересчитываться, только если "
            f"изменился хотя бы один аргумент (сравнение по ссылке). Жалоба: {symptom}. Укажите "
            f"номер строки с ошибкой.")
    why = {"some": "some вместо every: совпадения одного аргумента достаточно, чтобы вернуть "
                   "старый результат",
           "compare_first": "каждый аргумент сравнивается с первым сохранённым, а не со своим "
                            "по индексу — совпадение почти невозможно",
           "length_neg": "условие длины перевёрнуто: при том же числе аргументов кэш никогда "
                         "не срабатывает",
           "return_fn": "при попадании в кэш функция всё равно вызывается заново и возвращает "
                        "новый массив"}
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {why[subtype]}.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="memo_cache_check",
                         params={"fixed_code": fixed, "subtype": subtype})
