"""qa.pytest.vacuous_assert — find_bug: проверка в тесте всегда истинна, регрессия проходит незамеченной.

Три подтипа «пустой» проверки: запятая вместо сравнения (`assert x, 1700`), метод без
вызова (`assert obj.is_locked`), кортеж в скобках (`assert (x == 1, "msg")`). Ключ
проверяется исполнением: с дефектом тесты зелёные и на правильном коде, и на мутанте
(регрессия не поймана); после исправления строки тесты зелёные на правильном коде и
падают на мутанте.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import (PYTEST_CAUGHT_TAIL, PYTEST_GREEN_TAIL,
                                                pytest_program)
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.vacuous_assert"


def _pricing(rng):
    pct = rng.choice([10, 15, 20, 25])
    promo = rng.choice(["SALE", "AUTUMN", "WELCOME"]) + str(pct)
    amount = rng.randint(8, 60) * 100
    plain = rng.randint(30, 199) * 10
    total = amount - amount * pct // 100
    impl = ("class Receipt:\n    def __init__(self, total, discount):\n"
            "        self.total, self.discount = total, discount\n\n"
            "    def is_discounted(self):\n        return self.discount > 0\n\n\n"
            "def make_receipt(amount, promo=None):\n    if amount < 0:\n"
            "        raise ValueError('amount')\n"
            f"    discount = amount * {pct} // 100 if promo == {promo!r} else 0\n"
            "    return Receipt(amount - discount, discount)\n")
    mutant = impl.replace(f"if promo == {promo!r}", f"if promo == {promo.lower()!r}")
    return dict(
        module="shop.pricing", func="make_receipt", ctx="интернет-магазин",
        impl=impl, mutant=mutant,
        regression=(f"после рефакторинга промокод {promo} перестал давать скидку: "
                    f"`make_receipt({amount}, \"{promo}\")` возвращает чек на {amount} ₽ без скидки"),
        others=[[f"def test_{rng.choice(['full_price_without_promo', 'no_promo_no_discount'])}():",
                 f"    receipt = make_receipt({plain})", f"    assert receipt.total == {plain}"],
                ["def test_negative_amount_rejected():", "    with pytest.raises(ValueError):",
                 f"        make_receipt(-{rng.randint(1, 99)}, \"{promo}\")"]],
        target_head=[f"def test_{rng.choice(['promo_gives_discount', 'promo_applied'])}():",
                     f"    receipt = make_receipt({amount}, \"{promo}\")"],
        obj="receipt", attr="total", value=str(total), method="is_discounted",
        msg=f"скидка {promo}")


def _lockout(rng):
    limit = rng.randint(3, 6)
    impl = ("class Account:\n    def __init__(self):\n        self.failed = 0\n"
            "        self.status = 'active'\n\n    def is_locked(self):\n"
            "        return self.status == 'locked'\n\n\n"
            f"def register_failures(n, limit={limit}):\n    if n < 0:\n"
            "        raise ValueError('n')\n    account = Account()\n    for _ in range(n):\n"
            "        account.failed += 1\n        if account.failed >= limit:\n"
            "            account.status = 'locked'\n    return account\n")
    mutant = impl.replace("account.failed >= limit", "account.failed > limit")
    return dict(
        module="auth.lockout", func="register_failures", ctx="личный кабинет банка",
        impl=impl, mutant=mutant,
        regression=(f"после правки учётная запись блокируется только после {limit + 1}-й "
                    f"неудачной попытки входа вместо {limit}-й"),
        others=[[f"def test_{rng.choice(['below_limit_stays_active', 'few_failures_not_locked'])}():",
                 f"    account = register_failures({limit - 1})",
                 "    assert account.status == \"active\""],
                ["def test_negative_count_rejected():", "    with pytest.raises(ValueError):",
                 f"        register_failures(-{rng.randint(1, 9)})"]],
        target_head=[f"def test_{rng.choice(['locked_at_limit', 'lock_after_limit'])}():",
                     f"    account = register_failures({limit})"],
        obj="account", attr="status", value="\"locked\"", method="is_locked",
        msg="блокировка после лимита")


def _delivery(rng):
    th = rng.randint(2, 15) * 500
    base = rng.choice([200, 300, 400, 500, 600])
    impl = ("class Quote:\n    def __init__(self, price):\n        self.price = price\n\n"
            f"    def is_discounted(self):\n        return self.price < {base}\n\n\n"
            "def quote(order_sum):\n    if order_sum <= 0:\n        raise ValueError('order_sum')\n"
            f"    return Quote({base} // 2 if order_sum >= {th} else {base})\n")
    mutant = impl.replace(f"order_sum >= {th}", f"order_sum > {th}")
    below = th - rng.choice([1, 10, 100])
    return dict(
        module="delivery.tariffs", func="quote", ctx="служба доставки",
        impl=impl, mutant=mutant,
        regression=(f"заказ ровно на {th} ₽ снова платит полную цену доставки {base} ₽, хотя "
                    f"по правилам скидка 50 % действует от {th} ₽ включительно"),
        others=[["def test_below_threshold_full_price():", f"    q = quote({below})",
                 f"    assert q.price == {base}"],
                ["def test_non_positive_sum_rejected():", "    with pytest.raises(ValueError):",
                 f"        quote({rng.choice([0, -1, -10, -100])})"]],
        target_head=[f"def test_{rng.choice(['half_price_at_threshold', 'threshold_inclusive'])}():",
                     f"    q = quote({th})"],
        obj="q", attr="price", value=str(base // 2), method="is_discounted",
        msg="скидка на пороге")


def _loyalty(rng):
    gold = rng.randint(4, 15)
    amount = rng.randint(5, 80) * 100
    rate = rng.choice([3, 5])
    impl = ("class Accrual:\n    def __init__(self, points, tier):\n"
            "        self.points, self.tier = points, tier\n\n"
            "    def is_boosted(self):\n        return self.tier == 'gold'\n\n\n"
            "def accrue(amount, orders_count):\n    if amount < 0:\n        raise ValueError('amount')\n"
            f"    tier = 'gold' if orders_count >= {gold} else 'base'\n"
            f"    rate = {rate} if tier == 'gold' else 1\n"
            "    return Accrual(amount * rate // 100, tier)\n")
    mutant = impl.replace(f"orders_count >= {gold}", f"orders_count > {gold}")
    return dict(
        module="loyalty.points", func="accrue", ctx="программа лояльности",
        impl=impl, mutant=mutant,
        regression=(f"клиент с ровно {gold} заказами перестал получать повышенные баллы "
                    f"({rate} % вместо 1 %)"),
        others=[["def test_new_client_base_rate():", f"    accrual = accrue({amount}, 1)",
                 f"    assert accrual.points == {amount // 100}"],
                ["def test_negative_amount_rejected():", "    with pytest.raises(ValueError):",
                 f"        accrue(-{rng.choice([1, 50, 100])}, 3)"]],
        target_head=[f"def test_{rng.choice(['gold_rate_from_threshold', 'gold_tier_boost'])}():",
                     f"    accrual = accrue({amount}, {gold})"],
        obj="accrual", attr="points", value=str(amount * rate // 100), method="is_boosted",
        msg="повышенные баллы")


CONTEXTS = [_pricing, _lockout, _delivery, _loyalty]
SUBTYPES = ["comma", "method", "tuple"]


def _target_lines(sc, sub):
    o, a, val, meth, msg = sc["obj"], sc["attr"], sc["value"], sc["method"], sc["msg"]
    if sub == "comma":
        return f"    assert {o}.{a}, {val}", f"    assert {o}.{a} == {val}"
    if sub == "method":
        return f"    assert {o}.{meth}", f"    assert {o}.{meth}()"
    return (f"    assert ({o}.{a} == {val}, \"{msg}\")", f"    assert {o}.{a} == {val}, \"{msg}\"")


WHY = {"comma": "`assert x, y` проверяет только истинность x, а y — сообщение об ошибке; "
                "значение не сравнивается",
       "method": "метод без скобок — объект связанного метода, он всегда истинен; метод не "
                 "вызывается",
       "tuple": "в скобках оказался кортеж из двух элементов, непустой кортеж всегда истинен "
                "(Python предупреждает SyntaxWarning: assertion is always true)"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sc = rng.choice(CONTEXTS)(rng)
    sub = rng.choice(SUBTYPES)
    bad, good = _target_lines(sc, sub)
    tests = [sc["others"][0], sc["others"][1], "TARGET"]
    rng.shuffle(tests)
    header = ["import pytest", f"from {sc['module']} import {sc['func']}"]

    def assemble(line):
        out = list(header)
        for t in tests:
            out += ["", ""] + (sc["target_head"] + [line] if t == "TARGET" else t)
        return "\n".join(out)

    buggy, fixed = assemble(bad), assemble(good)
    key_line = buggy.splitlines().index(bad) + 1
    assert changed_lines(buggy, fixed) == {key_line}
    mod_ok, mod_bad = {sc["module"]: sc["impl"]}, {sc["module"]: sc["mutant"]}
    checks = [
        Check(name="buggy_green_on_correct", runner="python", expect="pass",
              program=pytest_program(buggy, PYTEST_GREEN_TAIL, mod_ok)),
        Check(name="buggy_misses_mutant", runner="python", expect="fail",
              program=pytest_program(buggy, PYTEST_CAUGHT_TAIL, mod_bad)),
        Check(name="fixed_green_on_correct", runner="python", expect="pass",
              embeds_display_code=False, program=pytest_program(fixed, PYTEST_GREEN_TAIL, mod_ok)),
        Check(name="fixed_catches_mutant", runner="python", expect="pass",
              embeds_display_code=False, program=pytest_program(fixed, PYTEST_CAUGHT_TAIL, mod_bad)),
    ]
    stem = (f"Тесты модуля `{sc['module']}` ({sc['ctx']}). В очередном релизе {sc['regression']}. "
            f"При этом все тесты ниже по-прежнему проходят, CI зелёный. Укажите номер строки "
            f"теста, из-за которой регрессия не обнаружена.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {WHY[sub]}. Исправление: `{good.strip()}` — "
                               "тест проходит на правильном коде и падает на регрессии.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=sc["ctx"],
                         verification="execution", checks=checks, defect_type="vacuous_assert",
                         params={"fixed_code": fixed, "subtype": sub, "module": sc["module"]})
