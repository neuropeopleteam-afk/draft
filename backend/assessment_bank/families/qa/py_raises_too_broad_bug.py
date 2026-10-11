"""qa.pytest.raises_too_broad_bug — find_bug: `pytest.raises(Exception)` ловит не ту ошибку.

Порог Junior/Middle. Тест проверяет, что на недопустимом входе функция бросает понятную `ValueError`, но ожидает
любое исключение. После регрессии проверка входа пропала, функция падает дальше с `ZeroDivisionError`/`KeyError`/
`IndexError` — тест зелёный. Исправление в той же строке — ожидать конкретный класс. Один подтип; ловушки —
другие тесты с точными проверками. Порядок тестов меняется.
Проверка исполнением: с дефектом тесты зелёные и на правильном коде, и на мутанте; после исправления мутант пойман.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import PYTEST_CAUGHT_TAIL, PYTEST_GREEN_TAIL, pytest_program
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.raises_too_broad_bug"

# (контекст, модуль, функция, недопустимый вход, проверка, тело, исключение мутанта, генератор (вход, результат))
def _avg(rng):
    xs = [rng.randint(2, 5) for _ in range(rng.randint(2, 4))]
    xs[-1] += (-sum(xs)) % len(xs) if sum(xs) % len(xs) and xs[-1] + (-sum(xs)) % len(xs) <= 9 else 0
    return repr(xs), repr(sum(xs) / len(xs))


def _first(rng):
    xs = rng.sample(range(10, 99), rng.randint(2, 4))
    return repr(xs), repr(xs[0])


def _unit(rng):
    q = rng.randint(2, 8)
    return repr((q * rng.randint(20, 300), q)), None


def _share(rng):
    b = rng.choice([2, 4, 5, 8, 10])
    return repr((rng.randint(1, b), b)), None


def _zone(rng):
    return repr(rng.choice(["A1", "B2"])), None


CONTEXTS = [
    ("средний балл", "school.grades", "average", "[]", "if not xs:", "return sum(xs) / len(xs)", "ZeroDivisionError", _avg),
    ("первый заказ клиента", "shop.history", "first_order", "[]", "if not xs:", "return xs[0]", "IndexError", _first),
    ("цена за единицу", "shop.units", "unit_price", "(500, 0)", "if xs[1] == 0:", "return xs[0] / xs[1]",
     "ZeroDivisionError", _unit),
    ("доля выполненных задач", "tasks.stats", "done_share", "(0, 0)", "if xs[1] == 0:", "return xs[0] / xs[1]",
     "ZeroDivisionError", _share),
    ("тариф по зоне", "delivery.zones", "zone_tariff", "'Z9'", "if xs not in TARIFFS:", "return TARIFFS[xs]", "KeyError", _zone),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, module, fn, bad_in, cond, body, mut_exc, gen_ok = rng.choice(CONTEXTS)
    tariffs = {"A1": rng.randint(5, 30) * 10, "B2": rng.randint(31, 60) * 10}
    pre = f"TARIFFS = {tariffs!r}\n\n\n" if "TARIFFS" in body else ""
    ok_in, ok_out = gen_ok(rng)
    if ok_out is None:
        ns = {"TARIFFS": tariffs}
        exec(f"def _f(xs):\n    {body}\n", ns)
        ok_out = repr(ns["_f"](eval(ok_in)))
    msg = rng.choice(["empty input", "invalid input", "bad value"])
    impl = (pre + f"def {fn}(xs):\n    {cond}\n        raise ValueError({msg!r})\n    {body}\n")
    mutant = pre + f"def {fn}(xs):\n    {body}\n"
    bad = rng.choice(["    with pytest.raises(Exception):", "    with pytest.raises((ValueError, Exception)):",
                      "    with pytest.raises(BaseException):"])
    good = "    with pytest.raises(ValueError):"
    t_target = [f"def test_{rng.choice(['rejects_invalid', 'invalid_input_error', 'bad_input_raises'])}():", "TARGET",
                f"        {fn}({bad_in})"]
    t_ok = [f"def test_{rng.choice(['regular_case', 'valid_input', 'happy_path'])}():", f"    assert {fn}({ok_in}) == {ok_out}"]
    t_type = ["def test_result_is_number():", f"    assert isinstance({fn}({ok_in}), (int, float))"]
    tests = [t_target, t_ok, t_type]
    rng.shuffle(tests)

    def assemble(line: str) -> str:
        out = ["import pytest", f"from {module} import {fn}"]
        for t in tests:
            out += ["", ""] + [line if x == "TARGET" else x for x in t]
        return "\n".join(out) + "\n"

    buggy, fixed = assemble(bad), assemble(good)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    okm, badm = {module: impl}, {module: mutant}
    checks = [
        Check(name="buggy_green_on_correct", runner="python", expect="pass", program=pytest_program(buggy, PYTEST_GREEN_TAIL, okm)),
        Check(name="buggy_misses_mutant", runner="python", expect="fail", program=pytest_program(buggy, PYTEST_CAUGHT_TAIL, badm)),
        Check(name="fixed_green_on_correct", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_GREEN_TAIL, okm)),
        Check(name="fixed_catches_mutant", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_CAUGHT_TAIL, badm)),
    ]
    stem = (f"Тесты модуля `{module}` ({ctx}). По контракту на недопустимом входе `{fn}` бросает `ValueError`, и API "
            f"отвечает 400. После рефакторинга на таком входе вылетает `{mut_exc}`, клиенты получают 500, но все тесты "
            f"ниже зелёные. Укажите номер строки теста, из-за которой регрессия не обнаружена.")
    why = (f"Строка {key}: тест ждёт любое исключение, поэтому `{mut_exc}` из сломанного кода тоже «подходит». "
           f"Контракт — конкретный класс: `{good.strip()}` (при желании с `match=`). Остальные тесты проверяют "
           f"значения точно.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=AnswerKey(kind="line", value=key, explanation=why),
                         context=ctx, verification="execution", checks=checks, defect_type="raises_too_broad",
                         display_code_note="Тесты запускаются на правильной реализации модуля и на регрессии.",
                         params={"fixed_code": fixed, "module": module})
