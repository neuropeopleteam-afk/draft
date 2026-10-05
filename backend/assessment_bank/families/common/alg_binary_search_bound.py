"""common.alg.binary_search_bound — find_bug: граничная ошибка в бинарном поиске."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, dedent, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.alg.binary_search_bound"

CONTEXTS = [
    ("timestamps", "moment", "временные метки событий журнала (секунды от начала суток)", "журнал"),
    ("prices", "budget", "цены товаров в каталоге (в рублях)", "каталог"),
    ("order_ids", "order_id", "номера заказов, уже переданных в доставку", "доставка"),
    ("marks", "km", "отметки пройденного расстояния на маршруте (км)", "маршрут"),
    ("amounts", "limit", "суммы транзакций за день (в рублях)", "платежи"),
    ("scores", "score", "баллы участников олимпиады", "олимпиада"),
    ("builds", "build", "номера сборок, прошедших тесты", "сборки"),
    ("latencies", "threshold", "время ответа сервиса по запросам (мс)", "мониторинг"),
]
NAMES = [("lo", "hi", "mid"), ("left", "right", "middle"), ("low", "high", "mid"), ("l", "r", "m")]
LOWER = ["count_less", "lower_bound", "first_not_less", "left_border", "bisect_left_index"]
UPPER = ["count_not_greater", "upper_bound", "first_greater", "right_border", "bisect_right_index"]
DEFECTS = ["hi_init", "cmp_boundary", "hi_shift"]


def _func(name: str, arr: str, x: str, kind: str, nm: tuple[str, str, str], hints: bool,
          guard: bool, defect: str | None) -> list[str]:
    lo, hi, mid = nm
    cmp = "<" if kind == "lower" else "<="
    if defect == "cmp_boundary":
        cmp = "<=" if kind == "lower" else "<"
    doc = ("Индекс первого элемента, который не меньше {x} (= число элементов < {x})."
           if kind == "lower" else
           "Индекс первого элемента, который больше {x} (= число элементов <= {x}).").format(x=x)
    sig = f"def {name}({arr}: list[int], {x}: int) -> int:" if hints else f"def {name}({arr}, {x}):"
    lines = [sig, f'    """{doc}"""']
    if guard:
        lines += [f"    if not {arr}:", "        return 0"]
    hi_init = f"len({arr}) - 1" if defect == "hi_init" else f"len({arr})"
    lines += [
        f"    {lo}, {hi} = 0, {hi_init}",
        f"    while {lo} < {hi}:",
        f"        {mid} = ({lo} + {hi}) // 2",
        f"        if {arr}[{mid}] {cmp} {x}:",
        f"            {lo} = {mid} + 1",
        "        else:",
        f"            {hi} = {mid} - 1" if defect == "hi_shift" else f"            {hi} = {mid}",
        f"    return {lo}",
    ]
    return lines


def _ref(arr: list[int], x: int, kind: str) -> int:
    return sum(1 for v in arr if (v < x if kind == "lower" else v <= x))


def _build(rng, defect: str | None, layout: str, ctx, nm, hints, guards, names, target):
    arr, x, _, _ = ctx
    if layout == "single":
        kind = target
        fname = names[kind]
        return "\n".join(_func(fname, arr, x, kind, nm, hints, guards[0], defect))
    lines = _func(names["lower"], arr, x, "lower", nm, hints, guards[0],
                  defect if target == "lower" else None)
    lines += ["", ""]
    lines += _func(names["upper"], arr, x, "upper", nm, hints, guards[1],
                   defect if target == "upper" else None)
    lines += ["", "", f"def count_between({arr}, a, b):",
              '    """Сколько элементов лежит в отрезке [a, b]."""',
              f"    return {names['upper']}({arr}, b) - {names['lower']}({arr}, a)"]
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    arr, x, desc, ctx_name = ctx
    nm = rng.choice(NAMES)
    hints = rng.random() < 0.5
    guards = (rng.random() < 0.4, rng.random() < 0.4)
    layout = "single" if rng.random() < 0.5 else "pair"
    target = rng.choice(["lower", "upper"])
    defect = rng.choice(DEFECTS)
    names = {"lower": rng.choice(LOWER), "upper": rng.choice(UPPER)}
    buggy = _build(rng, defect, layout, ctx, nm, hints, guards, names, target)
    fixed = _build(rng, None, layout, ctx, nm, hints, guards, names, target)
    bl, fl = buggy.splitlines(), fixed.splitlines()
    key_line = next(i + 1 for i, (a, b) in enumerate(zip(bl, fl)) if a != b)

    base = rng.randrange(1, 60)
    example = sorted(base + rng.randrange(0, 40) for _ in range(rng.randint(5, 8)))
    dup = rng.choice(example)
    example = sorted(example + [dup])
    if layout == "single":
        kind = target
        fname = names[kind]
        ex_x = rng.choice([dup, rng.choice(example) + 1, example[-1] + rng.randint(1, 5)])
        call = f"{fname}({arr}, {ex_x})"
        expected = _ref(example, ex_x, kind)
        what = ("индекс первого элемента, который не меньше заданного значения (то есть "
                "количество элементов, строго меньших его)" if kind == "lower" else
                "индекс первого элемента, который строго больше заданного значения (то есть "
                "количество элементов, не превосходящих его)")
        task = f"Функция `{fname}` должна возвращать {what}."
    else:
        a = rng.choice(example)
        b = a + rng.randint(3, 25)
        call = f"count_between({arr}, {a}, {b})"
        expected = _ref(example, b, "upper") - _ref(example, a, "lower")
        task = (f"Функции `{names['lower']}` и `{names['upper']}` ищут границы в отсортированном "
                f"списке, а `count_between` считает, сколько элементов попадает в отрезок [a, b] "
                f"включительно.")
    stem = (f"Список `{arr}` содержит {desc}, отсортированные по возрастанию; возможны повторы. "
            f"{task}\n\nПример: для `{arr} = {example}` вызов `{call}` должен вернуть `{expected}`."
            f"\n\nВ коде ровно одна ошибка. Укажите номер строки, в которой она находится.")

    tests = []
    rnd_arrays = [example, [], [5], [2, 2, 2], sorted(rng.randrange(0, 30) for _ in range(9))]
    fn_lower = names["lower"] if layout == "pair" or target == "lower" else None
    fn_upper = names["upper"] if layout == "pair" or target == "upper" else None
    tests.append(f"arrays = {rnd_arrays!r}")
    tests.append("for arr in arrays:")
    tests.append("    for x in range(-2, (max(arr) if arr else 0) + 4):")
    if fn_lower:
        tests.append(f"        assert {fn_lower}(arr, x) == sum(1 for v in arr if v < x), ('lower', arr, x)")
    if fn_upper:
        tests.append(f"        assert {fn_upper}(arr, x) == sum(1 for v in arr if v <= x), ('upper', arr, x)")
    if layout == "pair":
        tests.append("        assert count_between(arr, x, x + 3) == sum(1 for v in arr if x <= v <= x + 3)")
    body = "\n".join(tests)
    checks = [
        Check(name="buggy_fails", runner="python", program=py_harness(buggy, body), expect="fail"),
        Check(name="fixed_passes", runner="python", program=py_harness(fixed, body), expect="pass",
              embeds_display_code=False),
    ]
    defect_ru = {"hi_init": "правая граница инициализирована как len - 1, поэтому ответ len "
                            "(все элементы меньше x) недостижим",
                 "cmp_boundary": "в сравнении перепутаны строгое и нестрогое неравенство: "
                                 "неверно обрабатываются элементы, равные x",
                 "hi_shift": "при сужении справа используется mid - 1, хотя элемент mid ещё может "
                             "быть ответом"}[defect]
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {defect_ru}. Исправление: "
                               f"`{fl[key_line - 1].strip()}`.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx_name,
                         verification="execution", checks=checks, defect_type="off_by_one",
                         params={"fixed_code": fixed, "defect": defect, "layout": layout,
                                 "target": target})
