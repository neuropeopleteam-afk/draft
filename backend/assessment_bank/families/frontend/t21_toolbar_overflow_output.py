"""frontend.layout.t21_toolbar_overflow_output — predict_output (набор t21, порог Junior): цикл с continue
и break — какие кнопки помещаются в панель инструментов.

Панель имеет ширину; кнопки идут по порядку, скрытые пропускаются (`continue`), а как только очередная кнопка не
помещается — цикл прерывается (`break`), и все оставшиеся уходят в меню «ещё». Программа печатает видимые кнопки
и занятую ширину. Ловушки: после break следующие (даже узкие) кнопки не проверяются; скрытые кнопки не
занимают место; при точном совпадении (used + w === width) кнопка ещё помещается. Ключ —
независимая модель в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.layout.t21_toolbar_overflow_output"

CTX = [("панель редактора", ["bold", "italic", "link", "image", "table", "code", "quote", "undo"]),
       ("шапка почтового клиента", ["reply", "forward", "archive", "spam", "move", "label", "print", "pin"]),
       ("панель таблицы", ["filter", "sort", "group", "export", "share", "chart", "freeze", "copy"]),
       ("плеер", ["play", "next", "shuffle", "repeat", "queue", "lyrics", "cast", "eq"])]
WIDTHS = [40, 48, 56, 64, 72, 80, 96]


def _model(buttons, width):
    used, visible, i = 0, [], 0
    stop = None
    for idx, (name, w, hidden) in enumerate(buttons):
        if hidden:
            continue
        if used + w > width:
            stop = idx
            break
        used += w
        visible.append(name)
    rest = 0 if stop is None else sum(1 for (_n, _w, h) in buttons[stop:] if not h)
    return visible, used, stop, rest


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    for _ in range(500):
        n = rng.randint(5, 7)
        names = rng.sample(pool, n)
        ws = [rng.choice(WIDTHS) for _ in range(n)]
        hid = [False] * n
        for j in rng.sample(range(n), rng.randint(1, 2)):
            hid[j] = True
        buttons = list(zip(names, ws, hid))
        width = rng.choice(range(160, 321, 8))
        visible, used, stop, rest = _model(buttons, width)
        if stop is None or not visible or rest < 2:
            continue
        # после break есть кнопка, которая поместилась бы по ширине, — ловушка «break, а не continue»
        free = width - used
        if not any((not h) and w <= free for (_n, w, h) in buttons[stop + 1:]):
            continue
        # хотя бы одна скрытая кнопка стоит до точки обрыва — ловушка «continue»
        if not any(h for (_n, _w, h) in buttons[:stop]):
            continue
        break
    else:
        raise RuntimeError("t21_toolbar_overflow: не собрана панель")
    lit = ", ".join(f"{{ id: \"{nm}\", w: {w}{', hidden: true' if h else ''} }}" for nm, w, h in buttons)
    code = "\n".join([
        f"const buttons = [{lit}];",
        "let used = 0;",
        "const visible = [];",
        "for (const b of buttons) {",
        "  if (b.hidden) continue;",
        f"  if (used + b.w > {width}) break;",
        "  used += b.w;",
        "  visible.push(b.id);",
        "}",
        "console.log(visible.join(\" \"), used);",
    ])
    out = f"{' '.join(visible)} {used}"
    hidden_names = [nm for nm, _w, h in buttons[:stop] if h]
    stop_name, stop_w, _ = buttons[stop]
    expl = (f"Скрытые кнопки до места обрыва ({', '.join(hidden_names)}) пропускаются через continue и не "
            f"занимают место. "
            f"Помещаются: {', '.join(visible)} — used = {used}. Кнопка {stop_name} (w = {stop_w}) даёт "
            f"{used} + {stop_w} = {used + stop_w} > {width}, срабатывает break: цикл заканчивается, и следующие "
            f"кнопки не проверяются, даже если какая-то из них поместилась бы в оставшиеся {width - used}. "
            f"Вывод — видимые кнопки и used: «{out}».")
    stem = (f"Интерфейс ({ctx}): программа решает, какие кнопки помещаются в панель инструментов; "
            f"остальные уходят в меню «ещё».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"buttons": [list(b) for b in buttons], "width": width}, language="javascript")
