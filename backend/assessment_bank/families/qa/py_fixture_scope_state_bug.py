"""qa.pytest.fixture_scope_state_bug — find_bug: изменяемый объект в фикстуре с широкой областью видимости.

Порог Middle/Senior. Фикстура, которую тесты изменяют (корзина, очередь, кошелёк), объявлена со `scope="module"`
или `"session"`: состояние переходит из теста в тест, и результат зависит от порядка — каждый тест по отдельности
зелёный, полный прогон или случайный порядок — красный. Исправление — область функции (`@pytest.fixture`) в той же
строке. Строка-ловушка — вторая фикстура с широкой областью, которую тесты только читают (безопасно). Один подтип.
Проверка исполнением (обвязка pytest банка): с дефектом каждый тест отдельно зелёный, но есть порядок, где прогон
красный; после исправления зелёные все порядки.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import PYTEST_GREEN_TAIL, pytest_program
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.fixture_scope_state_bug"

# (контекст, модуль, класс, фикстура, метод добавления, метод итога, справочник, ключи справочника)
CONTEXTS = [("корзина магазина", "shop.cart", "Cart", "cart", "add", "total", "prices", ["apple", "pear", "plum"]),
            ("кошелёк клиента", "bank.wallet", "Wallet", "wallet", "deposit", "balance", "rates", ["rub", "kzt", "byn"]),
            ("очередь задач", "jobs.queue", "JobQueue", "queue", "push", "weight", "costs", ["report", "email", "backup"]),
            ("плейлист", "music.playlist", "Playlist", "playlist", "append", "duration", "tracks", ["intro", "song", "outro"]),
            ("склад", "store.stock", "Stock", "stock", "receive", "units", "packs", ["box", "pallet", "bag"])]

TAIL_ALONE = r'''
_bk_names = [n for n in list(globals()) if n.startswith("test_")]
_bk_ok = True
for _bk_n in _bk_names:
    _bk_c = _bk_summary(_bk_run(dict(globals()), order=[_bk_n]))
    _bk_ok = _bk_ok and _bk_c["failed"] + _bk_c["error"] == 0
print("RESULT: PASS" if _bk_ok else "RESULT: FAIL")
'''
TAIL_ALL_ORDERS = r'''
import itertools as _bk_itx
_bk_names = [n for n in list(globals()) if n.startswith("test_")]
_bk_ok = True
for _bk_perm in _bk_itx.permutations(_bk_names):
    _bk_c = _bk_summary(_bk_run(dict(globals()), order=list(_bk_perm)))
    _bk_ok = _bk_ok and _bk_c["failed"] + _bk_c["error"] == 0
print("RESULT: PASS" if _bk_ok else "RESULT: FAIL")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, module, cls, fx, add, total, ref, keys = rng.choice(CONTEXTS)
    vals = {k: rng.randint(2, 30) * 10 for k in keys}
    impl = (f"class {cls}:\n    def __init__(self):\n        self.items = []\n\n"
            f"    def {add}(self, name, value):\n        self.items.append((name, value))\n\n"
            f"    def {total}(self):\n        return sum(v for _, v in self.items)\n")
    scope = rng.choice(["module", "session"])
    bad = f'@pytest.fixture(scope="{scope}")'
    good = "@pytest.fixture"
    k0, k1, k2 = keys
    tests = [
        [f"def test_{rng.choice(['empty', 'starts_empty'])}({fx}):", f"    assert {fx}.{total}() == 0"],
        [f"def test_one_{k0}({fx}, {ref}):", f"    {fx}.{add}({k0!r}, {ref}[{k0!r}])",
         f"    assert {fx}.{total}() == {vals[k0]}"],
        [f"def test_{k1}_and_{k2}({fx}, {ref}):", f"    {fx}.{add}({k1!r}, {ref}[{k1!r}])",
         f"    {fx}.{add}({k2!r}, {ref}[{k2!r}])", f"    assert {fx}.{total}() == {vals[k1] + vals[k2]}"],
    ]
    rng.shuffle(tests)
    ref_scope = rng.choice(["session", "module"])
    fx_block = ["FIXTURE", f"def {fx}():", f"    return {cls}()"]
    ref_block = [f'@pytest.fixture(scope="{ref_scope}")', f"def {ref}():", f"    return {vals!r}"]
    blocks = [fx_block, ref_block] if rng.random() < 0.5 else [ref_block, fx_block]
    doc = [f'"""Тесты {cls}: {ctx}."""', ""] if rng.random() < 0.5 else []

    def assemble(line: str) -> str:
        out = doc + ["import pytest", f"from {module} import {cls}"]
        for b in blocks + tests:
            out += ["", ""] + [line if x == "FIXTURE" else x for x in b]
        return "\n".join(out) + "\n"

    buggy, fixed = assemble(bad), assemble(good)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    mods = {module: impl}
    checks = [
        Check(name="buggy_each_alone_green", runner="python", expect="pass",
              program=pytest_program(buggy, TAIL_ALONE, mods)),
        Check(name="buggy_order_dependent", runner="python", expect="fail",
              program=pytest_program(buggy, TAIL_ALL_ORDERS, mods)),
        Check(name="fixed_all_orders_green", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, TAIL_ALL_ORDERS, mods)),
        Check(name="fixed_green", runner="python", expect="pass", embeds_display_code=False,
              program=pytest_program(fixed, PYTEST_GREEN_TAIL, mods)),
    ]
    stem = (f"Тесты модуля `{module}` ({ctx}). Каждый тест по отдельности (`pytest -k …`) проходит, а при полном "
            f"прогоне или в случайном порядке часть тестов падает; код `{cls}` не менялся. Укажите номер строки, "
            f"из-за которой результат зависит от порядка тестов.")
    why = (f"Строка {key}: фикстура `{fx}` возвращает изменяемый объект, который тесты меняют, но объявлена со "
           f"`scope=\"{scope}\"` — один экземпляр на все тесты, состояние переходит из теста в тест. Нужна область "
           f"функции (`@pytest.fixture`): новый объект на каждый тест. Фикстура `{ref}` с широкой областью безопасна — "
           f"тесты её только читают.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx, verification="execution",
                         checks=checks, defect_type="shared_mutable_fixture",
                         display_code_note="Тесты запускаются по одному и во всех порядках (обвязка pytest банка).",
                         params={"fixed_code": fixed, "scope": scope, "module": module})
