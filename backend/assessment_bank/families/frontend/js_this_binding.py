"""frontend.js.this_binding — predict_output: потеря this у методов, bind, стрелочные поля класса."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.this_binding"

# (класс, поле-имя, поле-счётчик, метод увеличения, шаг, метод сброса, контекст)
CLASSES = [
    ("Timer", "name", "ticks", "tick", 1, "reset", "таймер обратного отсчёта"),
    ("Cart", "owner", "items", "add", 1, "clear", "корзина интернет-магазина"),
    ("Player", "nick", "score", "hit", 10, "restart", "браузерная игра"),
    ("Badge", "title", "unread", "bump", 1, "markRead", "счётчик уведомлений"),
    ("Upload", "file", "parts", "push", 2, "cancel", "загрузчик файлов"),
]
NAMES = ["a", "b", "x", "main", "demo", "web"]
OTHER = ["tmp", "copy", "alt", "spare"]

# Виды вызова: что передаётся в run(...)
KINDS = ["direct", "detached", "arrow", "bind_self", "bind_other", "call", "rebind", "arrow_call",
         "borrow"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    cls, fname, fcnt, inc, step, reset, ctx = rng.choice(CLASSES)
    name = rng.choice(NAMES)
    oname = rng.choice([n for n in OTHER])
    start = rng.choice([0, 1, 2, 3])
    ostart = rng.choice([5, 7, 10, 20])
    # 4 вызова: хотя бы один «потерянный this» и хотя бы одна ловушка уровня Middle
    for _ in range(100):
        kinds = rng.sample(KINDS, 4)
        if "detached" in kinds and any(k in kinds for k in ("rebind", "arrow_call", "borrow",
                                                              "bind_other")):
            break
    inst = "obj"
    lines = ["'use strict';",
             f"class {cls} {{",
             f"  constructor({fname}, {fcnt}) {{ this.{fname} = {fname}; this.{fcnt} = {fcnt}; }}",
             f"  {inc}() {{ this.{fcnt} += {step}; return `${{this.{fname}}}:${{this.{fcnt}}}`; }}",
             f"  {reset} = () => {{ this.{fcnt} = 0; return `${{this.{fname}}}:0`; }};",
             "}",
             "function run(fn) {",
             "  try { return fn(); } catch (e) { return e.name; }",
             "}",
             f"const {inst} = new {cls}('{name}', {start});",
             f"const {inc}Ref = {inst}.{inc};"]
    if "borrow" in kinds:
        lines.append(f"const {oname} = {{ {fname}: '{oname}', {fcnt}: {ostart}, {inc}: {inst}.{inc} }};")
    st = {"main": start, "other": ostart}
    outs = []
    lit = f"{{ {fname}: 'lit', {fcnt}: {ostart} }}"
    for k in kinds:
        if k == "direct":
            arg = f"() => {inst}.{inc}()"
            st["main"] += step
            outs.append(f"{name}:{st['main']}")
        elif k == "detached":
            arg = f"{inc}Ref"
            outs.append("TypeError")
        elif k == "arrow":
            arg = f"{inst}.{reset}"
            st["main"] = 0
            outs.append(f"{name}:0")
        elif k == "bind_self":
            arg = f"{inst}.{inc}.bind({inst})"
            st["main"] += step
            outs.append(f"{name}:{st['main']}")
        elif k == "bind_other":
            arg = f"{inc}Ref.bind({lit})"
            outs.append(f"lit:{ostart + step}")
        elif k == "call":
            arg = f"() => {inc}Ref.call({inst})"
            st["main"] += step
            outs.append(f"{name}:{st['main']}")
        elif k == "rebind":
            arg = f"{inc}Ref.bind({inst}).bind({lit})"
            st["main"] += step
            outs.append(f"{name}:{st['main']}")
        elif k == "arrow_call":
            arg = f"() => {inst}.{reset}.call({lit})"
            st["main"] = 0
            outs.append(f"{name}:0")
        else:  # borrow
            arg = f"() => {oname}.{inc}()"
            st["other"] += step
            outs.append(f"{oname}:{st['other']}")
        lines.append(f"console.log(run({arg}));")
    code = "\n".join(lines)
    out = "\n".join(outs)
    stem = (f"Класс `{cls}` ({ctx}) используется в обработчиках событий. Что выведет код в "
            f"Node.js 20? Если вызов завершается исключением, функция `run` возвращает имя "
            f"ошибки. Запишите все строки вывода по порядку.")
    why = {"direct": "вызов через объект — this = объект",
           "detached": "метод, извлечённый из объекта, вызывается без получателя: в строгом "
                       "режиме this = undefined → TypeError",
           "arrow": "стрелочное поле класса запоминает this экземпляра",
           "bind_self": "bind фиксирует this",
           "bind_other": "bind привязывает метод к другому объекту",
           "call": "call задаёт this явно",
           "rebind": "повторный bind не меняет уже привязанный this",
           "arrow_call": "у стрелочной функции свой this не задаётся через call — сбрасывается "
                         "счётчик экземпляра",
           "borrow": "метод, скопированный в другой объект, получает this этого объекта"}
    ak = AnswerKey(kind="output", value=out,
                   explanation="; ".join(why[k] for k in kinds) + ". Состояние экземпляра "
                               "меняется по ходу вызовов.")
    checks = [Check(name="stdout", runner="node", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"kinds": kinds})
