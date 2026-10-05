"""backend.async.missing_await_bug — find_bug: пропущенный await в асинхронном коде.

Без `await` вызов корутинной функции возвращает объект корутины: в условии он всегда
истинен (`if coro` / `if not coro`), а в арифметике даёт TypeError. Остальные вызовы
в коде написаны правильно, поэтому ответ требует понимания, а не поиска слова «await».
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.async.missing_await_bug"

# (контекст, аргумент, функция-проверка (пропустить, если истинна), её «отрицательная» форма
#  (пропустить, если ложна), хранилище флагов, функция-значение, словарь, источник, итог, описание)
CONTEXTS = [
    ("программа лояльности", "user_id", "is_blocked", "is_active", "Redis", "bonus_for", "BONUS",
     "сервису лояльности", "total_bonus", "сумму бонусов пользователей"),
    ("аналитика заказов", "order_id", "is_cancelled", "is_confirmed", "PostgreSQL", "order_amount",
     "AMOUNTS", "сервису заказов", "revenue", "выручку по заказам"),
    ("служба доставки", "courier_id", "is_offline", "is_on_shift", "Redis", "parcels_of",
     "PARCELS", "сервису логистики", "parcels_total", "число посылок у курьеров"),
    ("служба поддержки", "ticket_id", "is_spam", "is_valid", "антиспам-сервису", "minutes_spent",
     "MINUTES", "трекеру задач", "support_minutes", "время, потраченное на обращения"),
    ("биллинг", "account_id", "is_frozen", "is_open", "сервису счетов", "debt_of", "DEBTS",
     "бухгалтерии", "total_debt", "общий долг по счетам"),
]
SUBTYPES = ["cond", "arith"]


def _code(c, polarity: str, helpers_first_check: bool, flags: list[str], values: dict[str, int],
          missing: str | None, extra_const: int, doc: str) -> tuple[str, int]:
    ctx, arg, chk_pos, chk_neg, store1, val_fn, dname, store2, main, _d = c
    chk = chk_pos if polarity == "pos" else chk_neg
    set_name = "FLAGGED" if polarity == "pos" else "ALLOWED"
    check_fn = [f"async def {chk}({arg}):",
                f"    await asyncio.sleep(0)  # запрос к {store1}",
                f"    return {arg} in {set_name}"]
    value_fn = [f"async def {val_fn}({arg}):",
                f"    await asyncio.sleep(0)  # запрос к {store2}",
                f"    return {dname}.get({arg}, 0)"]
    helpers = (check_fn + ["", ""] + value_fn) if helpers_first_check else (value_fn + ["", ""] + check_fn)
    aw_c = "" if missing == "cond" else "await "
    aw_v = "" if missing == "arith" else "await "
    cond = f"    if {aw_c}{chk}({arg}):" if polarity == "pos" else f"    if not {aw_c}{chk}({arg}):"
    body = [f"async def {main}({arg}s):", "    total = 0", f"    for {arg} in {arg}s:",
            "    " + cond, "            continue", f"        total += {aw_v}{val_fn}({arg})",
            "    return total"]
    set_lit = "{" + ", ".join(repr(x) for x in flags) + "}" if flags else "set()"
    head = ["import asyncio", ""] + ([f"TIMEOUT_S = {extra_const}"] if extra_const else []) + [
        f"{set_name} = {set_lit}", f"{dname} = {values!r}", "", ""]
    if doc:
        body.insert(1, f'    """{doc}"""')
    lines = head + helpers + ["", ""] + body
    code = "\n".join(lines)
    start = len(head) + len(helpers) + 2  # индекс строки def main (с 0)
    key = start + 1 + (3 if missing == "cond" else 5) + (1 if doc else 0) if missing else 0
    return code, key


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, arg, chk_pos, chk_neg, _s1, _vf, _dn, _s2, main, descr = c
    sub = rng.choice(SUBTYPES)
    polarity = rng.choice(["pos", "neg"])
    first_check = rng.random() < 0.5
    prefix = {"user_id": "u", "order_id": "o", "courier_id": "c", "ticket_id": "t", "account_id": "a"}[arg]
    ids = [f"{prefix}{n}" for n in rng.sample(range(10, 99), rng.randint(4, 5))]
    skipped = rng.sample(ids, rng.randint(1, 2))
    values = {i: rng.randint(1, 30) * 10 for i in ids}
    flags = sorted(skipped) if polarity == "pos" else sorted(set(ids) - set(skipped))
    expected = sum(v for i, v in values.items() if i not in skipped)
    extra_const = rng.choice([0, 2, 3, 5])
    doc = rng.choice(["", f"Считает {descr}.", "Обращается к внешним сервисам асинхронно."])
    buggy, key_line = _code(c, polarity, first_check, flags, values, sub, extra_const, doc)
    fixed, _ = _code(c, polarity, first_check, flags, values, None, extra_const, doc)
    assert changed_lines(buggy, fixed) == {key_line}, (changed_lines(buggy, fixed), key_line)
    call = f"{main}({ids!r})"
    test = f"assert asyncio.run({call}) == {expected}"
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    if sub == "arith":
        symptom = "падает с `TypeError`"
        why = ("без `await` вызов возвращает объект корутины, и `total += корутина` даёт TypeError")
    elif polarity == "pos":
        symptom = "возвращает `0`"
        why = ("без `await` в условии оказывается объект корутины — он всегда истинен, поэтому "
               "цикл пропускает каждый элемент")
    else:
        symptom = f"возвращает `{sum(values.values())}`"
        why = ("без `await` в условии оказывается объект корутины — он всегда истинен, `not` даёт "
               "False, и цикл не пропускает ни одного элемента")
    rule = (f"пропускаются элементы, для которых `{chk_pos}` истинна" if polarity == "pos"
            else f"пропускаются элементы, для которых `{chk_neg}` ложна")
    stem = (f"Асинхронная функция `{main}` ({ctx}) считает {descr}; {rule}. Тест "
            f"`asyncio.run({call})` ожидает `{expected}`, но функция {symptom}. Укажите номер "
            f"строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {why}. Исправление — добавить `await`.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="missing_await",
                         params={"fixed_code": fixed, "subtype": sub, "polarity": polarity})
