"""qa.pytest.patch_arg_order — find_bug: порядок аргументов при нескольких декораторах @patch.

Декораторы применяются снизу вверх, поэтому первый аргумент теста — мок из НИЖНЕГО
декоратора. В тесте имена аргументов перечислены сверху вниз: моки перепутаны, тест падает
на правильном коде. Исправление одной строкой — порядок параметров функции теста.
Проверяется исполнением с настоящим unittest.mock: с дефектом тест красный на правильной
реализации; исправленный — зелёный на правильной и красный на мутанте.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import (PYTEST_CAUGHT_TAIL, PYTEST_GREEN_TAIL,
                                                pytest_program)
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.patch_arg_order"

# module, func, params, guard(name, mockname, args), main(name, mockname, args),
# effect(name, mockname, args с RESULT), ctx, описание
CONTEXTS = [
    dict(module="shop.checkout", func="place_order", params=["order_id", "amount"],
         guard=("reserve_stock", "mock_stock", ["order_id"]),
         main=("charge_card", "mock_charge", ["order_id", "amount"]),
         effect=("send_receipt", "mock_receipt", ["order_id", "RESULT"]),
         ctx="интернет-магазин", what="оформляет заказ: резервирует товар, списывает оплату и "
                                      "отправляет чек с номером транзакции"),
    dict(module="bank.transfers", func="transfer", params=["account", "amount"],
         guard=("check_limits", "mock_limits", ["account", "amount"]),
         main=("post_ledger", "mock_ledger", ["account", "amount"]),
         effect=("notify_client", "mock_notify", ["account", "RESULT"]),
         ctx="банк", what="проводит перевод: проверяет лимиты, делает проводку и уведомляет "
                          "клиента номером проводки"),
    dict(module="clinic.booking", func="book_visit", params=["doctor_id", "phone"],
         guard=("is_doctor_active", "mock_active", ["doctor_id"]),
         main=("reserve_slot", "mock_reserve", ["doctor_id", "phone"]),
         effect=("send_sms", "mock_sms", ["phone", "RESULT"]),
         ctx="запись в клинику", what="записывает пациента: проверяет, что врач принимает, "
                                      "бронирует слот и отправляет SMS с номером записи"),
    dict(module="hr.onboarding", func="hire", params=["login", "email"],
         guard=("is_login_free", "mock_free", ["login"]),
         main=("create_account", "mock_create", ["login", "email"]),
         effect=("send_welcome", "mock_welcome", ["email", "RESULT"]),
         ctx="HR-портал", what="оформляет сотрудника: проверяет логин, создаёт учётную запись и "
                               "отправляет приветственное письмо с её идентификатором"),
]


def _impl(c, with_guard, mutant=False):
    names = ([c["guard"]] if with_guard else []) + [c["main"], c["effect"]]
    out = ["class RejectedError(Exception):", "    pass", ""]
    for n, _m, _a in names:
        out += ["", f"def {n}(*args):", "    raise RuntimeError('внешний сервис недоступен в тестах')"]
    out += ["", "", f"def {c['func']}({', '.join(c['params'])}):"]
    if with_guard:
        g = c["guard"]
        out += [f"    if not {g[0]}({', '.join(g[2])}):", f"        raise RejectedError({g[2][0]})"]
    m, e = c["main"], c["effect"]
    out.append(f"    result = {m[0]}({', '.join(m[2])})")
    eargs = [("None" if mutant else "result") if a == "RESULT" else a for a in e[2]]
    out += [f"    {e[0]}({', '.join(eargs)})", "    return result"]
    return "\n".join(out) + "\n"


def _values(rng, c):
    v = {}
    for p in c["params"]:
        v[p] = {"order_id": str(rng.randint(10, 9999)), "amount": str(rng.randint(5, 900) * 10),
                "account": repr("40817810" + "".join(str(rng.randint(0, 9)) for _ in range(4))),
                "doctor_id": str(rng.randint(1, 300)),
                "phone": repr("+7999" + "".join(str(rng.randint(0, 9)) for _ in range(7))),
                "login": repr(rng.choice(["a.ivanova", "p.sidorov", "k.lee", "m.fedorova"])),
                "email": repr(rng.choice(["new@corp.example", "hello@corp.example",
                                          "staff@corp.example"]))}[p]
    prefix = {"place_order": "tx-", "transfer": "E-", "book_visit": "B-", "hire": "U-"}[c["func"]]
    v["RESULT"] = repr(prefix + str(rng.randint(100, 99999)))
    return v


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    with_guard = rng.random() < 0.5
    vals = _values(rng, c)
    patched = ([c["guard"]] if with_guard else []) + [c["main"], c["effect"]]
    # в коде декораторы идут в порядке вызовов: guard, main, effect — сверху вниз
    rng_order = list(patched)
    if rng.random() < 0.5:
        rng_order = list(reversed(rng_order))
    top_down = [p[1] for p in rng_order]
    bottom_up = list(reversed(top_down))
    test_name = rng.choice(["test_{e}_after_{m}", "test_{m}_then_{e}", "test_{e}_gets_result"]).format(
        e=c["effect"][0].split("_")[0], m=c["main"][0].split("_")[0])
    body = []
    if with_guard:
        body.append(f"    {c['guard'][1]}.return_value = True")
    body.append(f"    {c['main'][1]}.return_value = {vals['RESULT']}")
    call_args = ", ".join(vals[p] for p in c["params"])
    body.append(f"    assert {c['func']}({call_args}) == {vals['RESULT']}")
    e = c["effect"]
    body.append(f"    {e[1]}.assert_called_once_with({', '.join(vals[a] for a in e[2])})")
    head = (["import pytest"] if rng.random() < 0.5 else []) + [
        "from unittest.mock import patch", "", f"from {c['module']} import {c['func']}", "", ""]
    decos = [f"@patch(\"{c['module']}.{p[0]}\")" for p in rng_order]
    bad_def = f"def {test_name}({', '.join(top_down)}):"
    good_def = f"def {test_name}({', '.join(bottom_up)}):"
    buggy = "\n".join(head + decos + [bad_def] + body)
    fixed = "\n".join(head + decos + [good_def] + body)
    key_line = buggy.splitlines().index(bad_def) + 1
    assert changed_lines(buggy, fixed) == {key_line}
    ok = {c["module"]: _impl(c, with_guard)}
    bad = {c["module"]: _impl(c, with_guard, mutant=True)}
    checks = [
        Check(name="buggy_red_on_correct", runner="python", expect="fail",
              program=pytest_program(buggy, PYTEST_GREEN_TAIL, ok)),
        Check(name="fixed_green_on_correct", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_GREEN_TAIL, ok)),
        Check(name="fixed_catches_mutant", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_CAUGHT_TAIL, bad)),
    ]
    deps = ", ".join(f"`{p[0]}`" for p in patched)
    stem = (f"Функция `{c['func']}` ({c['ctx']}) {c['what']}. Внешние вызовы ({deps}) в тесте "
            f"заменены моками. Тест падает, хотя `{c['func']}` работает правильно: это подтвердили "
            f"на стенде и ревью кода. Тест можно исправить, изменив ровно одну строку. Укажите её номер.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: декораторы @patch применяются снизу вверх, и "
                                "первым аргументом приходит мок из нижнего декоратора. Имена "
                                f"перечислены сверху вниз, моки перепутаны. Верно: `{good_def}`."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=c["ctx"],
                         verification="execution", checks=checks, defect_type="patch_arg_order",
                         params={"fixed_code": fixed, "with_guard": with_guard,
                                 "reversed": top_down[0] != patched[0][1]})
