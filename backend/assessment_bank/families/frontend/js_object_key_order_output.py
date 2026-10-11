"""frontend.js.object_key_order_output — predict_output: порядок ключей объекта в JavaScript.

Порог Middle/Senior. Порядок обхода собственных строковых ключей (ECMAScript, OrdinaryOwnPropertyKeys):
сначала ключи-индексы массива («0», «7», «42» — без ведущих нулей, без знака и дробной части) по возрастанию,
затем остальные строки в порядке добавления; удаление и повторное добавление переносит строковый ключ в конец,
а ключ-индекс остаётся на своём месте по числу. Ловушки: «01», «-1», «1.5» — не индексы.
Ключ — независимая модель в генераторе, сверяется с исполнением в Node.
"""
from __future__ import annotations

import re

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import output_variant

FAMILY_ID = "frontend.js.object_key_order_output"

CONTEXTS = [("остатки по размерам", "stock"), ("места в зале", "seats"), ("этажи здания", "floors"),
            ("версии документа", "versions"), ("коды ответов", "counters"), ("номера полок", "shelves")]
INT_KEYS = ["0", "2", "3", "7", "10", "12", "42", "100"]
TRICKY = ["01", "-1", "1.5", "007", "+3"]
WORDS = ["a", "b", "x", "total", "misc", "S", "M", "XL", "new"]
_INDEX = re.compile(r"^(0|[1-9][0-9]*)$")


def _model(ops):
    keys: list[str] = []
    for op, k in ops:
        if op == "set" and k not in keys:
            keys.append(k)
        elif op == "del" and k in keys:
            keys.remove(k)
    ints = sorted((k for k in keys if _INDEX.match(k)), key=int)
    return ints + [k for k in keys if not _INDEX.match(k)]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, name = rng.choice(CONTEXTS)
    ints = rng.sample(INT_KEYS, rng.randint(2, 3))
    if ints == sorted(ints, key=int):
        ints.reverse()
    keys = ints + rng.sample(TRICKY, 1) + rng.sample(WORDS, rng.randint(2, 3))
    rng.shuffle(keys)
    first_word = next(k for k in keys if not _INDEX.match(k))
    if keys[-1] == first_word or keys.index(first_word) == len(keys) - 1:
        keys.remove(first_word)
        keys.insert(0, first_word)
    moved = rng.choice([first_word, rng.choice(ints)])
    ops = [("set", k) for k in keys] + [("del", moved), ("set", moved)]
    lines = [f"const {name} = {{}};"]
    for i, k in enumerate(keys):
        lines.append(f'{name}["{k}"] = {i + 1};')
    lines += [f'delete {name}["{moved}"];', f'{name}["{moved}"] = {len(keys) + 1};',
              f'console.log(Object.keys({name}).join(","));',
              f'console.log(Object.values({name}).join(","));']
    code = "\n".join(lines) + "\n"
    order = _model(ops)
    vals = {k: i + 1 for i, k in enumerate(keys)}
    vals[moved] = len(keys) + 1
    expected = ",".join(order) + "\n" + ",".join(str(vals[k]) for k in order)
    stem = (f"JavaScript ({ctx}). Что напечатает программа? Запишите две строки вывода точно так, как их "
            f"печатает `console.log`.")
    why = ("Собственные строковые ключи обходятся так: сначала ключи-индексы («0», «7», «42» — каноническая запись "
           "целого без знака, ведущих нулей и дробной части) по возрастанию числа, затем остальные строки в "
           "порядке добавления. После `delete` и повторного присваивания строковый ключ встаёт в конец, а ключ-"
           "индекс снова занимает место по числу. «01», «-1», «1.5», «+3» — обычные строки. "
           f"Порядок: {', '.join(order)}.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, expected=expected, runner="node", context=ctx,
                          why=why, params={"keys": keys, "moved": moved})
