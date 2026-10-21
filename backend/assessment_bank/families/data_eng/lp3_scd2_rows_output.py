"""data_eng.dwh.lp3_scd2_rows_output — predict_output: сколько строк будет в измерении SCD2 после загрузки.

Измерение «клиент» ведётся как SCD тип 2 по отслеживаемым атрибутам (новая версия строки при изменении) и как тип 1
по остальным (перезапись текущей версии без новой строки). Загрузка повторно присылает уже записанные значения
(без изменений — новой строки нет) и новые ключи (первая версия). Нужно число строк измерения после применения
пакета изменений к начальному состоянию. Ловушки: каждая запись пакета — новая строка; изменение атрибута типа 1
считать новой версией; повтор того же значения считать изменением. Ответ — целое число.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.dwh.lp3_scd2_rows_output"
ATTRS2 = ["тариф", "город", "сегмент", "менеджер"]
ATTRS1 = ["телефон", "email", "имя в приложении"]
VALS = {"тариф": ["Базовый", "Плюс", "Премиум"], "город": ["Москва", "Казань", "Пермь", "Омск"],
        "сегмент": ["B2C", "SMB", "Enterprise"], "менеджер": ["Иванова", "Петров", "Сидорова"],
        "телефон": ["+7…01", "+7…02", "+7…03"], "email": ["a@x.ru", "b@x.ru", "c@x.ru"],
        "имя в приложении": ["Аня", "Анна", "Ан"]}

CALC = r'''
t2, cur, rows = [], {}, 0
for l in DATA.splitlines():
    if l.startswith("SCD2 по атрибутам"):
        t2 = [x.strip() for x in l.split(":", 1)[1].split(",")]
    elif l.startswith("было:"):
        k, kv = l[5:].split("|")
        cur[k.strip()] = dict(x.split("=") for x in kv.strip().split("; "))
        rows += 1
    elif l.startswith("пакет:"):
        k, a, val = [x.strip() for x in l[6:].split("|")]
        if k not in cur:
            cur[k] = {}
            rows += 1
            cur[k][a] = val
            continue
        if cur[k].get(a) == val:
            continue
        if a in t2:
            rows += 1
        cur[k][a] = val
print(rows)
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(3000):
        t2 = rng.sample(ATTRS2, 2)
        t1 = rng.sample(ATTRS1, 1)
        attrs = t2 + t1
        nk = rng.randint(3, 5)
        keys = [f"C-{rng.randint(1000, 9999)}" for _ in range(nk)]
        if len(set(keys)) != nk:
            continue
        cur = {k: {a: rng.choice(VALS[a]) for a in attrs} for k in keys}
        init = {k: dict(v) for k, v in cur.items()}
        rows = nk
        batch = []
        for _ in range(rng.randint(8, 12)):
            if rng.random() < 0.15:
                k = f"C-{rng.randint(1000, 9999)}"
                if k in keys or any(b[0] == k for b in batch):
                    continue  # новый ключ встречается в пакете один раз (иначе «изменение пустого» неоднозначно)
            else:
                k = rng.choice(keys)
            a = rng.choice(attrs)
            val = rng.choice(VALS[a])
            batch.append((k, a, val))
        st = {k: dict(v) for k, v in init.items()}
        for k, a, val in batch:
            if k not in st:
                st[k] = {a: val}
                rows += 1
                continue
            if st[k].get(a) == val:
                continue
            if a in t2:
                rows += 1
            st[k][a] = val
        good = rows
        all_rows = nk + len(batch)
        if good in (all_rows,) or good == nk:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"SCD2 по атрибутам: {', '.join(t2)}", f"SCD1 (перезапись): {', '.join(t1)}", ""]
    for k, v in init.items():
        lines.append(f"было: {k} | " + "; ".join(f"{a}={v[a]}" for a in attrs))
    lines.append("")
    for k, a, val in batch:
        lines.append(f"пакет: {k} | {a} | {val}")
    block = "\n".join(lines)
    stem = ("Хранилище данных: измерение «клиент». По атрибутам SCD2 изменение создаёт новую версию строки (старая "
            "закрывается), по атрибутам SCD1 — перезаписывает текущую версию без новой строки. Новый ключ клиента — "
            "первая версия строки; запись пакета с тем же значением, что уже в текущей версии, ничего не меняет. "
            "Сначала в измерении по одной строке на клиента («было»), затем записи пакета применяются по порядку. "
            "Сколько строк (всех версий) будет в измерении? Ответ — целое число.")
    expl = (f"Начинаем с {nk} строк; по порядку: новый ключ +1, изменение атрибута SCD2 +1, повтор значения и SCD1 — 0. "
            f"Итого {good}. «Каждая запись пакета — строка» дало бы {all_rows}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx="клиент",
                         accept=num_accept(good, ("строк", "строки")), params={"t2": t2, "t1": t1, "batch": batch})
