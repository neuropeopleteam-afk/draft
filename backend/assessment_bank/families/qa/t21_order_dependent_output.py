"""qa.flaky.t21_order_dependent_output — predict_output (набор t21, порог Senior): тесты, зависящие от порядка, —
общий кэш модуля «прогревается» одним тестом и меняет результат другого.

Модуль держит кэш-словарь и журнал походов в «базу»; функция-загрузчик кэширует ответ — у части вариантов ключ
кэша не включает второй параметр (валюту, язык, тариф…), и следующий вызов с другим параметром получает чужое
значение. Два теста проверяют значение и/или «свежесть» (ровно один поход в базу за тест, ровно один поход
всего). Прогон в порядке A→B и B→A — в одном процессе: между прогонами сбрасывается кэш, кэш и журнал или ничего.
Печать — результаты тестов в порядке запуска и размер кэша. Ядро — изоляция тестов: результат зависит от порядка и
от того, что осталось от предыдущего прогона; отличие от qa.data.t21_mutable_default_output (общий список из
значения по умолчанию) — явное состояние модуля, неполный ключ кэша и проверки на число обращений.
Ключ — независимая модель кэша в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.flaky.t21_order_dependent_output"

# (сюжет, словарь данных, функция, имя объекта, имя параметра, объекты {obj: {param: value}})
DOMAINS = [
    ("цены каталога в двух валютах", "PRICES", "get_price", "sku", "cur",
     {"book": {"RUB": 990, "USD": 11}, "pen": {"RUB": 90, "USD": 1}, "mug": {"RUB": 450, "USD": 5},
      "lamp": {"RUB": 2700, "USD": 30}}),
    ("тексты интерфейса на двух языках", "TEXTS", "get_text", "key", "lang",
     {"title": {"ru": "Заказ", "en": "Order"}, "pay": {"ru": "Оплата", "en": "Payment"},
      "cart": {"ru": "Корзина", "en": "Cart"}, "back": {"ru": "Назад", "en": "Back"}}),
    ("стоимость доставки по городам", "COST", "get_cost", "item", "city",
     {"box": {"msk": 300, "spb": 450}, "bag": {"msk": 150, "spb": 200}, "tv": {"msk": 900, "spb": 1200},
      "sofa": {"msk": 2500, "spb": 3100}}),
    ("лимиты API по тарифам", "LIMITS", "get_limit", "api", "plan",
     {"search": {"free": 100, "pro": 1000}, "export": {"free": 5, "pro": 50}, "upload": {"free": 10, "pro": 200},
      "report": {"free": 3, "pro": 30}}),
    ("таймауты сервисов по окружениям", "TIMEOUTS", "get_timeout", "svc", "env",
     {"db": {"dev": 5, "prod": 30}, "auth": {"dev": 2, "prod": 10}, "queue": {"dev": 8, "prod": 60},
      "cdn": {"dev": 1, "prod": 4}}),
]


def _lit(v):
    return f'"{v}"' if isinstance(v, str) else str(v)


def _simulate(full_key, tests, resets, data):
    cache, calls, runs, notes = {}, [], [], []
    for ri, order in enumerate([[0, 1], [1, 0]]):
        if "cache" in resets:
            cache.clear()
        if "calls" in resets:
            calls.clear()
        res = []
        for ti in order:
            name, obj, prm, kind = tests[ti]
            k = (obj, prm) if full_key else obj
            before = len(calls)
            hit = k in cache
            if not hit:
                calls.append(obj)
                cache[k] = data[obj][prm]
            v = cache[k]
            ok = v == data[obj][prm]
            if kind == "fresh":
                ok = ok and len(calls) == before + 1
            elif kind == "first":
                ok = ok and len(calls) == 1
            res.append((name, ok))
            notes.append((ri, name, hit, v, len(calls), ok))
        runs.append((res, len(cache)))
    return runs, notes


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, dname, fn, oname, pname, full = rng.choice(DOMAINS)
    objs = sorted(rng.sample(sorted(full), 2))
    data = {}
    for o in objs:
        f = rng.choice([1, 2, 3])
        data[o] = {p: (v * f if isinstance(v, int) else v) for p, v in full[o].items()}
    params = sorted(next(iter(data.values())))
    for _ in range(500):
        full_key = rng.random() < 0.35
        p1, p2 = rng.sample(params, 2)
        o1 = rng.choice(objs)
        o2 = o1 if rng.random() < 0.75 else next(o for o in objs if o != o1)
        kinds = [rng.choice(["value", "value", "fresh", "first"]), rng.choice(["value", "fresh", "fresh", "first"])]
        if full_key and kinds == ["value", "value"]:
            continue
        resets = rng.choice([(), ("cache",), ("cache", "calls")])
        tests = [(f"test_{p1.lower()}", o1, p1, kinds[0]), (f"test_{p2.lower()}", o2, p2, kinds[1])]
        runs, notes = _simulate(full_key, tests, resets, data)
        r1 = dict(runs[0][0])
        r2 = dict(runs[1][0])
        if r1 == r2:
            continue
        break
    else:
        raise RuntimeError("t21_order_dependent: не собран вариант")
    data_lit = "{" + ", ".join(f'"{o}": {{' + ", ".join(f'"{p}": {_lit(v)}' for p, v in data[o].items()) + "}"
                               for o in objs) + "}"
    lines = [f"{dname} = {data_lit}", "cache, calls = {}, []", "",
             f"def {fn}({oname}, {pname}):"]
    if full_key:
        lines += [f"    k = ({oname}, {pname})", "    if k not in cache:", f"        calls.append({oname})",
                  f"        cache[k] = {dname}[{oname}][{pname}]", "    return cache[k]"]
    else:
        lines += [f"    if {oname} not in cache:", f"        calls.append({oname})",
                  f"        cache[{oname}] = {dname}[{oname}][{pname}]", f"    return cache[{oname}]"]
    for name, obj, prm, kind in tests:
        call = f'{fn}("{obj}", "{prm}") == {_lit(data[obj][prm])}'
        lines += ["", f"def {name}():"]
        if kind == "fresh":
            lines += ["    before = len(calls)", f"    return {call} and len(calls) == before + 1"]
        elif kind == "first":
            lines += [f"    return {call} and len(calls) == 1"]
        else:
            lines += [f"    return {call}"]
    a, b = tests[0][0], tests[1][0]
    lines += ["", f"for order in (({a}, {b}), ({b}, {a})):"]
    if "cache" in resets:
        lines.append("    cache.clear()")
    if "calls" in resets:
        lines.append("    calls.clear()")
    lines.append("    print({t.__name__: t() for t in order}, len(cache))")
    code = "\n".join(lines)
    n_lines = sum(1 for ln in lines if ln.strip())
    outs = ["{" + ", ".join(f"'{n}': {ok}" for n, ok in res) + "}" + f" {size}" for res, size in runs]
    out = "\n".join(outs)
    if full_key:
        key_note = f"ключ кэша — пара ({oname}, {pname}), значения для разных {pname} не смешиваются"
    elif o1 == o2:
        key_note = (f"ключ кэша — только {oname}: {pname} в ключ не входит, и второй вызов с тем же {oname} получает "
                    f"значение, закэшированное для другого {pname}")
    else:
        key_note = (f"ключ кэша — только {oname} ({pname} в ключ не входит), но тесты берут разные {oname} — "
                    f"значения не смешиваются, важны только попадания в кэш")
    rs = {(): "между прогонами ничего не сбрасывается — второй прогон начинается с тем, что оставил первый",
          ("cache",): "перед каждым прогоном сбрасывается только кэш, журнал calls копится",
          ("cache", "calls"): "перед каждым прогоном сбрасываются и кэш, и журнал calls"}[resets]
    per_run = {0: [], 1: []}
    for ri, name, hit, v, ncalls, ok in notes:
        per_run[ri].append(f"{name} — {'попадание в кэш' if hit else 'промах, поход в базу'}, значение {_lit(v)}, "
                           f"len(calls) = {ncalls} → {ok}")
    steps_txt = "; ".join(f"прогон {ri + 1}: " + ", затем ".join(per_run[ri]) + f" (в кэше {runs[ri][1]})"
                          for ri in (0, 1))
    expl = (f"Кэш и журнал calls — общие для всех тестов модуля; {key_note}; {rs}. Проверки: "
            + ", ".join(f"{n} — " + {"value": "только значение", "fresh": "значение и ровно один поход в базу за "
                                     "тест", "first": "значение и ровно один поход в базу всего"}[k]
                        for n, _o, _p, k in tests)
            + f". Ход: {steps_txt}. Вывод по строкам: " + " / ".join(f"«{o}»" for o in outs) + ".")
    stem = (f"Автотесты ({plot}): два теста работают с общим кэшем модуля, и их прогоняют в обоих порядках в одном "
            f"процессе.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"full_key": full_key, "tests": [list(t) for t in tests], "resets": list(resets),
                                  "lines": n_lines}, language="python")
