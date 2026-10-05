"""qa.js.brittle_render_fix — choose_fix (node): хрупкая проверка разметки во фронтенд-тесте.

Тест сравнивает HTML виджета целиком (``toBe`` со строкой разметки). После рефакторинга
вёрстки (другие теги и классы, добавлена строка-подсказка) видимый текст не изменился, а
тест упал. Нужно выбрать замену проверки, которая не зависит от разметки, но ловит ошибку
расчёта. Правильная — проверка видимого текста через ``textOf`` с подстрокой «метка +
значение». Дистракторы: подстрока разметки (падает на новой вёрстке), только метка без
значения (пропускает ошибку расчёта), точное равенство всего текста (падает из-за
подсказки), сравнение с результатом той же функции (тавтология, пропускает ошибку).
Каждый вариант исполняется в node на трёх версиях модуля: текущая вёрстка (должен пройти),
новая вёрстка (должен пройти), мутант с ошибкой расчёта (должен упасть).
"""
from __future__ import annotations

import json

from assessment_bank.families.qa._shims import JEST_SHIM
from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options, check_lengths

FAMILY_ID = "qa.js.brittle_render_fix"


def _j(v):
    """JS-литерал в стиле проекта: строки в одинарных кавычках, ключи без кавычек."""
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(_j(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k}: {_j(x)}" for k, x in v.items()) + " }"
    raise TypeError(v)


def _cart(rng):
    a, b = rng.sample(["Кофе", "Чай", "Сироп", "Круассан", "Какао", "Печенье"], 2)
    pa, pb = rng.randrange(150, 900, 10), rng.randrange(150, 900, 10)
    qa_, qb = rng.choice([(2, 1), (3, 1), (2, 2), (1, 3)])
    items = [{"title": a, "price": pa, "qty": qa_}, {"title": b, "price": pb, "qty": qb}]
    return dict(ctx="корзина интернет-магазина", module="ui/cartSummary", func="renderCartSummary",
                const="ITEMS", arg=items, label="Итого:", unit=" ₽",
                calc="arg.reduce((s, i) => s + i.price * i.qty, 0)",
                mutant="arg.reduce((s, i) => s + i.price, 0)",
                hint="'Товаров: ' + arg.reduce((s, i) => s + i.qty, 0)",
                value=pa * qa_ + pb * qb, test="показывает итог корзины", cls="summary")


def _balance(rng):
    rub = rng.randrange(300, 9000, 10)
    acc = {"owner": rng.choice(["Анна", "Олег", "Мария", "Ильдар"]), "kop": rub * 100}
    return dict(ctx="личный кабинет банка", module="ui/balanceCard", func="renderBalance",
                const="ACCOUNT", arg=acc, label="Баланс:", unit=" ₽",
                calc="arg.kop / 100", mutant="arg.kop", hint="'Владелец: ' + arg.owner",
                value=rub, test="показывает баланс в рублях", cls="balance")


