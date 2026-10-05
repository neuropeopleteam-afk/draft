"""qa.js.unawaited_assert — find_bug: асинхронная проверка в тесте Jest не дожидается промиса.

Тест вызывает асинхронную функцию и проверяет результат внутри `.then`, но не возвращает и
не ожидает промис: тест завершается раньше проверки и всегда зелёный. Ключ проверяется
исполнением в Node (обвязка JEST_SHIM): с дефектом набор тестов зелёный и на правильной
реализации, и на мутанте; после исправления строки — зелёный на правильной и красный на мутанте.
"""
from __future__ import annotations

import json

from assessment_bank.families.qa._shims import JEST_SHIM
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.js.unawaited_assert"


def _j(v):
    return json.dumps(v, ensure_ascii=False)


def _orders(rng):
    ids = rng.sample(range(10, 999), 3)
    impl = ("const STATUS = { new: 'Ожидает оплаты', paid: 'Оплачен', cancelled: 'Отменён' };\n"
            "async function loadOrderView(api, id) {\n  const order = await api.getOrder(id);\n"
            "  return { title: 'Заказ №' + order.id, statusText: STATUS[order.status] };\n}\n"
            "return { loadOrderView };")
    mutant = impl.replace("paid: 'Оплачен'", "paid: 'Ожидает оплаты'")

    def case(name, i, status, text):
        return dict(name=name, mock=f"getOrder: jest.fn().mockResolvedValue({{ id: {i}, status: '{status}' }})",
                    call=f"loadOrderView(api, {i})", var="view", expr="view.statusText", value=_j(text))
    return dict(module="../src/orders", func="loadOrderView", ctx="личный кабинет магазина",
                impl=impl, mutant=mutant,
                regression="оплаченные заказы снова показываются со статусом «Ожидает оплаты»",
                others=[case("новый заказ ожидает оплаты", ids[0], "new", "Ожидает оплаты"),
                        case("отменённый заказ", ids[1], "cancelled", "Отменён")],
                target=case("оплаченный заказ", ids[2], "paid", "Оплачен"))


def _profile(rng):
    first, last, nick = rng.choice([("Анна", "Козлова", "anna_k"), ("Илья", "Петров", "ilya.dev"),
                                    ("Мария", "Орлова", "mori"), ("Олег", "Смирнов", "oleg77"),
                                    ("Дина", "Лебедева", "dina_l"), ("Артём", "Волков", "volk")])
    uid = rng.sample(range(100, 9999), 2)
    impl = ("async function loadProfile(api, id) {\n  const u = await api.getUser(id);\n"
            "  const name = u.nickname ? u.nickname : u.first + ' ' + u.last[0] + '.';\n"
            "  return { displayName: name, initials: u.first[0] + u.last[0] };\n}\n"
            "return { loadProfile };")
    mutant = impl.replace("u.nickname ? u.nickname :", "false ? u.nickname :")

    def case(name, i, with_nick, field, text):
        extra = f", nickname: '{nick}'" if with_nick else ""
        return dict(name=name, mock=f"getUser: jest.fn().mockResolvedValue({{ first: '{first}', "
                                    f"last: '{last}'{extra} }})",
                    call=f"loadProfile(api, {i})", var="profile", expr=f"profile.{field}",
                    value=_j(text))
    return dict(module="../src/profile", func="loadProfile", ctx="соцсеть",
                impl=impl, mutant=mutant,
                regression="у пользователей с никнеймом вместо никнейма снова выводится «Имя Ф.»",
                others=[case("имя и первая буква фамилии", uid[0], False, "displayName",
                             f"{first} {last[0]}."),
                        case("инициалы в аватаре", uid[1], True, "initials", first[0] + last[0])],
                target=case("никнейм важнее имени", uid[0] + 1, True, "displayName", nick))


def _cart(rng):
    th = rng.randint(2, 12) * 500
    impl = ("async function loadCartSummary(api) {\n  const cart = await api.getCart();\n"
            "  const total = cart.items.reduce((s, it) => s + it.price * it.qty, 0);\n"
            f"  return {{ total, freeShipping: total >= {th} }};\n}}\nreturn {{ loadCartSummary }};")
    mutant = impl.replace(f"total >= {th}", f"total > {th}")
    below = th - rng.choice([1, 10, 50])
    p = th // 2

    def case(name, items, field, value):
        lit = ", ".join(f"{{ price: {pr}, qty: {q} }}" for pr, q in items)
        return dict(name=name, mock=f"getCart: jest.fn().mockResolvedValue({{ items: [{lit}] }})",
                    call="loadCartSummary(api)", var="summary", expr=f"summary.{field}",
                    value=value)
    return dict(module="../src/cart", func="loadCartSummary", ctx="корзина маркетплейса",
                impl=impl, mutant=mutant,
                regression=f"при сумме корзины ровно {th} ₽ бейдж «Бесплатная доставка» пропал",
                others=[case("сумма позиций корзины", [(p, 1), (below - p, 1)], "total", str(below)),
                        case("ниже порога доставка платная", [(below, 1)], "freeShipping", "false")],
                target=case("бесплатная доставка с порога", [(p, 2)], "freeShipping", "true"))


