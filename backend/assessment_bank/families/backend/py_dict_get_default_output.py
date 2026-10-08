"""backend.py.dict_get_default_output — predict_output: dict.get со значением по умолчанию и подсчёт.

Лёгкое семейство у порога Junior (грейд «Стажёр»): словарь-счётчик заполняется в цикле через
`counts.get(key, 0) + 1`, затем печатаются два-три значения: `get` существующего ключа, `get`
отсутствующего ключа с умолчанием и без него (None), `len`. Единственная ловушка — `get` для отсутствующего
ключа не добавляет его в словарь и возвращает умолчание (или None). Исполняется Python; ключ — независимый
подсчёт в генераторе.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.py.dict_get_default_output"

CONTEXTS = [("статусы заказов", "statuses", ["new", "paid", "shipped", "cancelled"], "refunded"),
            ("HTTP-коды ответов", "codes", [200, 404, 500, 301], 418),
            ("теги статей", "tags", ["python", "sql", "docker", "git"], "rust"),
            ("города доставки", "cities", ["Рига", "Таллин", "Вильнюс", "Каунас"], "Тарту"),
            ("уровни логов", "levels", ["INFO", "WARN", "ERROR", "DEBUG"], "FATAL")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, values, missing = rng.choice(CONTEXTS)
    pool = values[: rng.randint(3, 4)]
    items = [rng.choice(pool) for _ in range(rng.randint(6, 9))]
    present = [v for v in pool if v in items]
    if len(present) < 2:
        items[0], items[1] = pool[0], pool[1]
        present = [v for v in pool if v in items]
    counts: dict = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    probe = rng.choice(present)
    default = rng.choice([0, -1, 10])
    order = rng.choice(["a", "b", "c"])
    name = rng.choice(["counts", "freq", "total_by_key", "seen"])
    prints = {"a": [f"print({name}.get({probe!r}, {default}))", f"print({name}.get({missing!r}, {default}))",
                    f"print({name}.get({missing!r}))", f"print(len({name}))"],
              "b": [f"print({name}.get({missing!r}))", f"print({name}.get({probe!r}, {default}))",
                    f"print(len({name}))", f"print({name}.get({missing!r}, {default}))"],
              "c": [f"print(len({name}))", f"print({name}.get({missing!r}, {default}))",
                    f"print({name}.get({probe!r}))", f"print({missing!r} in {name})"]}[order]
    outs = {"a": [counts[probe], default, None, len(counts)],
            "b": [None, counts[probe], len(counts), default],
            "c": [len(counts), default, counts[probe], False]}[order]
    code = "\n".join([f"{var} = {items!r}", f"{name} = {{}}", f"for item in {var}:",
                      f"    {name}[item] = {name}.get(item, 0) + 1"] + prints) + "\n"
    expected = "\n".join(str(o) for o in outs)
    stem = (f"Python ({ctx}). Что напечатает программа? Запишите вывод построчно, как печатает `print` "
            f"(отсутствие значения печатается как `None`).")
    why = (f"В цикле `get(item, 0) + 1` создаёт счётчик для каждого встреченного ключа: {probe!r} встречается "
           f"{counts[probe]} раз, разных ключей {len(counts)}. `get({missing!r}, {default})` возвращает умолчание "
           f"{default}, а `get({missing!r})` без умолчания — None; ни то, ни другое ключ в словарь не добавляет.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    checks = [Check(name="run", runner="python", program=code, expect="stdout_equals", expected_stdout=expected)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"order": order, "n": len(items)})
