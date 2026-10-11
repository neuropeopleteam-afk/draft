"""backend.cache.stampede_fix — choose_fix: одновременные промахи кэша вызывают загрузку многократно.

Порог Middle/Senior. Асинхронный кэш без защиты: N одновременных запросов одного ключа — N загрузок из БД
(«давка» кэша). Требования: одна загрузка на ключ при одновременных запросах; ошибка загрузки не кэшируется
(следующий запрос пробует снова). Варианты замены (состав фиксирован, один подтип):
* верный — замок на ключ и повторная проверка кэша под замком;
* замок на ключ, но проверка кэша до замка, а не под ним, — загрузки идут по очереди, но их всё равно N;
* новый `asyncio.Lock()` на каждый вызов — взаимного исключения нет;
* кэш задач (`ensure_future`) — одна загрузка, но упавшая задача остаётся в кэше и ошибка повторяется.
Проверка исполнением (asyncio): 5 одновременных запросов → одна загрузка; сбой первой загрузки → следующий вызов успешен.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import fix_options_variant

FAMILY_ID = "backend.cache.stampede_fix"

CONTEXTS = [("профили пользователей", "get_profile", "user_id"), ("карточки товаров", "get_product", "sku"),
            ("курсы валют", "get_rate", "pair"), ("настройки арендатора", "get_settings", "tenant_id"),
            ("тарифы доставки", "get_tariff", "zone"), ("права доступа", "get_permissions", "role_id")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, k = rng.choice(CONTEXTS)
    cache = rng.choice(["_cache", "CACHE", "_memo"])
    locks = rng.choice(["_locks", "LOCKS", "_key_locks"])
    ld = rng.choice(["load", "fetch", "loader"])
    prelude = f"import asyncio\n\n{cache} = {{}}"
    head = f"async def {fn}({k}, {ld}):"
    hit = [f"    if {k} in {cache}:", f"        return {cache}[{k}]"]
    buggy = prelude + "\n\n\n" + "\n".join([head] + hit + [f"    value = await {ld}({k})", f"    {cache}[{k}] = value",
                                                          "    return value"]) + "\n"
    lk = f"    lock = {locks}.setdefault({k}, asyncio.Lock())"
    correct = "\n".join([f"{locks} = {{}}", "", "", head] + hit + [
        lk, "    async with lock:", f"        if {k} not in {cache}:", f"            {cache}[{k}] = await {ld}({k})",
        f"    return {cache}[{k}]"]) + "\n"
    d_no_recheck = "\n".join([f"{locks} = {{}}", "", "", head] + hit + [
        lk, f"    if {k} not in {cache}:", "        async with lock:", f"            {cache}[{k}] = await {ld}({k})",
        f"    return {cache}[{k}]"]) + "\n"
    d_new_lock = "\n".join([head] + hit + [
        "    lock = asyncio.Lock()", "    async with lock:", f"        if {k} not in {cache}:",
        f"            {cache}[{k}] = await {ld}({k})", f"    return {cache}[{k}]"]) + "\n"
    d_tasks = "\n".join([head, f"    if {k} not in {cache}:", f"        {cache}[{k}] = asyncio.ensure_future({ld}({k}))",
                         f"    return await {cache}[{k}]"]) + "\n"
    n = rng.randint(4, 8)
    key1, key2 = rng.sample(range(10, 99), 2)
    test = f"""
calls = []
async def ok_load(x):
    calls.append(x)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return {{"id": x}}
state = {{"fail": True}}
async def flaky(x):
    calls.append(x)
    await asyncio.sleep(0)
    if state["fail"]:
        state["fail"] = False
        raise ConnectionError("db")
    return {{"id": x}}
async def main():
    rs = await asyncio.gather(*[{fn}({key1}, ok_load) for _ in range({n})])
    assert all(r == {{"id": {key1}}} for r in rs)
    assert calls.count({key1}) == 1, calls
    try:
        await {fn}({key2}, flaky)
        raise AssertionError("ошибка не дошла")
    except ConnectionError:
        pass
    assert (await {fn}({key2}, flaky)) == {{"id": {key2}}}
asyncio.run(main())
"""
    stem = (f"Python, asyncio ({ctx}). После сброса кэша `{fn}` при всплеске трафика сотни одновременных запросов "
            f"одного ключа уходят в базу. Нужно: при одновременных запросах одного `{k}` — одна загрузка; если "
            f"загрузка упала, ошибка получает вызывающий, а следующий запрос пробует снова. Какая замена кода "
            f"это обеспечивает?")
    why = ("Нужен замок на ключ и повторная проверка кэша под замком: первый запрос загружает, остальные ждут замок и "
           "находят значение в кэше; исключение выходит из `async with`, в кэш ничего не попадает. Если проверять кэш до "
           "замка, а не под ним, все запросы проходят проверку раньше первой загрузки — загрузки идут по очереди, но их столько же; новый замок на каждый вызов ничего не исключает; "
           "кэш задач даёт одну загрузку, но упавшая задача остаётся в кэше, и ошибка повторяется у всех следующих.")
    return fix_options_variant(FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct,
                               distractors=[d_no_recheck, d_new_lock, d_tasks], test=test, prelude=prelude,
                               context=ctx, defect="cache_stampede", why=why, label="Заменить код на:",
                               params={"n": n, "keys": [key1, key2]})
