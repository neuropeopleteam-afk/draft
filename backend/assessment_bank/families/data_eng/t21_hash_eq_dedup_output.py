"""data_eng.etl.t21_hash_eq_dedup_output — predict_output (набор t21, порог Senior): дедупликация записей через set
объектов с собственными __eq__ / __hash__ рядом со словарём «последняя версия по ключу».

Варианты класса: (a) только __hash__ по ключу — равенство остаётся по идентичности, set не сворачивает ничего;
(b) __eq__ и __hash__ по ключу — set сворачивает по ключу и ХРАНИТ ПЕРВЫЙ добавленный объект (повторное add
равного элемента его не заменяет); (c) __eq__ по (ключ, версия), __hash__ по ключу — сворачиваются только полные
копии. Словарь `{e.key: e.version ...}` всегда хранит последнюю версию. Ключ — независимая модель в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.etl.t21_hash_eq_dedup_output"

CTX = [("изменения заказов из очереди", "Change", "order_id"), ("версии карточек товаров", "Card", "sku"),
       ("события профиля клиента", "Event", "client_id"), ("обновления остатков", "StockRow", "item_id"),
       ("записи журнала платежей", "Payment", "payment_id")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cls, key = rng.choice(CTX)
    mode = rng.choice(["hash_only", "key_eq", "key_eq", "full_eq"])
    for _ in range(500):
        keys = rng.sample(range(101, 140), rng.randint(2, 3))
        rows = []
        for k in keys:
            vs = sorted(rng.sample(range(1, 6), rng.randint(1, 3)))
            rows += [(k, v) for v in vs]
        dup = rng.choice(rows)
        rows.append(dup)                       # полная копия одной записи
        rng.shuffle(rows)
        firsts, lasts = {}, {}
        for k, v in rows:
            firsts.setdefault(k, v)
            lasts[k] = v
        if (5 <= len(rows) <= 7 and any(firsts[k] != lasts[k] for k in firsts)
                and sum(firsts.values()) != sum(lasts.values())):
            break
    else:
        raise RuntimeError("t21_hash_eq_dedup: не собрались записи")
    if mode == "hash_only":
        kept = rows
        methods = ""
    elif mode == "key_eq":
        kept = [(k, v) for k, v in firsts.items()]
        methods = (f"    def __eq__(self, other):\n"
                   f"        return self.{key} == other.{key}\n")
    else:
        kept = list(dict.fromkeys(rows))
        methods = (f"    def __eq__(self, other):\n"
                   f"        return (self.{key}, self.version) == (other.{key}, other.version)\n")
    lst = ", ".join(f"({k}, {v})" for k, v in rows)
    code = (f"class {cls}:\n"
            f"    def __init__(self, {key}, version):\n"
            f"        self.{key}, self.version = {key}, version\n"
            + methods +
            f"    def __hash__(self):\n"
            f"        return hash(self.{key})\n"
            f"rows = [{lst}]\n"
            f"items = [{cls}(k, v) for k, v in rows]\n"
            f"unique = set(items)\n"
            f"latest = {{e.{key}: e.version for e in items}}\n"
            f"print(len(unique), sum(e.version for e in unique))\n"
            f"print(len(latest), sum(latest.values()))")
    out = f"{len(kept)} {sum(v for _, v in kept)}\n{len(lasts)} {sum(lasts.values())}"
    if mode == "hash_only":
        why = ("__eq__ не переопределён: объекты равны только сами себе, одинаковый хэш лишь кладёт их в одну "
               "корзину — "
               f"set хранит все {len(rows)} {plural(len(rows), 'объект', 'объекта', 'объектов')}")
    elif mode == "key_eq":
        why = (f"__eq__ и __hash__ по {key}: set сворачивает записи по ключу и оставляет первый добавленный объект "
               f"(версии {', '.join(f'{k}→{v}' for k, v in firsts.items())}), повторное добавление равного его не "
               "заменяет")
    else:
        why = (f"__eq__ по ({key}, version): сворачивается только полная копия {dup}, разные версии одного ключа "
               f"остаются — {len(kept)} {plural(len(kept), 'объект', 'объекта', 'объектов')}")
    expl = (f"{why[0].upper() + why[1:]}; сумма их версий {sum(v for _, v in kept)}. Словарь перезаписывает значение "
            f"при каждом ключе и хранит последнюю версию: {', '.join(f'{k}→{v}' for k, v in lasts.items())}, "
            f"сумма {sum(lasts.values())}. Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Поток «{ctx}» содержит повторы; программа сворачивает записи через set объектов и через словарь по "
            "ключу и сравнивает результат.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"mode": mode, "rows": len(rows)}, language="python")
