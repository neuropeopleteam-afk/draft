"""backend.cache.invalidation_bug — find_bug: ключ кэша и инвалидация (cache-aside).

Значение зависит от двух параметров (id и, например, валюта). Одна строка ломает
согласованность кэша: ключ без второго параметра (значения разных валют склеиваются),
инвалидация по константе вместо переменной цикла или по неверному аргументу (после
обновления остаются устаревшие записи). Симптом — последовательность вызовов, в которой
один из ответов неверен. Ответы дефектного кода считает модель кэша, сверка исполнением.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.cache.invalidation_bug"

# (контекст, getter, setter, префикс, id, параметр, имя таблицы множителей, множители, что хранится)
CONTEXTS = [
    ("каталог товаров", "get_price", "update_price", "price", "product_id", "currency", "RATES",
     {"RUB": 1, "KZT": 6, "AMD": 4}, "цену товара в валюте"),
    ("служба доставки", "get_delivery_cost", "set_base_cost", "delivery", "zone_id", "tariff",
     "MULTIPLIERS", {"standard": 1, "express": 2, "night": 3}, "стоимость доставки по тарифу"),
    ("оператор связи", "get_fee", "set_monthly_fee", "fee", "plan_id", "period", "MONTHS",
     {"month": 1, "quarter": 3, "year": 12}, "плату за тариф за период"),
    ("аренда жилья", "get_rent", "set_daily_rent", "rent", "flat_id", "term", "DAYS",
     {"day": 1, "week": 7, "month": 30}, "стоимость аренды за срок"),
]
SUBTYPES = ["key_missing_param", "invalidate_constant", "invalidate_wrong_arg"]


def _code(c, bug, ids_vals, order):
    _ctx, get, sett, prefix, idn, par, tname, mult, _what = c
    params = tuple(mult)
    key_ret = (f'    return f"{prefix}:{{{idn}}}"' if bug == "key_missing_param"
               else f'    return f"{prefix}:{{{idn}}}:{{{par}}}"')
    if bug == "invalidate_constant":
        pop = f"        cache.pop(cache_key({idn}, {params[0]!r}), None)"
    elif bug == "invalidate_wrong_arg":
        pop = f"        cache.pop(cache_key(value, {par}), None)"
    else:
        pop = f"        cache.pop(cache_key({idn}, {par}), None)"
    blocks = {"key": [f"def cache_key({idn}, {par}):", key_ret],
              "get": [f"def {get}({idn}, {par}):", f"    key = cache_key({idn}, {par})",
                      "    if key not in cache:", f"        cache[key] = db[{idn}] * {tname}[{par}]",
                      "    return cache[key]"],
              "set": [f"def {sett}({idn}, value):", f"    db[{idn}] = value",
                      f"    for {par} in {tname}:", pop]}
    lines = [f"{tname} = {mult!r}", f"db = {ids_vals!r}", "cache = {}"]
    for name in order:
        lines += ["", ""] + blocks[name]
    return "\n".join(lines)


def _model(bug, mult, db, ops):
    """Модель кэша с дефектом: возвращает ответы всех вызовов get."""
    db, cache, out = dict(db), {}, []
    p0 = next(iter(mult))
    key = (lambda i, p: (i,)) if bug == "key_missing_param" else (lambda i, p: (i, p))
    for op in ops:
        if op[0] == "get":
            _, i, p = op
            k = key(i, p)
            if k not in cache:
                cache[k] = db[i] * mult[p]
            out.append(cache[k])
        else:
            _, i, v = op
            db[i] = v
            for p in mult:
                if bug == "invalidate_constant":
                    cache.pop(key(i, p0), None)
                elif bug == "invalidate_wrong_arg":
                    cache.pop(key(v, p), None)
                else:
                    cache.pop(key(i, p), None)
    return out


# Калибровка 05.10: подтипы key_missing_param выделены в backend.cache.key_params_bug (варианты были неизоморфны).
SUBTYPES_HERE = ('invalidate_constant', 'invalidate_wrong_arg')


def _generate(seed: int, family_id: str, subtypes):
    rng = make_rng(family_id, seed)
    c = rng.choice(CONTEXTS)
    ctx, get, sett, _prefix, idn, par, tname, mult, what = c
    bug = rng.choice(list(subtypes))
    params = list(mult)
    ids = rng.sample(range(1, 40), 3)
    ids_vals = {i: rng.randint(5, 90) * 100 for i in ids}
    i = rng.choice(ids)
    pa = params[0] if bug == "invalidate_constant" else rng.choice(params)
    pb = rng.choice([p for p in params if p != pa])
    new = rng.choice([v for v in range(500, 9500, 100) if v != ids_vals[i] and v not in ids])
    other = rng.choice([x for x in ids if x != i])
    ops = [("get", i, pa), ("get", other, pa), ("get", i, pb), ("set", i, new), ("get", i, pb),
           ("get", i, pa)]
    if rng.random() < 0.5:
        ops[0], ops[1] = ops[1], ops[0]
    good = _model(None, mult, ids_vals, ops)
    bad = _model(bug, mult, ids_vals, ops)
    assert good != bad
    order = rng.choice([["key", "get", "set"], ["key", "set", "get"], ["get", "set", "key"],
                        ["set", "get", "key"]])
    buggy, fixed = _code(c, bug, ids_vals, order), _code(c, None, ids_vals, order)
    key_line = sorted(changed_lines(buggy, fixed))[0]
    assert changed_lines(buggy, fixed) == {key_line}
    call = lambda op: (f"{get}({op[1]}, {op[2]!r})" if op[0] == "get" else f"{sett}({op[1]}, {op[2]})")
    first_bad = next(k for k in range(len(good)) if good[k] != bad[k])
    test_lines, k = [], 0
    for op in ops:
        if op[0] == "get":
            test_lines.append(f"assert {call(op)} == {good[k]}")
            k += 1
        else:
            test_lines.append(call(op))
    test = "\n".join(test_lines)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    seq = "; ".join(f"`{call(op)}`" for op in ops)
    nth = ["первый", "второй", "третий", "четвёртый", "пятый"][first_bad]
    stem = (f"Сервис ({ctx}) кэширует {what} по схеме cache-aside: значение вычисляется из базы "
            f"при промахе, а `{sett}` меняет базу и удаляет из кэша все связанные записи. "
            f"Требование: после изменения любые чтения возвращают новое значение. Тест выполняет "
            f"по порядку: {seq}. {nth.capitalize()} вызов `{get}` возвращает `{bad[first_bad]}` "
            f"вместо `{good[first_bad]}`. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    why = {"key_missing_param": f"ключ кэша не содержит `{par}`, и значения для разных `{par}` "
                                f"перезаписывают друг друга",
           "invalidate_constant": f"в цикле удаляется запись только для {params[0]!r} вместо "
                                  f"переменной цикла `{par}`; остальные записи устаревают",
           "invalidate_wrong_arg": f"ключ для удаления строится из `value` вместо `{idn}`, "
                                   f"поэтому удаляются несуществующие записи"}[bug]
    ak = AnswerKey(kind="line", value=key_line, explanation=f"Строка {key_line}: {why}.")
    return build_variant(family_id, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="cache_staleness",
                         params={"fixed_code": fixed, "subtype": bug, "ops": [list(o) for o in ops]})



def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES_HERE)
