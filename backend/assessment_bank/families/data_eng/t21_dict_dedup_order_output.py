"""data_eng.etl.t21_dict_dedup_order_output — predict_output (набор t21, порог Junior): дедупликация по ключу через
dict — какое значение остаётся (последнее / первое / наибольшее) и в каком порядке печатаются ключи.

Программа сворачивает поток изменений по ключу в словарь и печатает его, затем — число отброшенных дублей.
Правило выбора значения зависит от варианта: `d[key] = v` (побеждает последнее), `if key not in d` (первое) или
`max(d.get(key, 0), v)` (наибольшее). Ловушка: словарь хранит ключи в порядке ПЕРВОЙ вставки, даже когда значение
перезаписано позже. Ключ — независимая модель в генераторе; проверка — исполнение кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.etl.t21_dict_dedup_order_output"

CTX = [("изменения балансов клиентов", "balance", ["u7", "u3", "u9", "u4", "u12", "u5"]),
       ("обновления цен товаров", "price", ["sku1", "sku4", "sku2", "sku8", "sku5", "sku3"]),
       ("статусы доставок из очереди", "attempt", ["d41", "d17", "d23", "d08", "d35", "d50"]),
       ("показания счётчиков", "value", ["m2", "m6", "m1", "m9", "m4", "m7"]),
       ("остатки товаров по складам", "qty", ["w3", "w1", "w5", "w8", "w2", "w6"])]
RULES = ["last", "first", "max"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, val, keys_pool = rng.choice(CTX)
    rule = rng.choice(RULES)
    dname = {"last": "latest", "first": "first_seen", "max": "best"}[rule]
    for _ in range(500):
        n_keys = rng.randint(3, 4)
        keys = rng.sample(keys_pool, n_keys)
        rows = [(k, rng.randint(1, 99)) for k in keys]
        for _ in range(rng.randint(2, 3)):
            rows.append((rng.choice(keys), rng.randint(1, 99)))
        rng.shuffle(rows)
        d: dict[str, int] = {}
        for k, v in rows:
            if rule == "last":
                d[k] = v
            elif rule == "first":
                if k not in d:
                    d[k] = v
            else:
                d[k] = max(d.get(k, 0), v)
        firsts = {}
        for k, v in rows:
            firsts.setdefault(k, v)
        lasts = dict(rows)
        # ловушка должна «работать»: правило меняет значение хотя бы у одного ключа, и порядок первой вставки
        # отличается от порядка последних появлений
        last_order = sorted(d, key=lambda k: max(i for i, (kk, _) in enumerate(rows) if kk == k))
        differs = (any(firsts[k] != lasts[k] for k in d) and list(d) != last_order
                   and len({v for _, v in rows}) == len(rows))
        if differs and len(rows) <= 7:
            break
    else:
        raise RuntimeError("t21_dict_dedup_order: не собрался поток")
    lst = ", ".join(f'("{k}", {v})' for k, v in rows)
    if rule == "last":
        body = f"for key, {val} in rows:\n    {dname}[key] = {val}\n"
    elif rule == "first":
        body = f"for key, {val} in rows:\n    if key not in {dname}:\n        {dname}[key] = {val}\n"
    else:
        body = f"for key, {val} in rows:\n    {dname}[key] = max({dname}.get(key, 0), {val})\n"
    code = (f"rows = [{lst}]\n"
            f"{dname} = {{}}\n"
            + body +
            f"for key in {dname}:\n"
            f"    print(key, {dname}[key])\n"
            f"print(len(rows) - len({dname}))")
    out = "\n".join(f"{k} {v}" for k, v in d.items()) + f"\n{len(rows) - len(d)}"
    rule_txt = {"last": "каждое присваивание перезаписывает значение — остаётся последнее",
                "first": "значение записывается только при первом появлении ключа — остаётся первое",
                "max": "остаётся наибольшее из значений ключа (стартовое 0 из get меньше любого)"}[rule]
    expl = (f"Правило: {rule_txt}. Порядок ключей в dict — порядок первой вставки: {', '.join(d)}, даже если значение "
            f"обновилось позже. Итог: " + ", ".join(f"{k} {v}" for k, v in d.items())
            + f"; дублей отброшено {len(rows)} − {len(d)} = {len(rows) - len(d)}.")
    stem = f"Поток «{ctx}» приходит с повторами ключей; программа сворачивает его по ключу перед загрузкой."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"rule": rule, "rows": len(rows), "keys": n_keys}, language="python")
