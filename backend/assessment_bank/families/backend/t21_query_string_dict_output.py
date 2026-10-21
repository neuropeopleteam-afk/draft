"""backend.http.t21_query_string_dict_output — predict_output (набор t21, порог Junior): разбор query string —
split по «&» и «=» и запись в словарь.

Обработчик разбирает строку запроса вручную: `for pair in query.split("&"): key, value = pair.split("="); params[key] = value`.
Ловушки (две конструкции вместе): повторный параметр перезаписывает значение, но ключ остаётся на месте первого
появления (порядок ключей словаря — порядок первой вставки), поэтому len меньше числа пар; значения — строки;
get с умолчанием срабатывает только для отсутствующего ключа. Ключ — независимая модель в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.http.t21_query_string_dict_output"

CTX = [("каталог товаров", "/products"), ("поиск заказов", "/orders"), ("лента событий", "/events"),
       ("список пользователей", "/users"), ("журнал платежей", "/payments")]
PARAMS = {
    "page": ["1", "2", "3", "4", "7"], "limit": ["10", "20", "50", "100"], "sort": ["price", "date", "name", "id"],
    "order": ["asc", "desc"], "lang": ["ru", "en", "kk"], "status": ["new", "paid", "done"],
    "q": ["tea", "box", "lamp"], "fields": ["id", "name", "total"],
}
DEFAULTS = {"offset": "0", "per_page": "25", "region": "msk", "cursor": "none", "page": "1", "limit": "20",
            "sort": "id", "lang": "ru"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, path = rng.choice(CTX)
    keys = rng.sample(sorted(PARAMS), rng.randint(3, 4))
    pairs = [(k, rng.choice(PARAMS[k])) for k in keys]
    n_dup = rng.choice([1, 1, 2])
    for k in rng.sample(keys[:-1], min(n_dup, len(keys) - 1)):
        alt = [v for v in PARAMS[k] if v != dict(pairs)[k]]
        pairs.append((k, rng.choice(alt)))
    # перемешать хвост так, чтобы первым оставался «оригинал» каждого ключа
    head, tail = pairs[:len(keys)], pairs[len(keys):]
    mixed = head[:]
    for p in tail:
        k_pos = [i for i, (k, _) in enumerate(mixed) if k == p[0]][0]
        mixed.insert(rng.randint(k_pos + 1, len(mixed)), p)
    pairs = mixed
    query = "&".join(f"{k}={v}" for k, v in pairs)
    dup_keys = [k for k in keys if sum(1 for kk, _ in pairs if kk == k) > 1]
    look = rng.choice(dup_keys)
    present_default = rng.random() < 0.35
    if present_default:
        gkey = rng.choice([k for k in keys if k != look])
    else:
        gkey = rng.choice([k for k in DEFAULTS if k not in keys])
    gdef = DEFAULTS.get(gkey, "0") if not present_default else rng.choice(["0", "1", "all"])
    var = rng.choice(["query", "qs", "raw"])
    code = (f'{var} = "{query}"\n'
            "params = {}\n"
            f'for pair in {var}.split("&"):\n'
            '    key, value = pair.split("=")\n'
            "    params[key] = value\n"
            f'print(len(params), params["{look}"], params.get("{gkey}", "{gdef}"))\n'
            'print(",".join(params))')
    model: dict[str, str] = {}
    order: list[str] = []
    for k, v in pairs:
        if k not in order:
            order.append(k)
        model[k] = v
    got = model[gkey] if gkey in model else gdef
    out = f"{len(order)} {model[look]} {got}\n{','.join(order)}"
    expl = (f"Пар в строке {len(pairs)}, различных ключей {len(order)}: повтор «{', '.join(dup_keys)}» перезаписывает "
            f"значение — остаётся последнее ({look} = {model[look]}), но ключ сохраняет место первого появления. "
            + (f"«{gkey}» в строке есть — get возвращает его значение {got}. " if gkey in model else
               f"«{gkey}» в строке нет — get возвращает умолчание {gdef}. ")
            + f"join по словарю перебирает ключи в порядке первой вставки: {','.join(order)}.")
    stem = (f"Сервис «{ctx}»: обработчик `GET {path}` разбирает строку запроса вручную, без библиотек; программа "
            "печатает итог разбора.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pairs": pairs, "look": look, "gkey": gkey}, language="python")
