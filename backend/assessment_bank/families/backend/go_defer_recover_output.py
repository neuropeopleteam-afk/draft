"""backend.go.defer_recover_output — predict_output: defer, panic/recover и именованные результаты.

Один подтип: функция с именованными результатами, циклом из отложенных печатей (LIFO), отложенной
печатью с аргументом, вычисленным в момент defer, и отложенным замыканием с recover, которое меняет
результаты после return или после паники. Функция вызывается дважды: без паники и с паникой.
Ключ — независимая модель порядка отложенных вызовов; сверка исполнением показанного кода.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.go.defer_recover_output"

# (контекст, имя функции, аргумент, сообщение паники)
CONTEXTS = [("расчёт скидки", "discount", "sum", "слишком большая сумма"),
            ("импорт строк CSV", "importRows", "rows", "слишком много строк"),
            ("резерв мест", "reserve", "seats", "мест не хватает"),
            ("пакетная рассылка", "sendBatch", "size", "превышен лимит пакета"),
            ("расчёт штрафа", "penalty", "days", "срок вне диапазона")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, arg, msg = rng.choice(CONTEXTS)
    loops = rng.randint(2, 3)
    add = rng.randint(2, 9)
    bump = rng.randint(1, 5)
    mul = rng.randint(2, 4)
    fallback = rng.choice([-1, 0, 100])
    limit = rng.randint(20, 60)
    ok_arg = rng.randint(3, limit)
    bad_arg = rng.randint(limit + 1, limit + 40)
    label = rng.choice(["step", "close", "cleanup"])
    order = rng.choice(["ok_first", "bad_first"])
    code_lines = [
        "package main", "", 'import "fmt"', "",
        f"func {fn}({arg} int) (result int, err error) {{",
        "\tdefer func() {",
        "\t\tif r := recover(); r != nil {",
        '\t\t\terr = fmt.Errorf("recovered: %v", r)',
        f"\t\t\tresult = {fallback}",
        "\t\t}",
        f"\t\tresult += {bump}",
        "\t}()",
        f"\tfor i := 1; i <= {loops}; i++ {{",
        f'\t\tdefer fmt.Println("{label}", i)',
        "\t}",
        f"\tx := {arg}",
        '\tdefer fmt.Println("x =", x)',
        f"\tx += {add}",
        f"\tif {arg} > {limit} {{",
        f'\t\tpanic("{msg}")',
        "\t}",
        f"\treturn x * {mul}, nil",
        "}", "",
        "func main() {",
    ]
    calls = [ok_arg, bad_arg] if order == "ok_first" else [bad_arg, ok_arg]
    out: list[str] = []
    first = True
    for v in calls:
        code_lines.append(f"\tr, err {':=' if first else '='} {fn}({v})")
        code_lines.append("\tfmt.Println(r, err)")
        first = False
        # модель: отложенные — в обратном порядке: x =, label loops..1, затем замыкание
        out.append(f"x = {v}")
        out += [f"{label} {i}" for i in range(loops, 0, -1)]
        if v > limit:
            out.append(f"{fallback + bump} recovered: {msg}")
        else:
            out.append(f"{(v + add) * mul + bump} <nil>")
    code_lines.append("}")
    code = "\n".join(code_lines) + "\n"
    expected = "\n".join(out)
    checks = [Check(name="run", runner="go", program=code, expect="stdout_equals", expected_stdout=expected)]
    stem = (f"Функция на Go ({ctx}) использует defer и recover. Что выведет программа? "
            f"Запишите вывод построчно точно в формате программы.")
    why = (f"Отложенные вызовы выполняются в обратном порядке: сначала печать x (аргумент вычислен в момент "
           f"defer, поэтому x = {arg} без +{add}), затем цикл от {loops} к 1, последним — замыкание с recover. "
           f"Оно выполняется и после return, и после паники: при панике ставит result = {fallback} и err, а "
           f"затем всегда прибавляет {bump} к именованному результату.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"loops": loops, "order": order, "limit": limit})
