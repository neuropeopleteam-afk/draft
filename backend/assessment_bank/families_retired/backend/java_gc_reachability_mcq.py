"""backend.java.gc_reachability_mcq — mcq_concept: сколько объектов доступны для сборки мусора в отмеченной точке.

Фрагмент Java создаёт 3–5 объектов `Node` и переназначает ссылки (локальные переменные и поле `next`).
Объект доступен для сборки, когда он недостижим ни от одной локальной переменной напрямую или через
цепочку полей. Ловушки: обнулённая переменная — не значит недостижимый объект (на него может ссылаться
поле другого объекта); объект без «своей» переменной может быть достижим через поле; цикл ссылок между
недостижимыми объектами сборке не мешает. Один подтип; варьируются число объектов и последовательность
операций. Ключ проверяется исполнением модели достижимости (обход графа ссылок от локальных переменных).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.gc_reachability_mcq"

CONTEXTS = [("связный список задач", "Task"), ("цепочка обработчиков", "Handler"), ("узлы маршрута", "Hop"),
            ("кэш страниц", "Page"), ("очередь сообщений", "Msg")]

MODEL = '''OPS = {ops!r}
N_OBJECTS, OPTIONS = {n}, {options!r}

vars, field = {{}}, {{}}
for op in OPS:
    kind, *args = op
    if kind == "new":
        vars[args[0]] = args[1]            # Node x = new Node("X")
    elif kind == "var_null":
        vars[args[0]] = None               # x = null
    elif kind == "var_assign":
        vars[args[0]] = vars[args[1]]      # x = y
    elif kind == "field_set":
        field[vars[args[0]]] = vars[args[1]]   # x.next = y
    elif kind == "field_null":
        field[vars[args[0]]] = None        # x.next = null

reachable, stack = set(), [o for o in vars.values() if o is not None]
while stack:
    o = stack.pop()
    if o in reachable:
        continue
    reachable.add(o)
    if field.get(o) is not None:
        stack.append(field[o])
eligible = N_OBJECTS - len(reachable)
print(next(k for k, v in OPTIONS.items() if v == eligible))
'''


def _render(ops, cls: str) -> list[str]:
    out = []
    for kind, *a in ops:
        if kind == "new":
            out.append(f'{cls} {a[0]} = new {cls}("{a[1]}");')
        elif kind == "var_null":
            out.append(f"{a[0]} = null;")
        elif kind == "var_assign":
            out.append(f"{a[0]} = {a[1]};")
        elif kind == "field_set":
            out.append(f"{a[0]}.next = {a[1]};")
        elif kind == "field_null":
            out.append(f"{a[0]}.next = null;")
    return out


def _simulate(ops, n):
    vars_, field = {}, {}
    for kind, *a in ops:
        if kind == "new":
            vars_[a[0]] = a[1]
        elif kind == "var_null":
            vars_[a[0]] = None
        elif kind == "var_assign":
            vars_[a[0]] = vars_[a[1]]
        elif kind == "field_set":
            field[vars_[a[0]]] = vars_[a[1]]
        elif kind == "field_null":
            field[vars_[a[0]]] = None
    reach, stack = set(), [o for o in vars_.values() if o is not None]
    while stack:
        o = stack.pop()
        if o in reach:
            continue
        reach.add(o)
        if field.get(o) is not None:
            stack.append(field[o])
    nulled_vars = sum(1 for k, *a in ops if k == "var_null")
    held = {o for o in vars_.values() if o is not None}
    return n - len(reach), nulled_vars, n - len(held)


def _build(rng):
    n = rng.randint(3, 5)
    names = ["a", "b", "c", "d", "e"][:n]
    labels = ["A", "B", "C", "D", "E"][:n]
    ops = [("new", v, l) for v, l in zip(names, labels)]
    # цепочка полей: каждый узел ссылается на следующий (частично)
    for i in range(n - 1):
        if rng.random() < 0.8:
            ops.append(("field_set", names[i], names[i + 1]))
    if rng.random() < 0.4:  # цикл: последний → первый или в середину
        ops.append(("field_set", names[-1], rng.choice(names[:-1])))
    k = rng.randint(2, 4)
    for _ in range(k):
        kind = rng.choice(["var_null", "var_null", "var_assign", "field_null", "field_set"])
        if kind == "var_null":
            ops.append(("var_null", rng.choice(names)))
        elif kind == "var_assign":
            x, y = rng.sample(names, 2)
            ops.append(("var_assign", x, y))
        else:
            # поле можно менять только у переменной, которая сейчас не null
            live = _live_vars(ops)
            if not live:
                continue
            x = rng.choice(live)
            if kind == "field_null":
                ops.append(("field_null", x))
            else:
                ops.append(("field_set", x, rng.choice(names)))
    return n, ops


def _live_vars(ops):
    vars_ = {}
    for kind, *a in ops:
        if kind == "new":
            vars_[a[0]] = a[1]
        elif kind == "var_null":
            vars_[a[0]] = None
        elif kind == "var_assign":
            vars_[a[0]] = vars_[a[1]]
    return [v for v, o in vars_.items() if o is not None]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cls = rng.choice(CONTEXTS)
    for _ in range(200):
        n, ops = _build(rng)
        # field_set/field_null через переменную, равную null, в Java дал бы NPE — такие варианты отбрасываем
        ok = True
        vars_ = {}
        for kind, *a in ops:
            if kind == "new":
                vars_[a[0]] = a[1]
            elif kind == "var_null":
                vars_[a[0]] = None
            elif kind == "var_assign":
                vars_[a[0]] = vars_[a[1]]
            elif kind in ("field_set", "field_null") and vars_.get(a[0]) is None:
                ok = False
        if not ok:
            continue
        eligible, nulled, unheld = _simulate(ops, n)
        # дистракторы по типичным ошибкам; все четыре значения должны различаться
        cands = [nulled, unheld, eligible + 1 if eligible + 1 <= n else eligible - 1, eligible - 1 if eligible > 0 else eligible + 2]
        distractors = []
        for c in cands:
            if 0 <= c <= n and c != eligible and c not in distractors:
                distractors.append(c)
            if len(distractors) == 3:
                break
        if len(distractors) == 3 and 1 <= eligible <= n - 1:
            break
    else:
        raise AssertionError("не удалось построить вариант")
    body = _render(ops, cls)
    code = "\n".join([f"final class {cls} {{", "    final String name;", f"    {cls} next;", "",
                      f"    {cls}(String name) {{", "        this.name = name;", "    }", "}", "", "",
                      "class Demo {", "    static void run() {"] + [f"        {l}" for l in body] +
                     ["        // здесь", "    }", "}"]) + "\n"
    word = lambda k: "объект" if k % 10 == 1 and k % 100 != 11 else ("объекта" if 2 <= k % 10 <= 4 else "объектов")
    texts = {eligible: f"{eligible} {word(eligible)}"} | {d: f"{d} {word(d)}" for d in distractors}
    opts, key = make_options(rng, (texts[eligible], None), [(texts[d], None) for d in distractors])
    mapping = {o.id: next(v for v, t in texts.items() if t == o.text) for o in opts}
    program = MODEL.format(ops=ops, n=n, options=mapping)
    checks = [Check(name="reachability", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=key, embeds_display_code=False)]
    stem = (f"Java ({ctx}). В методе `run()` создаются {n} объектов `{cls}`. Сколько из них доступны для сборки "
            f"мусора в точке `// здесь` (при условии, что JIT не сокращает время жизни переменных)?")
    why = (f"Объект доступен для сборки, когда он недостижим от локальных переменных — ни напрямую, ни через "
           f"цепочку полей `next`. Обнулённая переменная не делает объект мусором, если на него ссылается поле "
           f"другого достижимого объекта; и наоборот, объект без «своей» переменной жив, пока к нему ведёт поле. "
           f"Обход ссылок от переменных даёт {n - eligible} достижимых, значит для сборки доступны {eligible}.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Показанный Java-код не исполняется: ключ даёт модель достижимости "
                                           "(обход графа ссылок от локальных переменных) по тем же операциям.",
                         params={"n": n, "eligible": eligible, "ops": ops})
