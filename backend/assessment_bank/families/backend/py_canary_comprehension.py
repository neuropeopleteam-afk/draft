"""backend.py.canary_comprehension — predict_output (канарейка): генераторы словарей и сортировка."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.py.canary_comprehension"

DATA = [
    ("orders", "status", ["new", "paid", "shipped"], "amount", "заказы"),
    ("tickets", "priority", ["low", "high", "urgent"], "minutes", "поддержка"),
    ("tasks", "team", ["web", "api", "data"], "points", "трекер задач"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, gkey, groups, vkey, ctx = rng.choice(DATA)
    rows = [(rng.choice(groups), rng.randint(1, 9) * 10) for _ in range(rng.randint(5, 7))]
    thr = rng.choice([20, 30, 40])
    agg = rng.choice(["sum", "len", "max"])
    order = rng.choice(["value", "key"])
    lines = [f"{name} = ["] + [f'    {{"{gkey}": "{g}", "{vkey}": {v}}},' for g, v in rows] + ["]"]
    lines += [f"groups = {{}}", f"for row in {name}:",
              f"    if row[\"{vkey}\"] >= {thr}:",
              f"        groups.setdefault(row[\"{gkey}\"], []).append(row[\"{vkey}\"])",
              f"result = {{k: {agg}(v) for k, v in groups.items()}}"]
    if order == "value":
        lines.append("print(sorted(result.items(), key=lambda kv: (-kv[1], kv[0])))")
    else:
        lines.append("print(sorted(result))")
    code = "\n".join(lines)
    groups_ref: dict[str, list[int]] = {}
    for g, v in rows:
        if v >= thr:
            groups_ref.setdefault(g, []).append(v)
    fn = {"sum": sum, "len": len, "max": max}[agg]
    res = {k: fn(v) for k, v in groups_ref.items()}
    out = repr(sorted(res.items(), key=lambda kv: (-kv[1], kv[0]))) if order == "value" else repr(sorted(res))
    stem = f"Что напечатает программа ({ctx})? Запишите вывод точно в том виде, в каком его печатает Python."
    ak = AnswerKey(kind="output", value=out,
                   explanation="Фильтр ≥ порога до группировки; sorted по (-значение, ключ) или по ключам.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"agg": agg, "order": order})
