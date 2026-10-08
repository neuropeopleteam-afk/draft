"""backend.go.slice_append_output — predict_output: срезы Go с общим базовым массивом.

Один подтип: все append укладываются в ёмкость (cap), поэтому срезы `head` и `ext` пишут в тот же
базовый массив, что и исходный срез. Ловушки: append к короткому срезу затирает элемент исходного,
присваивание по индексу в «новом» срезе меняет исходный, второй append к `head` пишет дальше.
Рост ёмкости (политика runtime) в семействе не используется — ответ однозначен по спецификации языка.
Ключ — независимая модель (массив + окна среза), сверка исполнением показанного кода (`go run -race`).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.go.slice_append_output"

# (контекст, имена: исходный, короткий, расширенный)
CONTEXTS = [("очередь задач", ("tasks", "head", "more")), ("цены товаров", ("prices", "top", "ext")),
            ("оценки за ревью", ("scores", "first", "all")), ("замеры температуры", ("temps", "morning", "full")),
            ("остатки на складе", ("stock", "part", "grown")), ("баллы участников", ("points", "lead", "extra"))]


def _fmt(xs: list[int]) -> str:
    return "[" + " ".join(str(x) for x in xs) + "]"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, (a, b, c) = rng.choice(CONTEXTS)
    n = rng.choice([3, 4])
    cap = rng.randint(n + 2, n + 4)
    vals = rng.sample(range(1, 60), n)
    k = rng.randint(1, n - 1)
    x, y, z, w = rng.sample(range(60, 99), 4)
    i = rng.randint(0, n - 1)
    order = rng.choice(["ext_first", "head_first"])
    # модель: общий базовый массив длины cap
    arr = [0] * cap
    arr[:n] = vals
    lines = [f"\t{a} := make([]int, 0, {cap})",
             f"\t{a} = append({a}, {', '.join(map(str, vals))})",
             f"\t{b} := {a}[:{k}]"]
    head_len = k
    ops_head = [f"\t{b} = append({b}, {x})"]
    ops_ext = [f"\t{c} := append({a}, {y})", f"\t{c}[{i}] = {z}"]
    if order == "head_first":
        body = ops_head + ops_ext
    else:
        body = ops_ext + ops_head
    for line in body:
        if line.startswith(f"\t{b} = append"):
            arr[head_len] = x
            head_len += 1
        elif line.startswith(f"\t{c} := append"):
            arr[n] = y
        else:
            arr[i] = z
    lines += body
    lines.append(f"\t{b} = append({b}, {w})")
    arr[head_len] = w
    head_len += 1
    out = [f"{a}: {_fmt(arr[:n])} len={n}", f"{b}: {_fmt(arr[:head_len])} len={head_len}",
           f"{c}: {_fmt(arr[:n + 1])} len={n + 1} cap={cap}"]
    prints = [f'\tfmt.Printf("{a}: %v len=%d\\n", {a}, len({a}))',
              f'\tfmt.Printf("{b}: %v len=%d\\n", {b}, len({b}))',
              f'\tfmt.Printf("{c}: %v len=%d cap=%d\\n", {c}, len({c}), cap({c}))']
    code = "\n".join(["package main", "", 'import "fmt"', "", "func main() {"] + lines + prints + ["}"]) + "\n"
    expected = "\n".join(out)
    checks = [Check(name="run", runner="go", program=code, expect="stdout_equals", expected_stdout=expected)]
    stem = (f"Программа на Go работает со срезами ({ctx}). Что она выведет? Запишите вывод построчно "
            f"точно в формате программы.")
    why = (f"Ёмкость {cap} больше длины, поэтому все append пишут в общий базовый массив: append к `{b}` "
           f"(длина {k}) записывает элемент на место {a}[{k}], `{c}` делит массив с `{a}`, и `{c}[{i}] = {z}` "
           f"меняет `{a}[{i}]`; второй append к `{b}` пишет в следующую ячейку того же массива.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"cap": cap, "n": n, "k": k, "i": i, "order": order})
