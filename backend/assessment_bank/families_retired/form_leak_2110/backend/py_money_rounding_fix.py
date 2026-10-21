"""backend.py.money_rounding_fix — choose_fix: денежное округление «половина вверх» без float."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from assessment_bank.gen_utils import build_variant, dedent, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.py.money_rounding_fix"
Q = Decimal("0.01")

CONTEXTS = [
    ("apply_discount", "percent", "цену со скидкой {p} %", "discount", "100 - percent", "интернет-магазин"),
    ("add_vat", "rate", "цену с НДС {p} %", "vat", "100 + rate", "бухгалтерия"),
    ("commission", "percent", "комиссию {p} % от суммы", "fee", "percent", "платёжная система"),
    ("cashback", "percent", "кешбэк {p} % от покупки", "cashback", "percent", "банк"),
]

BODIES = {
    "good": """\
        from decimal import Decimal, ROUND_HALF_UP


        def {fn}(amount: str, {arg}: int) -> str:
            value = Decimal(amount) * ({mult}) / 100
            return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))""",
    "from_float": """\
        from decimal import Decimal, ROUND_HALF_UP


        def {fn}(amount: str, {arg}: int) -> str:
            value = Decimal(float(amount)) * ({mult}) / 100
            return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))""",
    "half_even": """\
        from decimal import Decimal


        def {fn}(amount: str, {arg}: int) -> str:
            value = Decimal(amount) * ({mult}) / 100
            return str(value.quantize(Decimal("0.01")))""",
    "int_half": """\
        def {fn}(amount: str, {arg}: int) -> str:
            value = float(amount) * ({mult}) / 100
            return f"{{int(value * 100 + 0.5) / 100:.2f}}\"""",
    "str_format": """\
        def {fn}(amount: str, {arg}: int) -> str:
            value = float(amount) * ({mult}) / 100
            return f"{{value:.2f}}\"""",
}
BUGGY = """\
    def {fn}(amount: str, {arg}: int) -> str:
        \"\"\"Сумма в рублях строкой; округление до копеек, половина — вверх.\"\"\"
        value = float(amount) * ({mult}) / 100
        return f"{{round(value, 2):.2f}}\""""


def _ref(kind: str, amount: str, k: int) -> str:
    if kind == "good":
        return str((Decimal(amount) * k / 100).quantize(Q, rounding=ROUND_HALF_UP))
    if kind == "from_float":
        return str((Decimal(float(amount)) * k / 100).quantize(Q, rounding=ROUND_HALF_UP))
    if kind == "half_even":
        return str((Decimal(amount) * k / 100).quantize(Q))
    if kind == "int_half":
        return f"{int(float(amount) * k / 100 * 100 + 0.5) / 100:.2f}"
    if kind == "str_format":
        return f"{float(amount) * k / 100:.2f}"
    if kind == "buggy":
        return f"{round(float(amount) * k / 100, 2):.2f}"
    raise ValueError(kind)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, arg, what, _short, mult_t, ctx = rng.choice(CONTEXTS)
    # кратные 20 множители не дают третьего знака «5» — такие ставки бесполезны для задания
    p = rng.choice([5, 10, 15, 25, 35, 50]) if arg != "rate" else 10  # НДС 10 % (льготная ставка); при 20–22 % третьего знака «5» почти не бывает
    k = eval(mult_t.replace("percent", str(p)).replace("rate", str(p)))  # noqa: S307 — наша константа
    chosen = rng.sample(["from_float", "half_even", "int_half", "str_format"], 3)
    cases: list[str] = []
    need = set(chosen) | {"buggy"}
    for _ in range(4000):
        amount = f"{rng.randint(1, 50000) / 100:.2f}"
        good = _ref("good", amount, k)
        fails = {d for d in set(chosen) | {"buggy"} if _ref(d, amount, k) != good}
        if fails and amount not in cases:
            cases.append(amount)
            need -= fails
        if not need and len(cases) >= 3:
            break
    else:
        raise RuntimeError("не нашлись тестовые суммы")
    while len(cases) < 5:
        amount = f"{rng.randint(1, 500) * 10}.00"
        if amount not in cases:
            cases.append(amount)
    rng.shuffle(cases)
    fmt = dict(fn=fn, arg=arg, mult=mult_t)
    code = dedent(BUGGY.format(**fmt))
    tests = "\n".join(f"assert {fn}({a!r}, {p}) == {_ref('good', a, k)!r}" for a in cases)
    opts, key = make_options(rng, ("Заменить функцию на:", dedent(BODIES["good"].format(**fmt))),
                             [("Заменить функцию на:", dedent(BODIES[d].format(**fmt))) for d in chosen])
    checks = [Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False)
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, tests),
                        expect="fail"))
    example = next(a for a in cases if _ref("buggy", a, k) != _ref("good", a, k))
    stem = (f"Сервис ({ctx}) считает {what.format(p=p)}. По требованиям бухгалтерии сумма "
            f"округляется до копеек по правилу «половина — вверх» (0,125 → 0,13). Сейчас "
            f"`{fn}('{example}', {p})` возвращает `'{_ref('buggy', example, k)}'`, а должно быть "
            f"`'{_ref('good', example, k)}'`. Какое исправление верно для любых сумм, заданных "
            f"строкой с двумя знаками после запятой?")
    why = {"from_float": "Decimal(float(...)) переносит двоичную погрешность float в Decimal",
           "half_even": "quantize без rounding использует банковское округление ROUND_HALF_EVEN",
           "int_half": "умножение float на 100 даёт значения вида 100.4999…",
           "str_format": "форматирование float округляет двоичное значение, а не десятичное"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: считать в Decimal из строки и quantize с ROUND_HALF_UP. Дистракторы: "
                               + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="float_money_rounding",
                         params={"distractors": chosen, "cases": cases, "k": k})
