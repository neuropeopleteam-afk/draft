"""backend.go.context_background_bug — find_bug: context.Background() рвёт цепочку отмены.

Функция создаёт context.WithTimeout от входящего ctx, но во внутреннем вызове передаёт
context.Background() (или context.TODO()): тайм-аут и отмена клиента до медленного вызова не доходят,
запрос висит, горутины и соединения копятся. Один подтип дефекта; варьируются контекст, имена,
порядок функций, служебные строки. Строка дефекта не постоянна.
Проверка исполнением (go -race): при тайм-ауте 10–30 мс медленный вызов (300–450 мс) должен прерваться с
context.DeadlineExceeded быстрее 150 мс — дефектный код не укладывается, исправленный укладывается.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.go.context_background_bug"

# (контекст, внешняя функция, внутренняя, параметр, что получает)
CONTEXTS = [("расчёт корзины", "quoteCart", "fetchPrice", "sku", "цену товара"),
            ("проверка остатков", "checkStock", "fetchStock", "item", "остаток на складе"),
            ("скоринг заявок", "scoreApplication", "fetchBureau", "client", "ответ кредитного бюро"),
            ("стоимость доставки", "deliveryCost", "fetchTariff", "zone", "тариф зоны"),
            ("лента рекомендаций", "buildFeed", "fetchItem", "id", "карточку товара")]


def _code(c, bad: str | None, helper_first: bool, log_line: bool, extra_const: bool, mul: int, budget: int,
          slow: int, acc: str) -> tuple[str, int]:
    ctx_name, outer, inner, arg, _what = c
    inner_fn = [f"func {inner}(ctx context.Context, {arg} string) (int, error) {{",
                "\tselect {",
                "\tcase <-time.After(slowCall):",
                f"\t\treturn len({arg}) * {mul}, nil",
                "\tcase <-ctx.Done():",
                "\t\treturn 0, ctx.Err()",
                "\t}",
                "}"]
    call_ctx = bad or "ctx"
    outer_fn = [f"func {outer}(ctx context.Context, {arg}s []string) (int, error) {{",
                "\tctx, cancel := context.WithTimeout(ctx, budget)",
                "\tdefer cancel()",
                f"\t{acc} := 0",
                f"\tfor _, {arg} := range {arg}s {{"]
    if log_line:
        outer_fn.append(f'\t\tlog.Printf("{inner} %s", {arg})')
    outer_fn += [f"\t\tv, err := {inner}({call_ctx}, {arg})",
                 "\t\tif err != nil {",
                 "\t\t\treturn 0, err",
                 "\t\t}",
                 f"\t\t{acc} += v",
                 "\t}",
                 f"\treturn {acc}, nil",
                 "}"]
    imports = ["\t\"context\"", "\t\"log\"", "\t\"time\""] if log_line else ["\t\"context\"", "\t\"time\""]
    head = ["package main", "", "import ("] + imports + [")", ""]
    consts = ["const (", f"\tslowCall = {slow} * time.Millisecond", f"\tbudget   = {budget} * time.Millisecond"]
    if extra_const:
        consts.append("\tmaxItems = 50")
    consts += [")", ""]
    blocks = (inner_fn + [""] + outer_fn) if helper_first else (outer_fn + [""] + inner_fn)
    lines = head + consts + blocks
    key = next(i for i, l in enumerate(lines, 1) if l.startswith(f"\t\tv, err := {inner}("))
    return "\n".join(lines) + "\n", key


def _harness(code: str, outer: str) -> str:
    code = code.replace('import (\n\t"context"\n', 'import (\n\t"context"\n\t"errors"\n\t"fmt"\n\t"io"\n', 1)
    if '\t"log"\n' not in code:
        code = code.replace('\t"time"\n)', '\t"log"\n\t"time"\n)', 1)
    return code + (
        "\nfunc main() {\n\tlog.SetOutput(io.Discard)\n\tstart := time.Now()\n"
        f"\t_, err := {outer}(context.Background(), []string{{\"a1\", \"b22\"}})\n"
        "\tel := time.Since(start)\n"
        "\tif errors.Is(err, context.DeadlineExceeded) && el < 150*time.Millisecond {\n"
        "\t\tfmt.Println(\"RESULT: PASS\")\n\t} else {\n"
        "\t\tfmt.Println(\"RESULT: FAIL\", err, el > 150*time.Millisecond)\n\t}\n}\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx_name, outer, inner, arg, what = c
    bad = rng.choice(["context.Background()", "context.TODO()"])
    helper_first = rng.random() < 0.5
    log_line = rng.random() < 0.5
    extra_const = rng.random() < 0.5
    mul = rng.randint(2, 40)
    budget = rng.choice([10, 15, 20, 25, 30])
    slow = rng.choice([300, 350, 400, 450])
    acc = rng.choice(["total", "sum", "acc", "result"])
    buggy, key = _code(c, bad, helper_first, log_line, extra_const, mul, budget, slow, acc)
    fixed, _ = _code(c, None, helper_first, log_line, extra_const, mul, budget, slow, acc)
    assert changed_lines(buggy, fixed) == {key}
    checks = [Check(name="buggy_fails", runner="go", program=_harness(buggy, outer), expect="fail",
                    embeds_display_code=False),
              Check(name="fixed_passes", runner="go", program=_harness(fixed, outer), expect="pass",
                    embeds_display_code=False)]
    stem = (f"Сервис ({ctx_name}) вызывает `{outer}` с бюджетом времени {budget} мс на весь запрос; `{inner}` "
            f"получает {what} от медленного внешнего сервиса. В продакшене запросы висят по {slow} мс на "
            f"каждый элемент, хотя тайм-аут задан, а при отмене запроса клиентом горутины продолжают ждать. "
            f"Укажите номер строки с ошибкой.")
    why = (f"Строка {key}: во внутренний вызов передан {bad} вместо ctx с тайм-аутом. Новый корневой "
           f"контекст не связан с родительским: ни тайм-аут WithTimeout, ни отмена клиента до {inner} не "
           f"доходят. Исправление — передать ctx.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx_name,
                         verification="execution", checks=checks, defect_type="context_detached",
                         display_code_note="Показанный код исполняется с добавленными импортами "
                                           "(errors, fmt, io) и функцией main с тестом.",
                         params={"fixed_code": fixed, "bad": bad})