def _price(rng):
    price = rng.randrange(800, 6000, 100)
    disc = rng.choice([10, 15, 20, 25, 30, 40])
    return dict(ctx="карточка товара", module="ui/priceTag", func="renderPrice",
                const="PRODUCT", arg={"sku": f"A-{rng.randint(100, 999)}", "price": price,
                                      "discount": disc},
                label="Цена:", unit=" ₽", calc="arg.price * (100 - arg.discount) / 100",
                mutant="arg.price", hint="'Скидка ' + arg.discount + ' %'",
                value=price * (100 - disc) // 100, test="показывает цену со скидкой", cls="price")


def _orders(rng):
    n_new = rng.randint(2, 4)
    n_other = rng.randint(1, 3)
    st = ["new"] * n_new + [rng.choice(["paid", "shipped", "done"]) for _ in range(n_other)]
    rng.shuffle(st)
    orders = [{"id": 100 + i, "status": s} for i, s in enumerate(st)]
    return dict(ctx="кабинет продавца", module="ui/ordersBadge", func="renderOrdersBadge",
                const="ORDERS", arg=orders, label="Новых заказов:", unit="",
                calc="arg.filter((o) => o.status === 'new').length", mutant="arg.length",
                hint="'Всего: ' + arg.length", value=n_new, test="считает только новые заказы",
                cls="badge")


CONTEXTS = [_cart, _balance, _price, _orders]


def _module_src(sc, version):
    expr = sc["mutant"] if version == "mutant" else sc["calc"]
    if version in ("v1", "mutant"):
        html = (f"'<div class=\"{sc['cls']}\"><span>{sc['label']}</span> <b>' + value + "
                f"'{sc['unit']}</b></div>'")
    else:
        html = (f"'<section class=\"{sc['cls']}-card\"><p>{sc['label']} <strong data-test=\"value\">' + "
                f"value + '{sc['unit']}</strong></p><p class=\"hint\">' + ({sc['hint']}) + '</p></section>'")
    return (f"function {sc['func']}(arg) {{\n  const value = {expr};\n  return {html};\n}}\n"
            f"return {{ {sc['func']} }};")


DOM_SRC = ("function textOf(html) {\n  return html.replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim();\n}\n"
           "return { textOf };")


def _v1_html(sc):
    return (f'<div class="{sc["cls"]}"><span>{sc["label"]}</span> <b>{sc["value"]}{sc["unit"]}</b></div>')


def _test_code(sc, assertion):
    return "\n".join([
        f"const {{ {sc['func']} }} = require({_j(sc['module'])});",
        "const { textOf } = require('test/dom');",
        "",
        f"const {sc['const']} = {_j(sc['arg'])};",
        "",
        f"test({_j(sc['test'])}, () => {{",
        f"  const html = {sc['func']}({sc['const']});",
        f"  {assertion}",
        "});",
    ])


def _program(sc, code, mode):
    """mode: 'option' — v1 зелёный, v2 зелёный, мутант красный; 'original' — v1 зелёный, v2 красный."""
    parts = [JEST_SHIM, "const __modules = {};",
             f"__modules['test/dom'] = (() => {{\n{DOM_SRC}\n}})();",
             "function require(p) {\n  if (!(p in __modules)) throw new Error('no module ' + p);\n"
             "  return __modules[p];\n}"]
    marks = []
    for ver in ("v1", "v2", "mutant"):
        parts.append(f"__modules[{_j(sc['module'])}] = (() => {{\n{_module_src(sc, ver)}\n}})();")
        parts.append("{\n" + code + "\n}")
        parts.append(f"const __n_{ver} = __tests.length;")
        marks.append(ver)
    cond = ("ok(v1) && ok(v2) && !ok(m)" if mode == "option" else "ok(v1) && !ok(v2)")
    parts.append(
        ";(async () => {\n  const res = await __runTests();\n"
        "  const ok = (r) => r.length > 0 && r.every((x) => x[1] === 'passed');\n"
        "  const v1 = res.slice(0, __n_v1), v2 = res.slice(__n_v1, __n_v2), m = res.slice(__n_v2);\n"
        f"  console.log({cond} ? 'RESULT: PASS' : 'RESULT: FAIL');\n}})();")
    return "\n".join(parts) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sc = rng.choice(CONTEXTS)(rng)
    val = f"{sc['label']} {sc['value']}{sc['unit']}"
    brittle = f"expect(html).toBe({_j(_v1_html(sc))});"
    good = f"expect(textOf(html)).toContain({_j(val)});"
    distract = {
        "markup": f"expect(html).toContain({_j('<b>' + str(sc['value']) + sc['unit'] + '</b>')});",
        "label_only": f"expect(textOf(html)).toContain({_j(sc['label'])});",
        "exact_text": f"expect(textOf(html)).toBe({_j(val)});",
        "tautology": f"expect(html).toEqual({sc['func']}({sc['const']}));",
    }
    chosen = rng.sample(sorted(distract), 3)
    check_lengths([good] + [distract[k] for k in chosen], max_ratio=1.6, slack=8)
    code = _test_code(sc, brittle)
    line = 8
    opts, key = balanced_options(FAMILY_ID, seed, rng, (f"Заменить строку {line} на:", good),
                                 [(f"Заменить строку {line} на:", distract[k]) for k in chosen])
    checks = [Check(name="original_breaks_on_refactor", runner="node",
                    program=_program(sc, code, "original"), expect="pass")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                            program=_program(sc, _test_code(sc, o.code), "option"),
                            expect="pass" if o.id == key else "fail"))
    stem = (f"Фронтенд ({sc['ctx']}): тест на Jest проверяет виджет `{sc['func']}`. Команда "
            f"переписала вёрстку виджета — другие теги и классы, добавлена строка-подсказка; "
            f"видимый текст «{val}» не изменился, а тест упал. В проекте есть помощник "
            f"`textOf(html)` — видимый текст без тегов, пробелы схлопнуты. Какая замена строки "
            f"{line} сделает тест устойчивым к изменениям разметки и при этом сохранит "
            f"способность ловить ошибки расчёта значения?")
    why = {"markup": "подстрока разметки снова привязывает тест к тегам — упадёт на новой вёрстке",
           "label_only": "проверка только метки пройдёт и при неверном значении",
           "exact_text": "точное равенство всего текста упадёт из-за добавленной подсказки",
           "tautology": "сравнение с результатом той же функции проходит всегда — тест "
                        "ничего не проверяет"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Проверяется видимый текст «{val}»: он не зависит от тегов и "
                                f"классов, но изменится при ошибке расчёта. Дистракторы: "
                                + "; ".join(why[k] for k in chosen) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=sc["ctx"], verification="execution", checks=checks,
                         defect_type="brittle_assertion",
                         display_code_note="Обвязка JEST_SHIM повторяет test/expect Jest; каждый "
                                           "вариант запускается на текущей и новой вёрстке и на "
                                           "мутанте с ошибкой расчёта.",
                         params={"distractors": chosen, "module": sc["module"]})