def _badge(rng):
    small = rng.randint(2, 40)
    big = rng.randint(120, 999)
    impl = ("async function loadBadge(api) {\n  const n = await api.countUnread();\n"
            "  return { text: n > 99 ? '99+' : String(n), visible: n > 0 };\n}\n"
            "return { loadBadge };")
    mutant = impl.replace("n > 99 ?", "n >= 99 ?")

    def case(name, n, field, value):
        return dict(name=name, mock=f"countUnread: jest.fn().mockResolvedValue({n})",
                    call="loadBadge(api)", var="badge", expr=f"badge.{field}", value=value)
    return dict(module="../src/badge", func="loadBadge", ctx="почтовый клиент",
                impl=impl, mutant=mutant,
                regression="при ровно 99 непрочитанных письмах бейдж показывает «99+» вместо «99»",
                others=[case("небольшое число как есть", small, "text", _j(str(small))),
                        case("больше 99 сокращается", big, "text", _j("99+"))],
                target=case("ровно 99 без сокращения", 99, "text", _j("99")))


CONTEXTS = [_orders, _profile, _cart, _badge]


def _test_block(c, mode):
    """mode: ok | then_no_return | await_missing | fixed_return | fixed_await."""
    head = "async () => {" if mode in ("ok", "await_missing", "fixed_await") else "() => {"
    lines = [f"test({_j(c['name'])}, {head}", f"  const api = {{ {c['mock']} }};"]
    if mode == "ok":
        lines += [f"  const {c['var']} = await {c['call']};",
                  f"  expect({c['expr']}).toBe({c['value']});"]
    else:
        prefix = {"then_no_return": "", "await_missing": "", "fixed_return": "return ",
                  "fixed_await": "await "}[mode]
        lines += [f"  {prefix}{c['call']}.then(({c['var']}) => {{",
                  f"    expect({c['expr']}).toBe({c['value']});", "  });"]
    return lines + ["});"]


def _prelude(module, src):
    return (JEST_SHIM + "\nconst __modules = {};\n"
            f"__modules[{_j(module)}] = (() => {{\n{src}\n}})();\n"
            "function require(p) {\n  if (!(p in __modules)) throw new Error('no module ' + p);\n"
            "  return __modules[p];\n}\n")


def _tail(mode):
    cond = "failed === 0" if mode == "green" else "failed > 0"
    return ("\n;(async () => {\n  const res = await __runTests();\n"
            "  const failed = res.filter((r) => r[1] !== 'passed').length;\n"
            f"  console.log({cond} ? 'RESULT: PASS' : 'RESULT: FAIL');\n}})();\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sc = rng.choice(CONTEXTS)(rng)
    sub = rng.choice(["then_no_return", "await_missing"])
    others = list(sc["others"])
    rng.shuffle(others)
    header = [f"const {{ {sc['func']} }} = require({_j(sc['module'])});"]

    order = others + ["TARGET"]
    rng.shuffle(order)

    def assemble(target_mode):
        out = list(header)
        for c in order:
            out += [""] + (_test_block(sc["target"], target_mode) if c == "TARGET"
                           else _test_block(c, "ok"))
        return "\n".join(out)

    buggy = assemble(sub)
    fixed = assemble("fixed_return" if sub == "then_no_return" else "fixed_await")
    bad_line = next(i for i, l in enumerate(buggy.splitlines(), 1) if ".then((" in l)
    assert changed_lines(buggy, fixed) == {bad_line}
    ok_pre, bad_pre = _prelude(sc["module"], sc["impl"]), _prelude(sc["module"], sc["mutant"])
    checks = [
        Check(name="buggy_green_on_correct", runner="node", expect="pass",
              program=ok_pre + buggy + _tail("green")),
        Check(name="buggy_misses_mutant", runner="node", expect="fail",
              program=bad_pre + buggy + _tail("caught")),
        Check(name="fixed_green_on_correct", runner="node", expect="pass", embeds_display_code=False,
              program=ok_pre + fixed + _tail("green")),
        Check(name="fixed_catches_mutant", runner="node", expect="pass", embeds_display_code=False,
              program=bad_pre + fixed + _tail("caught")),
    ]
    stem = (f"Тесты Jest для функции `{sc['func']}` ({sc['ctx']}). После очередного релиза "
            f"{sc['regression']}, но все тесты по-прежнему зелёные. Укажите номер строки, из-за "
            f"которой тест не обнаруживает регрессию.")
    fix_word = "`return`" if sub == "then_no_return" else "`await`"
    ak = AnswerKey(kind="line", value=bad_line,
                   explanation=(f"Строка {bad_line}: промис с проверкой внутри `.then` не возвращается "
                                "и не ожидается, тест завершается раньше, чем выполнится expect, и "
                                f"считается пройденным. Исправление — добавить {fix_word} перед вызовом "
                                "(или переписать на `const x = await ...; expect(...)`)."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=sc["ctx"],
                         verification="execution", checks=checks, defect_type="unawaited_assertion",
                         display_code_note="require и Jest (test/expect/jest.fn) предоставляет "
                                           "минимальная совместимая обвязка; показанный код "
                                           "исполняется дословно.",
                         params={"fixed_code": fixed, "subtype": sub, "module": sc["module"]})
