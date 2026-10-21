"""qa.data.t21_mutable_default_output — predict_output (набор t21, порог Middle): фабрика тестовых данных
с изменяемым значением по умолчанию `def make_user(name, roles=[])`.

Фабрика дописывает в список ролей роль по умолчанию и возвращает словарь, который ХРАНИТ ССЫЛКУ на этот список.
Значение по умолчанию создаётся один раз при определении функции, поэтому все вызовы без аргумента делят один
список: роль дописывается в него при каждом таком вызове, и у ранее созданных объектов список «растёт задним
числом» (по одному тесты проходят, вместе — нет). Вызов с явным списком дописывает роль В СПИСОК ВЫЗЫВАЮЩЕГО —
его переменная тоже меняется. Печать — после всех вызовов: списки, длины и проверка `is`. Отличие от
data_eng.etl.t21_default_seen_set_output (множество `seen=set()` при дедупликации, функция возвращает новый
список): здесь ловушка — общий объект внутри возвращённых данных и изменение явного аргумента. Ключ — независимая
модель ссылок на списки в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.data.t21_mutable_default_output"

# (сюжет, функция, параметр-список, ключ словаря, значение по умолчанию, имена, явный список (имя, элементы))
CTX = [("фабрика пользователей для UI-тестов", "make_user", "roles", "roles", "viewer",
        ["ann", "bob", "eve", "kim"], ("admins", ["admin"])),
       ("фабрика заказов для API-тестов", "make_order", "items", "items", "sku-1",
        ["o1", "o2", "o3", "o4"], ("promo", ["gift"])),
       ("генератор тест-кейсов регресса", "new_case", "tags", "tags", "smoke",
        ["login", "cart", "pay", "search"], ("nightly", ["slow"])),
       ("фабрика аккаунтов для нагрузочного прогона", "make_account", "flags", "flags", "trial",
        ["acc1", "acc2", "acc3", "acc4"], ("vip", ["beta"])),
       ("сборщик тестовых платежей", "make_payment", "steps", "steps", "auth",
        ["p1", "p2", "p3", "p4"], ("refund", ["hold"]))]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, par, key, dflt, names, (ev, eitems) = rng.choice(CTX)
    eitems = list(eitems)
    for _ in range(300):
        n = rng.choice([3, 3, 4])
        who = rng.sample(names, n)
        exp_pos = sorted(rng.sample(range(n), rng.choice([1, 1, 2])))  # вызовы с явным списком
        dpos = [i for i in range(n) if i not in exp_pos]
        if len(dpos) < 2:
            continue
        break
    else:
        raise RuntimeError("t21_mutable_default: не собран вариант")
    uv = [f"u{i + 1}" for i in range(n)]
    # модель: два списка — общий по умолчанию и явный список вызывающего
    shared: list[str] = []
    explicit = list(eitems)
    owner = {}
    for i in range(n):
        if i in exp_pos:
            explicit.append(dflt)
            owner[uv[i]] = "explicit"
        else:
            shared.append(dflt)
            owner[uv[i]] = "shared"
    lst = {"shared": shared, "explicit": explicit}
    # что печатаем: ранний объект по умолчанию, явный список, длины всех, сравнение is
    first_d, last_d = uv[dpos[0]], uv[dpos[-1]]
    prints, outs = [], []
    prints.append(f'print({first_d}["{key}"])')
    outs.append(repr(shared))
    prints.append(f"print({ev})")
    outs.append(repr(explicit))
    kind = rng.choice(["lens", "is", "both"])
    is_note = ""
    if kind in ("lens", "both"):
        prints.append(f'print([len(u["{key}"]) for u in ({", ".join(uv)})])')
        outs.append(repr([len(lst[owner[u]]) for u in uv]))
    if kind in ("is", "both"):
        a = rng.choice([u for u in uv if u != last_d]) if rng.random() < 0.5 else uv[exp_pos[0]]
        b = last_d if a != last_d else first_d
        prints.append(f'print({a}["{key}"] is {b}["{key}"])')
        outs.append(str(owner[a] == owner[b]))
        is_note = (f" {a} и {b} держат {'один и тот же список' if owner[a] == owner[b] else 'разные списки'} — "
                   f"is даёт {owner[a] == owner[b]}.")
    else:
        is_note = ""
    if rng.random() < 0.5:
        prints = [prints[1], prints[0]] + prints[2:]
        outs = [outs[1], outs[0]] + outs[2:]
    calls = []
    for i in range(n):
        if i in exp_pos:
            calls.append(f'{uv[i]} = {fn}("{who[i]}", {ev})')
        else:
            calls.append(f'{uv[i]} = {fn}("{who[i]}")')
    code = "\n".join([f"def {fn}(name, {par}=[]):", f'    {par}.append("{dflt}")',
                      f'    return {{"name": name, "{key}": {par}}}', "", f"{ev} = {eitems!r}"]
                     + calls + prints)
    out = "\n".join(outs)
    d_calls = ", ".join(uv[i] for i in dpos)
    e_calls = ", ".join(uv[i] for i in exp_pos)
    expl = (f"Список по умолчанию {par}=[] создаётся один раз — при определении {fn}. Вызовы без аргумента "
            f"({d_calls}) дописывают «{dflt}» в ОДИН И ТОТ ЖЕ список, и все эти объекты хранят ссылку на него, поэтому "
            f"после всех вызовов у каждого из них {repr(shared)} — даже у созданного первым. "
            f"{'Вызов' if len(exp_pos) == 1 else 'Вызовы'} с явным {ev} ({e_calls}) "
            f"{'дописывает' if len(exp_pos) == 1 else 'дописывают'} в список вызывающего: {ev} теперь {repr(explicit)}. Печать идёт после всех "
            f"вызовов.{is_note} Вывод по строкам: " + " / ".join(f"«{o}»" for o in outs) + ".")
    stem = f"Тестовые данные ({ctx}): программа создаёт несколько объектов через фабрику и печатает их поля."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "explicit_at": exp_pos, "kind": kind}, language="python")
