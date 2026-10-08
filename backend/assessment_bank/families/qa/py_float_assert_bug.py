"""qa.pytest.float_assert_bug — find_bug: точное сравнение float в тесте.

Лёгкое семейство у порога Junior (грейд «Стажёр»): три коротких теста функции суммирования цен; в одном
ожидаемая сумма записана десятичной дробью, которая в double не представима точно (`0.1 + 0.2 != 0.3`),
и тест падает при верной реализации. Остальные сравнения точны (целые, половинки, пустой список) — это
строки-ловушки. Исправление — `pytest.approx(...)` в той же строке. Один подтип. Проверка исполнением:
дефектный тест красный на верной реализации; исправленный — зелёный на верной и ловит мутанта
(потерян последний элемент).
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import PYTEST_CAUGHT_TAIL, PYTEST_GREEN_TAIL, pytest_program
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.float_assert_bug"

# (контекст, модуль, функция, имя аргумента)
CONTEXTS = [("корзина", "cart", "cart_total", "prices"), ("счёт в кафе", "bill", "bill_total", "items"),
            ("расходы", "expenses", "sum_expenses", "amounts"), ("зарплатная ведомость", "payroll", "total_pay", "lines"),
            ("доставка", "shipping", "shipping_cost", "fees")]
EXACT_SETS = [([2.5, 2.5], "5.0"), ([1.5, 2.25], "3.75"), ([4.0, 6.0], "10.0"), ([0.5, 0.25, 0.25], "1.0"),
              ([3.0, 1.5, 0.5], "5.0"), ([10.0, 2.5], "12.5")]


def _inexact(rng):
    while True:
        n = rng.randint(2, 3)
        cents = [rng.randint(1, 999) for _ in range(n)]
        vals = [c / 100 for c in cents]
        total_cents = sum(cents)
        expected = total_cents / 100
        s = sum(vals)
        if s != expected and abs(s - expected) < 1e-9:
            txt = ", ".join(f"{c // 100}.{c % 100:02d}" for c in cents)
            exp_txt = f"{total_cents // 100}.{total_cents % 100:02d}"
            return txt, exp_txt


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, mod, fn, arg = rng.choice(CONTEXTS)
    bad_vals, bad_exp = _inexact(rng)
    exact_vals, exact_exp = rng.choice(EXACT_SETS)
    exact_txt = ", ".join(str(v) for v in exact_vals)
    tests = [
        ("test_two_items" if bad_vals.count(",") == 1 else "test_three_items",
         f"    assert {fn}([{bad_vals}]) == {bad_exp}", f"    assert {fn}([{bad_vals}]) == pytest.approx({bad_exp})"),
        ("test_empty", f"    assert {fn}([]) == 0", None),
        ("test_exact_fractions", f"    assert {fn}([{exact_txt}]) == {exact_exp}", None),
    ]
    rng.shuffle(tests)
    if tests[0][0] != "test_empty" and rng.random() < 0.5:
        tests.insert(0, ("test_single_item", f"    assert {fn}([9.99]) == 9.99", None))
    lines_b, lines_f = ["import pytest", "", f"from {mod} import {fn}", "", ""], ["import pytest", "", f"from {mod} import {fn}", "", ""]
    for name, line_b, line_f in tests:
        lines_b += [f"def {name}():", line_b, "", ""]
        lines_f += [f"def {name}():", line_f or line_b, "", ""]
    buggy = "\n".join(lines_b[:-2]) + "\n"
    fixed = "\n".join(lines_f[:-2]) + "\n"
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    mod_ok = {mod: f"def {fn}({arg}):\n    return sum({arg})\n"}
    mod_bad = {mod: f"def {fn}({arg}):\n    return sum({arg}[:-1])\n"}
    checks = [
        Check(name="buggy_red_on_correct", runner="python", expect="fail",
              program=pytest_program(buggy, PYTEST_GREEN_TAIL, mod_ok)),
        Check(name="fixed_green_on_correct", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_GREEN_TAIL, mod_ok)),
        Check(name="fixed_catches_mutant", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_CAUGHT_TAIL, mod_bad)),
    ]
    stem = (f"pytest ({ctx}). Функция `{fn}` складывает значения списка и реализована верно: `return sum({arg})`. "
            f"Один из тестов падает. Укажите номер строки с ошибкой в тестах.")
    why = (f"Строка {key}: сумма {bad_vals} в double не равна {bad_exp} точно — десятичные дроби вроде 0.1 не "
           f"представимы в двоичной системе, и накапливается погрешность порядка 1e-16. Сравнивать float нужно с "
           f"допуском: `pytest.approx({bad_exp})`. Остальные ожидания (целые, половинки, четверти, пустой список) "
           f"представимы точно, поэтому те сравнения верны.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="float_exact_equality",
                         display_code_note="Модуль с функцией подставляется перед тестами; pytest — совместимая обвязка "
                                           "песочницы (approx с допусками по умолчанию).",
                         params={"fixed_code": fixed, "bad": bad_vals})
