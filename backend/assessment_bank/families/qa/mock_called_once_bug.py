"""qa.mock.called_once_bug — find_bug: проверка мока не учитывает число вызовов.

Порог Junior/Middle. Регрессия — событие отправляется дважды. Проверка в тесте смотрит только последний вызов
(`assert_called_with`, `call_args == call(...)`, `called and call_args …`) и пропускает повтор. Исправление —
`assert_called_once_with(...)` в той же строке. Один подтип; строки-ловушки — настоящие `assert_called_once_with`,
`assert_not_called`, `pytest.raises`. Порядок тестов меняется. (Опечатки вида `called_once_with` Python 3.12 уже
ловит сам — `AttributeError`, поэтому они в семейство не входят.)
Проверка исполнением: с дефектом тесты зелёные на мутанте (регрессия не поймана), после исправления — мутант пойман,
правильный код зелёный.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import PYTEST_CAUGHT_TAIL, PYTEST_GREEN_TAIL, pytest_program
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.mock.called_once_bug"

# (контекст, модуль, функция, зависимость-проверяемая, метод, событие, вторая зависимость, её метод)
CONTEXTS = [("оформление заказа", "shop.orders", "place_order", "notifier", "send", "order_placed", "payments", "charge"),
            ("сброс пароля", "auth.reset", "request_reset", "mailer", "deliver", "reset_link", "audit", "record"),
            ("возврат товара", "shop.refunds", "refund", "bus", "publish", "refund_done", "ledger", "post"),
            ("запись к врачу", "clinic.booking", "book_visit", "sms", "notify", "visit_booked", "calendar", "reserve"),
            ("выдача пропуска", "office.passes", "issue_pass", "chat", "post", "pass_issued", "registry", "add"),
            ("публикация статьи", "cms.publish", "publish_article", "cache", "purge", "article_live", "search", "index")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, module, fn, dep, meth, event, dep2, meth2 = rng.choice(CONTEXTS)
    price, qty = rng.randint(2, 40) * 50, rng.randint(1, 5)
    total = price * qty
    impl = (f"def {fn}(items, {dep}, {dep2}):\n    if not items:\n        raise ValueError('empty')\n"
            f"    total = sum(p * q for p, q in items)\n    {dep2}.{meth2}(total)\n"
            f"    {dep}.{meth}({event!r}, total)\n    return total\n")
    mutant = impl.replace(f"    {dep}.{meth}({event!r}, total)\n",
                          f"    {dep}.{meth}({event!r}, total)\n    if total > 0:\n        {dep}.{meth}({event!r}, total)\n")
    mutant_kind = "duplicate"
    regression = (f"после рефакторинга `{fn}` вызывает `{dep}.{meth}` дважды — получатель видит событие "
                  f"`{event}` два раза")
    bad_form = rng.choice([f"    {dep}.{meth}.assert_called_with({event!r}, {total})",
                           f"    assert {dep}.{meth}.call_args == call({event!r}, {total})",
                           f"    assert {dep}.{meth}.called and {dep}.{meth}.call_args == call({event!r}, {total})"])
    good = f"    {dep}.{meth}.assert_called_once_with({event!r}, {total})"
    t_target = [f"def test_{rng.choice(['notifies', 'emits_event', 'sends_event'])}():", f"    {dep} = Mock()",
                f"    {fn}([({price}, {qty})], {dep}, Mock())", "TARGET"]
    t_charge = [f"def test_{rng.choice(['charges_total', 'records_total'])}():", f"    {dep2} = Mock()",
                f"    assert {fn}([({price}, {qty})], Mock(), {dep2}) == {total}",
                f"    {dep2}.{meth2}.assert_called_once_with({total})"]
    t_empty = ["def test_empty_rejected():", f"    {dep} = Mock()", "    with pytest.raises(ValueError):",
               f"        {fn}([], {dep}, Mock())", f"    {dep}.{meth}.assert_not_called()"]
    tests = [t_target, t_charge, t_empty]
    rng.shuffle(tests)

    def assemble(line: str) -> str:
        out = ["import pytest", "from unittest.mock import Mock, call", f"from {module} import {fn}"]
        for t in tests:
            out += ["", ""] + [line if x == "TARGET" else x for x in t]
        return "\n".join(out) + "\n"

    buggy, fixed = assemble(bad_form), assemble(good)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    ok, bad = {module: impl}, {module: mutant}
    checks = [
        Check(name="buggy_green_on_correct", runner="python", expect="pass",
              program=pytest_program(buggy, PYTEST_GREEN_TAIL, ok)),
        Check(name="buggy_misses_mutant", runner="python", expect="fail",
              program=pytest_program(buggy, PYTEST_CAUGHT_TAIL, bad)),
        Check(name="fixed_green_on_correct", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_GREEN_TAIL, ok)),
        Check(name="fixed_catches_mutant", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_CAUGHT_TAIL, bad)),
    ]
    stem = (f"Тесты модуля `{module}` ({ctx}). В релизе {regression}, но все тесты ниже прошли, CI зелёный. "
            f"Укажите номер строки теста, из-за которой регрессия не обнаружена.")
    why = (f"Строка {key}: `assert_called_with` и `call_args` проверяют только последний вызов (а `called` — сам факт "
           f"вызова), число вызовов не проверяется, поэтому повторный вызов проходит незамеченным. Нужна проверка "
           f"«ровно один вызов с этими аргументами»: `{good.strip()}`. Остальные проверки (`assert_called_once_with`, "
           f"`assert_not_called`, `pytest.raises`) верны.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx, verification="execution",
                         checks=checks, defect_type="mock_call_count_unchecked",
                         display_code_note="Тесты запускаются на правильной реализации модуля и на регрессии.",
                         params={"fixed_code": fixed, "mutant": mutant_kind, "module": module})
