"""frontend.js.closure_var — find_bug: var в цикле и замыкания обработчиков."""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.closure_var"

SCENARIOS = [
    ("createTabHandlers", "tabs", "tab", "Открыта вкладка", ["Профиль", "Заказы", "Настройки", "Помощь"], "личный кабинет"),
    ("createMenuHandlers", "items", "item", "Выбран пункт", ["Новый", "Открыть", "Сохранить", "Экспорт"], "редактор"),
    ("createFilterHandlers", "filters", "filter", "Фильтр", ["Цена", "Бренд", "Рейтинг", "Наличие"], "каталог"),
    ("createStepHandlers", "steps", "step", "Шаг", ["Адрес", "Доставка", "Оплата", "Подтверждение"], "оформление заказа"),
]
DECOYS = [
    ["function formatTitle(title) {", "  return title.trim().replace(/\\s+/g, ' ');", "}"],
    ["function clamp(value, min, max) {", "  return Math.min(Math.max(value, min), max);", "}"],
    ["const isEmpty = (list) => !list || list.length === 0;"],
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, coll, one, msg, labels, ctx = rng.choice(SCENARIOS)
    labels = rng.sample(labels, rng.randint(3, 4))
    use_index = rng.random() < 0.4
    body_ref = f"`{msg} ${{i + 1}}: ${{{coll}[i]}}`" if use_index else f"`{msg}: ${{{coll}[i]}}`"
    decoy = rng.choice(DECOYS)
    loop_bad = f"  for (var i = 0; i < {coll}.length; i++) {{"
    loop_good = f"  for (let i = 0; i < {coll}.length; i++) {{"
    main = [f"function {fn}({coll}, log) {{", "  const handlers = [];", "LOOP",
            f"    handlers.push(() => log({body_ref}));", "  }", "  return handlers;", "}"]
    decoy_first = rng.random() < 0.5
    pick = rng.randrange(len(labels))
    usage = ["", f"const handlers = {fn}({json.dumps(labels, ensure_ascii=False)}, (m) => console.log(m));",
             f"handlers[{pick}]();"]

    def assemble(loop):
        m = [loop if l == "LOOP" else l for l in main]
        return ((decoy + [""] + m) if decoy_first else (m + [""] + decoy)) + usage
    buggy, fixed = "\n".join(assemble(loop_bad)), "\n".join(assemble(loop_good))
    key_line = buggy.splitlines().index(loop_bad) + 1
    assert changed_lines(buggy, fixed) == {key_line}
    expect = (f"{msg} {pick + 1}: {labels[pick]}" if use_index else f"{msg}: {labels[pick]}")
    test = (f"const out = [];\nconst hs = {fn}({json.dumps(labels, ensure_ascii=False)}, (m) => out.push(m));\n"
            f"hs[{pick}]();\n__assert(out[0] === {json.dumps(expect, ensure_ascii=False)}, 'got ' + out[0]);")
    wrong = (f"{msg} {len(labels) + 1}: undefined" if use_index else f"{msg}: undefined")
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Функция `{fn}` ({ctx}) создаёт обработчики кликов для элементов `{coll}`. Вызов "
            f"`handlers[{pick}]()` должен вывести `{expect}`, но выводит `{wrong}`. Укажите номер "
            f"строки, в которой находится причина ошибки.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: `var` создаёт одну переменную i на всю функцию; "
                               "к моменту клика цикл завершён и i равна длине массива. `let` "
                               "создаёт новую привязку на каждой итерации.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="closure_loop_var",
                         params={"fixed_code": fixed, "use_index": use_index})
