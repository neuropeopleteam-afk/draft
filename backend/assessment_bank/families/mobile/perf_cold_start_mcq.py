"""mobile.perf.cold_start_mcq — mcq_concept: какое изменение сильнее всего сократит холодный старт.

Таблица задач инициализации приложения при холодном старте: поток (главный / фоновый), длительность и нужна ли
задача первому экрану. Модель: задачи главного потока выполняются по очереди; фоновые стартуют одновременно в
момент запуска, каждая в своём потоке; первый экран ждёт конца главного потока и всех нужных ему фоновых задач,
затем рисуется (время отрисовки задано); «ленивая» задача выполняется при первом обращении — если она нужна
первому экрану, то на главном потоке во время его отрисовки. Варианты — одно изменение каждый: перенести задачу
в фон, сделать ленивой, ускорить вдвое. Ловушки уровня Senior: перенос в фон задачи, которую первый экран всё
равно ждёт (выигрыш — только перекрытие), «ленивая» инициализация нужной первому экрану задачи (выигрыша нет),
ускорение задачи вне критического пути. Верный вариант единственный, отрыв от второго не меньше 15 % выигрыша.
Ключ проверяется исполнением: Python разбирает показанную таблицу и считает время до первого кадра для каждого
изменения.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, text_table
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options, py_literal_block

FAMILY_ID = "mobile.perf.cold_start_mcq"

APPS = ["мобильный банк", "маркетплейс", "приложение такси", "онлайн-кинотеатр", "приложение доставки еды",
        "приложение авиакомпании", "фитнес-трекер", "мессенджер для бизнеса"]

# (задача, нужна ли первому экрану по смыслу)
TASKS = [("Отчёты о падениях (SDK)", False), ("Граф зависимостей (DI)", True), ("Аналитика (SDK)", False),
         ("Флаги функций с диска", True), ("Открытие базы и миграции", True), ("Рекламный SDK", False),
         ("Загрузчик изображений", True), ("Чат поддержки (SDK)", False), ("Шрифты и тема", True),
         ("Проверка root/jailbreak", False), ("Кэш каталога с диска", True), ("Карты (SDK)", False)]

CALC = r'''
rows = []
for l in TABLE.strip().splitlines()[2:]:
    c = [x.strip() for x in l.split("|")]
    rows.append(dict(name=c[0], thread=c[1], dur=int(c[2]), need=(c[3] == "да"), lazy=False))

def ttff(rs):
    main_end = sum(r["dur"] for r in rs if r["thread"] == "главный" and not r["lazy"])
    bg_wait = max([r["dur"] for r in rs if r["thread"] == "фоновый" and r["need"] and not r["lazy"]] + [0])
    lazy_on_render = sum(r["dur"] for r in rs if r["lazy"] and r["need"])
    return max(main_end, bg_wait) + RENDER + lazy_on_render

def apply(rs, ch):
    kind, name = ch
    out = []
    for r in rs:
        r = dict(r)
        if r["name"] == name:
            if kind == "to_bg":
                r["thread"] = "фоновый"
            elif kind == "lazy":
                r["lazy"] = True
            else:
                r["dur"] = r["dur"] // 2
        out.append(r)
    return out

t = {k: ttff(apply(rows, ch)) for k, ch in CHANGES.items()}
best = min(t.values())
hits = [k for k, v in t.items() if v == best]
print(hits[0] if len(hits) == 1 else "AMBIGUOUS")
'''


def _ttff(rows, render):
    main_end = sum(r["dur"] for r in rows if r["thread"] == "главный" and not r["lazy"])
    bg_wait = max([r["dur"] for r in rows if r["thread"] == "фоновый" and r["need"] and not r["lazy"]] + [0])
    return max(main_end, bg_wait) + render + sum(r["dur"] for r in rows if r["lazy"] and r["need"])


def _apply(rows, ch):
    kind, name = ch
    out = []
    for r in rows:
        r = dict(r)
        if r["name"] == name:
            if kind == "to_bg":
                r["thread"] = "фоновый"
            elif kind == "lazy":
                r["lazy"] = True
            else:
                r["dur"] = r["dur"] // 2
        out.append(r)
    return out


def _text(ch):
    kind, name = ch
    return {"to_bg": f"Перенести «{name}» в фоновый поток",
            "lazy": f"Сделать «{name}» ленивой — инициализировать при первом обращении",
            "half": f"Ускорить «{name}» вдвое (кэш результата)"}[kind]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    app = rng.choice(APPS)
    render = rng.choice([60, 80, 100, 120])
    for _ in range(4000):
        picked = rng.sample(TASKS, rng.randint(6, 7))
        rows = []
        for name, need in picked:
            thread = "фоновый" if rng.random() < 0.3 else "главный"
            rows.append(dict(name=name, thread=thread, dur=rng.choice([30, 40, 60, 80, 120, 150, 200, 250, 300, 400]),
                             need=need, lazy=False))
        main = [r for r in rows if r["thread"] == "главный"]
        if len(main) < 4:
            continue
        base = _ttff(rows, render)
        cands = []
        for r in main:
            cands.append(("to_bg", r["name"]))
            cands.append(("lazy", r["name"]))
        for r in rows:
            cands.append(("half", r["name"]))
        gain = {c: base - _ttff(_apply(rows, c), render) for c in cands}
        # ловушки: перенос в фон или «ленивая» задача, нужная первому экрану, длиннее верного выигрыша
        traps = [c for c in cands if c[0] in ("to_bg", "lazy") and next(r for r in rows if r["name"] == c[1])["need"]
                 and next(r for r in rows if r["name"] == c[1])["dur"] >= 120]
        if not traps:
            continue
        trap = rng.choice(traps)
        others = [c for c in cands if c != trap and c[1] != trap[1]]
        rng.shuffle(others)
        chosen = [trap]
        for c in others:
            if all(c[1] != x[1] for x in chosen):
                chosen.append(c)
            if len(chosen) == 4:
                break
        if len(chosen) < 4:
            continue
        g = sorted((gain[c] for c in chosen), reverse=True)
        if g[0] <= 0 or g[0] - g[1] < max(20, g[0] * 0.15):
            continue
        best = max(chosen, key=lambda c: gain[c])
        if best == trap:
            continue
        name_of_trap = next(r for r in rows if r["name"] == trap[1])
        if gain[trap] >= name_of_trap["dur"]:
            continue  # ловушка должна давать меньше «наивного» выигрыша
        break
    else:
        raise RuntimeError("нет набора задач")
    headers = ["Задача", "Поток", "Длительность, мс", "Нужна первому экрану"]
    trows = [[r["name"], r["thread"], str(r["dur"]), "да" if r["need"] else "нет"] for r in rows]
    table = text_table(headers, trows)
    dist = [c for c in chosen if c != best]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (_text(best), None), [(_text(c), None) for c in dist])
    by_text = {_text(c): c for c in chosen}
    changes = {o.id: by_text[o.text] for o in opts}
    prog = py_literal_block("TABLE", table) + f"RENDER = {render}\nCHANGES = {changes!r}\n" + CALC
    checks = [Check(name="cold_start_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=key)]
    stem = (f"Приложение «{app}»: при холодном старте выполняются задачи из таблицы. Задачи главного потока идут "
            f"по очереди; фоновые стартуют одновременно в момент запуска, каждая в своём потоке. Первый экран "
            f"ждёт конца главного потока и всех нужных ему фоновых задач, затем рисуется {render} мс. Ленивая "
            f"задача выполняется при первом обращении: если она нужна первому экрану — на главном потоке во время "
            f"его отрисовки. Сейчас до первого кадра {base} мс. Какое одно изменение сильнее всего сократит это "
            f"время?")
    expl = ("Время до первого кадра = max(сумма задач главного потока, самая долгая нужная экрану фоновая) + "
            f"отрисовка + ленивые нужные задачи. Сейчас {base} мс. " +
            "; ".join(f"«{_text(c)}» → {base - gain[c]} мс" for c in chosen) +
            f". Ловушка: «{_text(trap)}» — задача нужна первому экрану: " +
            ("экран всё равно ждёт её конца в фоне." if trap[0] == "to_bg" else
             "она всё равно выполнится на главном потоке во время отрисовки."))
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak, context=app,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется моделью на Python, разбирающей показанную таблицу.",
                         params={"render": render, "best": list(best), "trap": list(trap),
                                 "rows": [[r["name"], r["thread"], r["dur"], r["need"]] for r in rows]})
