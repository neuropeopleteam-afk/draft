"""backend.java.gc_reachability_mcq — mcq_concept: сколько объектов доступны для сборки мусора в отмеченной точке.

Версия 2 (08.10): фиксированный сценарий вместо случайного графа. Версия 1 была выведена из выдачи 07.10: число
объектов, длина цепочки и тип операций менялись от варианта к варианту (σ варианта 1,88), а условие было
двусмысленным («если JIT не сокращает время жизни переменных»).

Теперь каждый вариант устроен одинаково:
  * ровно 4 объекта `Node` (переменные из набора a–d / p–s / …), каждый создаётся своей строкой;
  * ровно 6 переназначений в фиксированном порядке типов: три связи `x.next = y` (цепочка p1 → p2 → p3 → p4 в
    произвольном порядке имён), затем три обнуления `x = null` — остаётся одна переменная, которая держит второй или
    третий объект цепочки; других операций, циклов и присваиваний переменных нет;
  * в условии прямо сказано: все локальные переменные остаются корнями до конца метода;
  * ловушка одна и та же: обнулены три переменные, но объекты за оставшимся звеном достижимы по цепочке `next`;
    ответ — 1 или 2 объекта;
  * одна схема дистракторов: число обнулённых переменных (3), ключ ± 1 и запасные значения (первые три различных
    числа из списка). Число обнулённых переменных всегда отличается от ключа: в версии 2.0 оно было равно 2 и
    совпадало с ключом «2 объекта», из-за чего ответ «посчитать обнуления» засчитывался верным в части вариантов
    (панель 08.10: p 0,39 при ключе 2 и 0,17 при ключе 1 — неизоморфность).
Ключ проверяется исполнением модели достижимости (обход графа ссылок от локальных переменных) по тем же операциям.
"""
from __future__ import annotations

import itertools

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.gc_reachability_mcq"

CONTEXTS = [("связный список задач", "Task"), ("цепочка обработчиков", "Handler"), ("узлы маршрута", "Hop"),
            ("кэш страниц", "Page"), ("очередь сообщений", "Msg")]
NAMES = "abcd"
NAME_SETS = ["abcd", "pqrs", "wxyz", "mnop", "uvwx"]   # только имена переменных; структура сценария та же

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


def _simulate(ops):
    """(доступно для сборки, объектов без своей переменной, обнулённых/переназначенных, но живых) или None."""
    vars_, field, touched = {}, {}, set()
    for kind, *a in ops:
        if kind == "new":
            vars_[a[0]] = a[1]
        elif kind == "field_set":
            if vars_[a[0]] is None or vars_[a[1]] is None:
                return None
            field[vars_[a[0]]] = vars_[a[1]]
        elif kind == "var_null":
            if vars_[a[0]] is None:
                return None
            touched.add(vars_[a[0]])
            vars_[a[0]] = None
        else:  # var_assign
            if vars_[a[0]] is None or vars_[a[1]] is None or vars_[a[0]] == vars_[a[1]]:
                return None
            touched.add(vars_[a[0]])
            vars_[a[0]] = vars_[a[1]]
    reach, stack = set(), [o for o in vars_.values() if o is not None]
    while stack:
        o = stack.pop()
        if o in reach:
            continue
        reach.add(o)
        if field.get(o) is not None:
            stack.append(field[o])
    held = {o for o in vars_.values() if o is not None}
    return 4 - len(reach), 4 - len(held), len(touched & reach)


def _scenarios():
    """Все сценарии: цепочка p1→p2→p3→p4, затем три обнуления; остаётся переменная второго или третьего звена."""
    out = []
    for perm in itertools.permutations(NAMES):
        links = [("field_set", perm[i], perm[i + 1]) for i in range(3)]
        for keep in (perm[1], perm[2]):
            nulls = [v for v in NAMES if v != keep]
            for order in itertools.permutations(nulls):
                ops = [("new", v, v.upper()) for v in NAMES] + links + [("var_null", v) for v in order]
                r = _simulate(ops)
                if r and r[0] in (1, 2) and r[2] >= 1:
                    out.append((ops, r))
    return out


SCENARIOS = _scenarios()


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
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cls = rng.choice(CONTEXTS)
    ops, (eligible, unheld, _alive) = rng.choice(SCENARIOS)
    ren = dict(zip(NAMES, rng.choice(NAME_SETS)))
    ops = [("new", ren[o[1]], ren[o[1]].upper()) if o[0] == "new" else (o[0],) + tuple(ren[x] for x in o[1:])
           for o in ops]
    n = 4
    nulled = sum(1 for o in ops if o[0] == "var_null")
    pref = [nulled, unheld, eligible + 1, eligible - 1, eligible + 2, 0, 3, 4, 1, 2]
    distractors = []
    for v in pref:
        if 0 <= v <= n and v != eligible and v not in distractors:
            distractors.append(v)
        if len(distractors) == 3:
            break
    assert len(distractors) == 3
    body = _render([o for o in ops if o[0] != "new"], cls)
    news = _render([o for o in ops if o[0] == "new"], cls)
    code = "\n".join([f"final class {cls} {{", "    final String name;", f"    {cls} next;", "",
                      f"    {cls}(String name) {{", "        this.name = name;", "    }", "}", "",
                      "class Demo {", "    static void run() {"] + [f"        {l}" for l in news + body] +
                     ["        // здесь", "    }", "}"]) + "\n"
    word = lambda k: plural(k, "объект", "объекта", "объектов")
    texts = {eligible: f"{eligible} {word(eligible)}"} | {d: f"{d} {word(d)}" for d in distractors}
    opts, key = make_options(rng, (texts[eligible], None), [(texts[d], None) for d in distractors])
    mapping = {o.id: next(v for v, t in texts.items() if t == o.text) for o in opts}
    program = MODEL.format(ops=ops, n=n, options=mapping)
    checks = [Check(name="reachability", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=key, embeds_display_code=False)]
    stem = (f"Java ({ctx}). В методе `run()` создаются 4 объекта `{cls}`, затем выполняются 6 присваиваний. Сколько "
            f"из этих объектов доступны для сборки мусора в точке `// здесь`? Считайте, что все локальные переменные "
            f"остаются корнями до конца метода.")
    why = (f"Объект доступен для сборки, когда он недостижим от локальных переменных — ни напрямую, ни через "
           f"цепочку полей `next`. Обнулённая переменная не делает объект мусором, пока на него "
           f"ссылается поле достижимого объекта; и наоборот, объект без «своей» переменной жив, пока к нему ведёт "
           f"`next`. Обход ссылок от переменных даёт {n - eligible} достижимых из {n}, значит для сборки доступны "
           f"{eligible}.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Показанный Java-код не исполняется: ключ даёт модель достижимости "
                                           "(обход графа ссылок от локальных переменных) по тем же операциям.",
                         params={"n": n, "eligible": eligible, "ops": ops})
