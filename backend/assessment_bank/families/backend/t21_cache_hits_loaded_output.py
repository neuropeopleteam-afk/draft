"""backend.cache.t21_cache_hits_loaded_output — predict_output (набор t21, порог Стажёра): кэш-словарь, который
заполняется по ходу цикла.

Обработчик получает поток запросов по id. Если id уже есть в словаре-кэше — попадание (hits += 1), иначе ответ
«читается из БД» и кладётся в кэш. Ловушка: первое обращение к id — всегда промах, повторные — попадания;
list(cache) печатает ключи в порядке добавления (первых обращений). Ключ — независимая модель
(подсчёт первых вхождений) в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.cache.t21_cache_hits_loaded_output"

CTX = [("профили пользователей", "user_id", "profile"), ("карточки товаров", "product_id", "product"),
       ("настройки магазинов", "shop_id", "settings"), ("тарифы клиентов", "client_id", "tariff"),
       ("права доступа", "role_id", "acl")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, key_name, val = rng.choice(CTX)
    for _ in range(200):
        pool = rng.sample(range(2, 60), rng.randint(3, 4))
        reqs = [rng.choice(pool) for _ in range(rng.randint(6, 8))]
        if len(set(reqs)) >= 3 and len(set(reqs)) < len(reqs) and reqs[0] != reqs[1]:
            break
    else:
        raise RuntimeError("t21_cache_hits: не собран поток запросов")
    var = rng.choice(["requests", "incoming", "ids"])
    code = (f"{var} = {reqs}\n"
            "cache, hits = {}, 0\n"
            f"for {key_name} in {var}:\n"
            f"    if {key_name} in cache:\n"
            "        hits += 1\n"
            "    else:\n"
            f"        cache[{key_name}] = \"{val}\"\n"
            "print(hits, list(cache))")
    first_seen: list[int] = []
    for i, r in enumerate(reqs):
        if r not in reqs[:i]:
            first_seen.append(r)
    hits = len(reqs) - len(first_seen)
    keys = f"[{', '.join(str(x) for x in first_seen)}]"
    out = f"{hits} {keys}"
    expl = (f"Запросов {len(reqs)}, различных id {len(first_seen)}: первое обращение к каждому id — промах (id "
            f"кладётся в кэш), все повторные — попадания: {len(reqs)} − {len(first_seen)} = {hits}. list(cache) — "
            f"ключи словаря в порядке добавления, то есть первых обращений: {keys}. Вывод: «{out}».")
    stem = (f"Сервис «{ctx}» кэширует ответы БД в словаре; программа прогоняет поток запросов по {key_name} и "
            "считает попадания в кэш.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"requests": reqs}, language="python")
