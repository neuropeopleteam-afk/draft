"""backend.cache.t21_cache_key_eq_hash_output — predict_output (набор t21, порог Senior): __eq__ / __hash__ ключа
словаря-кэша.

Ключ кэша — объект с двумя полями, но __eq__ (и согласованный с ним __hash__) учитывает только одно. Ловушки:
равные по __eq__ ключи — одна запись: значение перезаписывается последним, а сам ключ-объект в словаре остаётся
ПЕРВЫМ вставленным (его второе поле не меняется); совпадение хэшей без равенства (hash = длина строки) записи
не склеивает; поиск по новому равному объекту находит запись. Ключ — независимая модель словаря (список пар
с поиском по полю равенства) в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.cache.t21_cache_key_eq_hash_output"

CTX = [("кэш ответов API", ["/orders", "/users", "/items", "/carts", "/stats", "/rates"]),
       ("кэш страниц каталога", ["/tea", "/coffee", "/cups", "/sale", "/new", "/gifts"]),
       ("кэш отчётов", ["/daily", "/weekly", "/sales", "/stock", "/churn", "/funnel"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, paths = rng.choice(CTX)
    eq_field = rng.choice(["path", "path", "user"])
    cls = rng.choice(["Key", "CacheKey", "ReqKey"])
    for _ in range(300):
        n = rng.randint(4, 5)
        ps = [rng.choice(paths[:4]) for _ in range(n)]
        us = [rng.randint(1, 9) for _ in range(n)]
        vals = [f"v{i + 1}" for i in range(n)]
        field = ps if eq_field == "path" else us
        distinct = len(set(field))
        # есть склейка, первый ключ группы с повтором стоит первым; при path — есть коллизия длины без равенства
        dup_first = field.count(field[0]) >= 2
        coll = eq_field != "path" or any(len(a) == len(b) and a != b for a in set(ps) for b in set(ps))
        if 2 <= distinct < n and dup_first and coll and len(set(zip(ps, us))) == n:
            break
    else:
        raise RuntimeError("t21_cache_key: не собраны ключи")
    probe_val = rng.choice(field)
    probe_other = rng.randint(10, 99)
    hash_expr = "len(self.path)" if eq_field == "path" else "self.user"
    triples = ", ".join(f'("{p}", {u}, "{v}")' for p, u, v in zip(ps, us, vals))
    if eq_field == "path":
        probe = f'{cls}("{probe_val}", {probe_other})'
    else:
        probe = f'{cls}("{rng.choice(paths[4:])}", {probe_val})'
    code = (f"class {cls}:\n"
            "    def __init__(self, path, user):\n"
            "        self.path, self.user = path, user\n"
            "    def __eq__(self, other):\n"
            f"        return self.{eq_field} == other.{eq_field}\n"
            "    def __hash__(self):\n"
            f"        return {hash_expr}\n"
            "cache = {}\n"
            f"for path, user, value in [{triples}]:\n"
            f"    cache[{cls}(path, user)] = value\n"
            "first = next(iter(cache))\n"
            f"print(len(cache), list(cache.values()))\n"
            f"print(first.path, first.user, cache[{probe}])")
    # модель: список [ключ (path, user), значение], поиск по полю равенства
    entries: list[list] = []
    for p, u, v in zip(ps, us, vals):
        f = p if eq_field == "path" else u
        for e in entries:
            if (e[0][0] if eq_field == "path" else e[0][1]) == f:
                e[1] = v
                break
        else:
            entries.append([(p, u), v])
    fk = entries[0][0]
    hit = [e[1] for e in entries if (e[0][0] if eq_field == "path" else e[0][1]) == probe_val][0]
    values = "[" + ", ".join(f"'{e[1]}'" for e in entries) + "]"
    out = f"{len(entries)} {values}\n{fk[0]} {fk[1]} {hit}"
    expl = (f"Равенство и хэш учитывают только {eq_field}: записи с одинаковым {eq_field} склеиваются, значение "
            f"перезаписывается последним, но ключ-объект остаётся первым вставленным. "
            + ("Одинаковая длина разных путей даёт одинаковый хэш, но __eq__ различает их — записи не склеиваются. "
               if eq_field == "path" else "")
            + f"Итого {len(entries)} записи, значения в порядке первой вставки: {values}. Первый ключ — "
              f"({fk[0]}, {fk[1]}): его поля не изменились. Поиск по новому объекту с {eq_field} = {probe_val} "
              f"находит запись со значением {hit}.")
    stem = (f"«{ctx}»: ключ кэша — объект с путём запроса и id пользователя; программа заполняет кэш и читает "
            "из него.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"eq": eq_field, "paths": ps, "users": us}, language="python")
