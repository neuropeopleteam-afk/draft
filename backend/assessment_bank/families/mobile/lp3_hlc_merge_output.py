"""mobile.sync.lp3_hlc_merge_output — predict_output: итог синхронизации офлайн-правок по гибридным часам.

Офлайн-первое приложение: устройства правят одно поле без связи, потом присылают правки на сервер в произвольном
порядке. Правило слияния — «побеждает правка с наибольшей гибридной меткой» (HLC: сначала физическое время в мс,
при равенстве — логический счётчик, при равенстве — идентификатор устройства по алфавиту). Удаление — тоже правка
(надгробие). Ловушки: последняя пришедшая на сервер правка; сравнение только по физическому времени (при равенстве
— первая в списке); надгробие проигнорировано. Ответ — итоговое значение поля или слово «удалено».
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.sync.lp3_hlc_merge_output"
CTX = [("список покупок", "название списка", ["Дача", "Продукты", "Ремонт", "Праздник", "Поход", "Аптека", "Школа"]),
       ("заметки", "заголовок заметки", ["Идеи", "Встреча", "Отпуск", "Книги", "Планы", "Рецепты", "Счета"]),
       ("CRM для курьеров", "статус точки", ["Ожидает", "Принят", "Отложен", "Доставлен", "Возврат", "Перенос"]),
       ("приложение для склада", "ячейка хранения", ["A1", "B4", "C2", "D7", "E3", "F5", "G8"])]
DEVICES = ["android-anna", "ios-boris", "android-vera", "tablet-gleb", "ios-dina"]

CALC = r'''
rows = []
for l in DATA.splitlines():
    if l.count("|") == 4 and not l.startswith("пришла"):
        n, dev, wall, cnt, val = [x.strip() for x in l.split("|")]
        rows.append(((int(wall), int(cnt), dev), val))
best = max(rows, key=lambda r: r[0])
print("удалено" if best[1] == "(удалить)" else best[1])
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    app, field, vals = rng.choice(CTX)
    for _ in range(3000):
        n = rng.randint(5, 7)
        devs = rng.sample(DEVICES, rng.randint(2, 4))
        base = 1_760_000_000_000 + rng.randint(0, 10_000_000)
        rows = []
        for i in range(n):
            wall = base + rng.choice([0, 0, 120, 120, 450, 900, 1500, 3000])
            cnt = rng.randint(0, 3)
            val = "(удалить)" if rng.random() < 0.15 else rng.choice(vals)
            rows.append([rng.choice(devs), wall, cnt, val])
        keys = [(w, c, d) for d, w, c, _ in rows]
        if len({k[:2] for k in keys}) != len(keys):
            continue  # пара (время, счётчик) уникальна — правило по имени устройства не понадобится
        best = max(range(n), key=lambda i: keys[i])
        good = "удалено" if rows[best][3] == "(удалить)" else rows[best][3]
        last = rows[-1][3]
        mw = max(k[0] for k in keys)
        by_wall = next(r[3] for r in rows if r[1] == mw)
        tie = sum(1 for k in keys if k[0] == mw) > 1
        if last == rows[best][3] or not tie or by_wall == rows[best][3]:
            continue  # ловушки «последняя пришедшая» и «только физическое время» дают другой ответ
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = ["пришла на сервер | устройство | физическое время, мс | счётчик | значение"]
    for i, (d, w, c, v) in enumerate(rows, 1):
        lines.append(f"{i} | {d} | {w} | {c} | {v}")
    block = "\n".join(lines)
    stem = (f"Приложение «{app}» работает офлайн. Поле «{field}» правили на нескольких устройствах без связи; правки "
            "пришли на сервер в порядке, указанном в первой колонке. Правило слияния: побеждает правка с наибольшей "
            "гибридной меткой (физическое время, затем счётчик, затем имя устройства по алфавиту); «(удалить)» — "
            "удаление значения, оно тоже правка. Какое значение поля будет на всех устройствах после синхронизации? "
            "Ответ — значение поля (как в таблице) или слово «удалено».")
    expl = (f"Сравниваем метки (физическое время, счётчик, устройство): максимум у правки №{best + 1} — "
            f"{rows[best][1]}/{rows[best][2]}/{rows[best][0]} → «{good}». Последняя пришедшая на сервер (№{n}) — "
            f"«{last}»; по одному физическому времени (первая из равных) — «{by_wall}». Порядок прихода не важен: "
            "так все устройства сходятся к одному значению независимо от сети.")
    acc = [good.lower(), good.upper(), f"«{good}»"]
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=good, expl=expl, ctx=app,
                         accept=acc, params={"rows": rows, "best": best})
