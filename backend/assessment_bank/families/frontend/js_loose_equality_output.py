"""frontend.js.loose_equality_output — predict_output: `==` против `===` и приведение типов.

Лёгкое семейство у порога Junior (грейд «Стажёр»): 4–5 сравнений из фиксированного набора базовых пар
(строка/число, 0/false, null/undefined, пустая строка/0, одинаковые строки, 1/true), каждое печатается
`console.log`. Единственная ловушка — `==` приводит типы, `===` требует совпадения типа. Экзотические пары
(`[] == false`, `NaN`) не используются. Исполняется Node; ключ — независимая таблица в генераторе.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.loose_equality_output"

# (левый, правый, ==, ===)
PAIRS = [('"5"', "5", True, False), ('"0"', "0", True, False), ("0", "false", True, False),
         ("1", "true", True, False), ('""', "0", True, False), ("null", "undefined", True, False),
         ('"abc"', '"abc"', True, True), ("7", "7", True, True), ("null", "0", False, False),
         ('"1"', "true", True, False), ("undefined", "0", False, False), ('"a"', '"b"', False, False)]
CONTEXTS = ["форма входа", "фильтр каталога", "корзина", "настройки профиля", "валидация полей"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    pairs = rng.sample(PAIRS, rng.randint(4, 5))
    lines, outs = [], []
    for left, right, loose, strict in pairs:
        op = rng.choice(["==", "==", "==="])
        res = loose if op == "==" else strict
        # ровно половина строк показывает различие операторов: добавляем парную строку с другим оператором
        lines.append(f"console.log({left} {op} {right});")
        outs.append("true" if res else "false")
    if all(l.count("===") == 0 for l in lines):
        left, right, loose, strict = pairs[0]
        lines.append(f"console.log({left} === {right});")
        outs.append("true" if strict else "false")
    if not any("===" not in l for l in lines):
        left, right, loose, strict = pairs[-1]
        lines.append(f"console.log({left} == {right});")
        outs.append("true" if loose else "false")
    code = "\n".join(lines) + "\n"
    expected = "\n".join(outs)
    stem = (f"JavaScript ({ctx}). Что напечатает программа? Запишите вывод построчно (`true` или `false`), "
            f"как печатает `console.log`.")
    why = ("`==` приводит операнды к одному типу: строка с числом сравнивается как число, `false` и `true` — как "
           "0 и 1, `null == undefined` истинно, но `null` с числом не сравнивается. `===` без приведения: разные "
           "типы — всегда `false`, одинаковые тип и значение — `true`.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    checks = [Check(name="run", runner="node", program=code, expect="stdout_equals", expected_stdout=expected)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"n": len(lines)})
