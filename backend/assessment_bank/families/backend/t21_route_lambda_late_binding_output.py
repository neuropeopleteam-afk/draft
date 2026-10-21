"""backend.http.t21_route_lambda_late_binding_output — predict_output (набор t21, порог Middle): позднее
связывание переменных в lambda, созданных в цикле.

Реестр маршрутов: в цикле по ресурсам в словарь кладутся обработчики-lambda, которые строят URL из префикса
версии и имени ресурса; после цикла префикс меняется. Ловушка (одна неочевидная семантика): lambda читает
переменные в момент ВЫЗОВА — без параметра по умолчанию все обработчики видят последнее значение переменной
цикла и новый префикс; параметр по умолчанию (`name=name` / `p=prefix`) фиксирует значение в момент создания.
Ключ — независимая модель «ранних» и «поздних» переменных в генераторе; проверка — исполнение показанного кода
в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.http.t21_route_lambda_late_binding_output"

CTX = [("API магазина", ["users", "orders", "cart", "items", "promo"]),
       ("API биллинга", ["invoices", "plans", "payments", "refunds", "limits"]),
       ("API доставки", ["couriers", "slots", "zones", "tracks", "quotes"]),
       ("API поддержки", ["tickets", "chats", "agents", "macros", "tags"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    names = rng.sample(pool, 3)
    v_old, v_new = rng.choice([("v1", "v2"), ("v2", "v3"), ("v1", "v3"), ("api", "api2")])
    mode = rng.choice(["late_both", "bind_name", "bind_prefix"])
    reg = rng.choice(["routes", "handlers", "urls"])
    if mode == "late_both":
        lam = 'lambda: "/" + prefix + "/" + name'
    elif mode == "bind_name":
        lam = 'lambda name=name: "/" + prefix + "/" + name'
    else:
        lam = 'lambda p=prefix: "/" + p + "/" + name'
    calls = rng.sample(names, 2)
    code = (f'prefix = "{v_old}"\n'
            f"{reg} = {{}}\n"
            f"for name in {names!r}:\n"
            f"    {reg}[name] = {lam}\n"
            f'prefix = "{v_new}"\n'
            f'print({reg}["{calls[0]}"]())\n'
            f'print({reg}["{calls[1]}"]())').replace("'", '"')
    last = names[-1]
    res = []
    for c in calls:
        nm = c if mode == "bind_name" else last
        px = v_old if mode == "bind_prefix" else v_new
        res.append(f"/{px}/{nm}")
    out = "\n".join(res)
    if mode == "late_both":
        why = (f"обе переменные lambda читает в момент вызова: name после цикла равна «{last}», prefix уже "
               f"«{v_new}» — оба вызова дают /{v_new}/{last}")
    elif mode == "bind_name":
        why = (f"name зафиксирована параметром по умолчанию в момент создания lambda, а prefix читается при вызове — "
               f"уже «{v_new}»")
    else:
        why = (f"prefix зафиксирован параметром по умолчанию p=prefix («{v_old}»), а name читается при вызове — после "
               f"цикла это «{last}», поэтому оба вызова дают /{v_old}/{last}")
    expl = (f"Ключи словаря разные, но тело lambda выполняется только при вызове: {why}. Переменная цикла name после "
            f"цикла сохраняет последнее значение «{last}».")
    stem = (f"«{ctx}»: реестр маршрутов заполняется в цикле обработчиками, которые строят URL ресурса; после "
            "регистрации версия API меняется.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"names": names, "mode": mode, "calls": calls}, language="python")
