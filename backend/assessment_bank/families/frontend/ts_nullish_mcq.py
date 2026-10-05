"""frontend.ts.nullish_mcq — mcq_concept: `||` против `??` и значения по умолчанию в TypeScript."""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.ts.nullish_mcq"

FIELDS = [  # (поле, тип TS, значение по умолчанию, возможные входные значения)
    ("pageSize", "number | null", 20, [0, None, "missing", 50]),
    ("title", "string | null", "Без названия", ["", None, "missing", "Отчёт"]),
    ("showArchived", "boolean", True, [False, "missing", True]),
    ("retries", "number", 3, [0, "missing", 5]),
    ("currency", "string", "RUB", ["", "missing", "USD"]),
]
CTX = ["таблица заказов", "виджет отчёта", "настройки уведомлений", "список задач"]


def _js(v):
    return "null" if v is None else json.dumps(v, ensure_ascii=False)


def _eval(op, v, default):
    if v == "missing" or v is None:
        return default
    if op == "||" and v in (0, "", False) and not (v is True):
        return default
    return v


def _s(v):
    return {True: "true", False: "false"}.get(v, str(v)) if isinstance(v, bool) else str(v)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fields = rng.sample(FIELDS, 3)
    ops = [rng.choice(["||", "??"]) for _ in fields]
    if len(set(ops)) == 1:
        ops[rng.randrange(3)] = "??" if ops[0] == "||" else "||"
    vals = []
    for f in fields:
        v = rng.choice(f[3])
        vals.append(v)
    falsy = lambda x: x is False or (not isinstance(x, bool) and x in (0, ""))
    # хотя бы два поля с «ложным, но не null» значением — иначе операторы неразличимы
    for i in rng.sample(range(3), 3):
        if sum(falsy(v) for v in vals) >= 2:
            break
        if not falsy(vals[i]):
            vals[i] = [x for x in fields[i][3] if falsy(x)][0]
    fn = rng.choice(["resolveOptions", "withDefaults", "normalizeConfig"])
    iface = rng.choice(["ListOptions", "WidgetConfig", "Settings"])
    decl = [f"interface {iface} {{"] + [f"  {f[0]}?: {f[1]};" for f in fields] + ["}", ""]
    body = [f"function {fn}(opts: {iface}): string {{"]
    body_js = [f"function {fn}(opts) {{"]
    for f, op in zip(fields, ops):
        line = f"  const {f[0]} = opts.{f[0]} {op} {_js(f[2])};"
        body.append(line)
        body_js.append(line)
    ret = "  return `" + "|".join("${" + f[0] + "}" for f in fields) + "`;"
    body += [ret, "}", ""]
    body_js += [ret, "}", ""]
    arg = "{ " + ", ".join(f"{f[0]}: {_js(v)}" for f, v in zip(fields, vals) if v != "missing") + " }"
    call = f"console.log({fn}({arg}));"
    code = "\n".join(decl + body + [call])
    program = "\n".join(body_js + [call])
    res = lambda opset: "|".join(_s(_eval(o, v, f[2])) for f, o, v in zip(fields, opset, vals))
    correct = res(ops)
    alts = [res(["||"] * 3), res(["??"] * 3)] + [res([("??" if o == "||" else "||") if j == i else o
                                                         for j, o in enumerate(ops)]) for i in range(3)]
    flip = lambda o: "??" if o == "||" else "||"
    alts.append(res([flip(o) for o in ops]))
    alts += [res([flip(o) if j != i else o for j, o in enumerate(ops)]) for i in range(3)]
    alts.append("|".join(_s(f[2]) for f in fields))
    # «ложные» значения, приведённые к строке по-другому — типичная ошибка чтения шаблонной строки
    alts.append("|".join({"": '""', 0: "0", False: "false"}.get(x, x) if not isinstance(x, bool) or x is False
                         else x for x in correct.split("|")))
    alts.append("|".join("undefined" if v == "missing" else _s(v) if v is not None else "null"
                         for v in vals))
    distr = []
    for a in alts:
        if a != correct and a not in distr:
            distr.append(a)
    rng.shuffle(distr)
    distr = distr[:3]
    if len(distr) < 3:
        raise RuntimeError("мало дистракторов")
    opts, key = make_options(rng, (correct, None), [(d, None) for d in distr])
    stem = (f"Что выведет код ({rng.choice(CTX)})? Поля, не переданные в объекте, отсутствуют "
            f"(undefined).")
    ak = AnswerKey(kind="option", value=key,
                   explanation="`||` подставляет значение по умолчанию для любого ложного значения "
                               "(0, '', false, null, undefined), `??` — только для null и undefined.")
    checks = [Check(name="stdout", runner="node", program=program, expect="stdout_equals",
                    expected_stdout=correct, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=iface, verification="execution", checks=checks,
                         display_code_note="Для проверки ключа аннотации типов удалены, код "
                                           "исполняется как JavaScript в Node.js.",
                         params={"ops": ops})
