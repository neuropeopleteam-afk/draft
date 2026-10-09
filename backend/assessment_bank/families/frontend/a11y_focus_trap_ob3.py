"""frontend.a11y.focus_trap_ob3 — открытая книга: удержание фокуса в модальном окне.

Модель страницы: элементы в порядке DOM (снаружи окна, контейнер окна с tabindex=-1,
элементы окна, снова снаружи). Обработчик keydown окна вызывает nextFocus; если она
вернула элемент — фокус переводится на него, иначе браузер переводит фокус по умолчанию к
следующему (Shift+Tab — к предыдущему) элементу из последовательности Tab. Шаги 1–2
проверяются исполнением этой модели в Node.js, генератор считает ключи своей моделью.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.a11y.focus_trap_ob3"

DIALOGS = [("подтверждение удаления", ["Закрыть", "Причина удаления", "Отмена", "Удалить"]),
           ("форма входа", ["Закрыть", "Email", "Пароль", "Войти"]),
           ("фильтры каталога", ["Сбросить", "Цена от", "Цена до", "Применить"]),
           ("выбор даты доставки", ["Назад", "Дата", "Интервал", "Сохранить"]),
           ("приглашение кандидата", ["Закрыть", "Вилка от", "Вилка до", "Отправить"])]
BEFORE = [["Логотип", "Поиск по сайту"], ["Меню", "Профиль"], ["Каталог", "Корзина"]]
AFTER = [["Контакты в подвале"], ["Чат поддержки"], ["Политика cookie"]]
CONTAINER = "контейнер окна"
OUTSIDE = "адресная строка"

KIND_LINES = {
    "good": ["  const last = items.length - 1;", "  if (event.shiftKey && i <= 0) return items[last];",
             "  if (!event.shiftKey && (i < 0 || i === last)) return items[0];"],
    "strict_first": ["  const last = items.length - 1;", "  if (event.shiftKey && i === 0) return items[last];",
                     "  if (!event.shiftKey && i === last) return items[0];"],
    "off_by_one": ["  const last = items.length;", "  if (event.shiftKey && i <= 0) return items[last];",
                   "  if (!event.shiftKey && (i === -1 || i === last)) return items[0];"],
    "minus_one_null": ["  const last = items.length - 1;", "  if (i === -1) return null;",
                       "  if (event.shiftKey) return i === 0 ? items[last] : null;",
                       "  return i === last ? items[0] : null;"],
    "no_shift_guard": ["  const last = items.length - 1;", "  if (event.shiftKey && i <= 0) return items[last];",
                       "  if (i === -1 || i === last) return items[0];"],
    "always_next": ["  if (items.length === 0) return null;", "  const last = items.length - 1;",
                    "  const next = i >= last ? 0 : i + 1;", "  return items[next];"],
    "stuck_first": ["  const last = items.length - 1;", "  if (event.shiftKey && i <= 0) return items[0];",
                    "  if (!event.shiftKey && (i === -1 || i === last)) return items[0];"],
}


def _code(kind: str) -> str:
    return "\n".join(["function nextFocus(event, items, current) {",
                      "  if (event.key !== 'Tab') return null;",
                      "  const i = items.indexOf(current);"] + KIND_LINES[kind] +
                     (["  return null;"] if kind not in ("always_next", "minus_one_null") else [])
                     + ["}"])


def _next(kind, shift, items, cur):
    i = items.index(cur) if cur in items else -1
    n = len(items)
    last = n if kind == "off_by_one" else n - 1
    get = lambda j: items[j] if 0 <= j < n else None  # noqa: E731
    if kind == "always_next":
        return items[(i + 1) % n]
    if kind == "minus_one_null" and i == -1:
        return None
    if kind in ("strict_first", "minus_one_null"):
        if shift and i == 0:
            return get(last)
        if not shift and i == last:
            return get(0)
        return None
    if shift and i <= 0:
        return get(0) if kind == "stuck_first" else get(last)
    if kind == "no_shift_guard":
        return get(0) if i in (-1, last) else None
    if not shift and i in (-1, last):
        return get(0)
    return None


def _press(kind, dom, items, cur, shift):
    t = _next(kind, shift, items, cur)
    if t:
        return t
    pos = [d[0] for d in dom].index(cur)
    rng_ = range(pos - 1, -1, -1) if shift else range(pos + 1, len(dom))
    for k in rng_:
        if dom[k][2]:
            return dom[k][0]
    return OUTSIDE


def _run(kind, dom, items, start, keys):
    inside = {d[0] for d in dom if d[1]}
    cur = start
    for sh in keys:
        cur = _press(kind, dom, items, cur, sh)
        if cur not in inside:
            return "escaped"
    return "inside"


def _trace(kind, dom, items):
    starts = [CONTAINER] + items
    return " | ".join(f"{s}:{'S' if sh else 'T'}→{_press(kind, dom, items, s, sh)}"
                      for s in starts for sh in (False, True))


JS_MODEL = """function press(dom, items, current, shift) {
  const t = nextFocus({ key: 'Tab', shiftKey: shift }, items, current);
  if (t) return t;
  const pos = dom.findIndex((d) => d[0] === current);
  if (!shift) { for (let k = pos + 1; k < dom.length; k++) if (dom[k][2]) return dom[k][0]; }
  else { for (let k = pos - 1; k >= 0; k--) if (dom[k][2]) return dom[k][0]; }
  return OUTSIDE;
}"""


def _program(code, dom, items, mode, start=None, keys=None):
    head = (code + "\n\nconst OUTSIDE = " + json.dumps(OUTSIDE, ensure_ascii=False) + ";\n" +
            JS_MODEL + "\nconst dom = " + json.dumps(dom, ensure_ascii=False) + ";\n" +
            "const items = " + json.dumps(items, ensure_ascii=False) + ";\n" +
            "const inside = new Set(dom.filter((d) => d[1]).map((d) => d[0]));\n")
    if mode == "run":
        return head + (f"let cur = {json.dumps(start, ensure_ascii=False)};\nlet res = 'inside';\n"
                       f"for (const sh of {json.dumps(keys)}) {{\n"
                       "  cur = press(dom, items, cur, sh);\n"
                       "  if (!inside.has(cur)) { res = 'escaped'; break; }\n}\nconsole.log(res);\n")
    return head + ("const out = [];\nfor (const s of " +
                   json.dumps([CONTAINER] + items, ensure_ascii=False) + ") {\n"
                   "  for (const sh of [false, true]) out.push(s + ':' + (sh ? 'S' : 'T') + '→' + "
                   "press(dom, items, s, sh));\n}\nconsole.log(out.join(' | '));\n")


CONDITIONS = {
    "restore": dict(
        text=("Окно закрывается по Escape и кнопкам. После закрытия пользователь клавиатуры "
              "оказывается в начале страницы, а экранный диктор молчит. Как правильно "
              "управлять фокусом при открытии и закрытии окна?"),
        criteria=[("open", "При открытии переводит фокус внутрь окна: на заголовок/контейнер "
                           "с tabindex=-1 или первый осмысленный элемент; запоминает элемент, "
                           "с которого открыли", 0.35),
                  ("close", "При закрытии (Escape, кнопки, клик по фону) возвращает фокус на "
                            "запомнивший элемент; если его нет — на разумный ориентир", 0.4),
                  ("announce", "Окно размечено role=dialog, aria-modal=true, aria-labelledby "
                               "на заголовок — диктор объявляет окно", 0.25)],
        strong="""При открытии запоминаю document.activeElement (кнопку, открывшую окно) и
            перевожу фокус внутрь: на заголовок или контейнер с tabindex=-1, если в окне
            длинный текст, или на первое поле формы. Окно размечаю role="dialog",
            aria-modal="true" и aria-labelledby на заголовок, чтобы диктор объявил его
            название. Escape закрывает окно так же, как кнопки «Закрыть»/«Отмена». При любом
            закрытии возвращаю фокус на запомненный элемент; если его уже нет в DOM
            (например, удалили строку таблицы), — на ближайший логичный ориентир: заголовок
            списка или следующую строку. Проверяю клавиатурой и NVDA/VoiceOver: после
            закрытия диктор произносит кнопку, с которой начинали.""",
        medium="""При закрытии окна нужно возвращать фокус на кнопку, которая его открыла, а
            при открытии переводить фокус внутрь окна. Escape должен закрывать окно.""",
        weak="""Нужно после закрытия вызвать window.scrollTo(0, 0), чтобы пользователь видел
            страницу."""),
    "inert": dict(
        text=("Клавиатурой фокус из окна больше не выходит, но пользователь экранного диктора "
              "стрелками виртуального курсора читает и активирует ссылки страницы под окном. "
              "Почему ловушка Tab этого не решает и что сделать?"),
        criteria=[("why", "Объясняет, что виртуальный курсор диктора не использует Tab и "
                          "читает всё дерево доступности", 0.3),
                  ("fix", "Делает фон недоступным: inert на остальном содержимом или "
                          "нативный <dialog> с showModal(); aria-modal=true как подсказка", 0.45),
                  ("caveats", "Учитывает поддержку браузеров и дикторов, снятие inert при "
                              "закрытии, вложенные окна и порталы", 0.25)],
        strong="""Ловушка Tab управляет только фокусом клавиатуры, а диктор в режиме чтения
            ходит по дереву доступности стрелками и видит всё, что не скрыто. Нужно сделать
            фон недоступным: проще всего нативный <dialog> и dialog.showModal() — браузер сам
            делает остальное содержимое инертным, обрабатывает Escape и возвращает фокус.
            Если окно своё, ставлю атрибут inert на соседние с порталом корневые элементы
            (или aria-hidden="true", если нужна поддержка старых браузеров) и снимаю его при
            закрытии. aria-modal="true" полезен, но некоторые дикторы его игнорируют, поэтому
            одного его недостаточно. Для вложенных окон inert снимаю только с верхнего.
            Проверяю на NVDA + Firefox и VoiceOver + Safari.""",
        medium="""Диктор читает страницу не через Tab, поэтому нужно скрыть фон: атрибутом inert
            или aria-hidden на остальном содержимом, либо использовать <dialog> с
            showModal().""",
        weak="""Нужно поставить tabindex="-1" всем ссылкам на странице."""),
    "dynamic": dict(
        text=("Содержимое окна меняется: кнопка «Отправить» блокируется (disabled) до "
              "заполнения формы, а после ошибки сервера появляется ссылка «Повторить». Список "
              "items вычисляется один раз при открытии. Какие ошибки возможны и как их "
              "исправить?"),
        criteria=[("stale", "Понимает, что список, вычисленный при открытии, устаревает: "
                            "фокус попадает на disabled-элемент или выходит мимо новой ссылки", 0.4),
                  ("query", "Вычисляет фокусируемые элементы на каждом keydown: селектор "
                            "по tabbable-элементам, фильтр disabled, hidden, tabindex=-1, "
                            "невидимых", 0.35),
                  ("details", "Учитывает tabindex>0, элементы в shadow DOM/iframe, готовые "
                              "решения (focus-trap, <dialog>)", 0.25)],
        strong="""Список, собранный при открытии, устаревает. Если последний элемент списка —
            заблокированная «Отправить», браузер её пропускает, и Tab с предпоследнего
            элемента уходит за окно; новая ссылка «Повторить» вообще не попадёт в цикл. Поэтому
            вычисляю элементы на каждом keydown: querySelectorAll по a[href], button, input,
            select, textarea, [tabindex] и фильтрую disabled, tabindex="-1", hidden, невидимые
            (нулевой размер или visibility: hidden). Порядок — как у браузера: элементы с
            tabindex>0 идут первыми, поэтому такие значения в окне запрещаю. Для сложных
            случаев (shadow DOM, iframe) беру проверенную библиотеку focus-trap или
            нативный <dialog>. Тест: заблокировать последнюю кнопку и нажать Tab.""",
        medium="""Нужно пересчитывать список фокусируемых элементов при каждом нажатии Tab и
            исключать disabled и скрытые элементы.""",
        weak="""Нужно убрать атрибут disabled с кнопки, тогда всё будет работать."""),
    "testing": dict(
        text=("Ловушку фокуса уже дважды ломали при рефакторинге. Как вы покроете её "
              "автоматическими тестами и что проверите вручную?"),
        criteria=[("unit", "Модульные/компонентные тесты с имитацией клавиатуры: Tab и "
                           "Shift+Tab на краях, старт с контейнера, Escape и возврат фокуса", 0.4),
                  ("e2e", "Сквозные тесты в реальном браузере (Playwright keyboard) и "
                          "автоматическая проверка доступности (axe)", 0.3),
                  ("manual", "Ручная проверка с экранными дикторами и только клавиатурой; "
                             "критерии WCAG 2.1.2 и 2.4.3", 0.3)],
        strong="""Компонентные тесты на Testing Library с user-event: открыть окно, проверить,
            что фокус внутри; userEvent.tab() с последнего элемента → первый; tab({ shift:
            true }) с первого и с контейнера → последний; Escape закрывает и возвращает фокус
            на кнопку-триггер; заблокированная кнопка пропускается. Так как jsdom не делает
            настоящую навигацию по Tab, дублирую ключевые сценарии в Playwright
            (page.keyboard.press('Tab')) в Chromium и WebKit и прогоняю axe-core на открытом
            окне. Вручную — только клавиатура и NVDA/VoiceOver: объявляется ли заголовок,
            нельзя ли уйти виртуальным курсором на фон. Ориентиры — WCAG 2.1.2 (нет ловушки
            без выхода: Escape работает) и 2.4.3 (логичный порядок фокуса).""",
        medium="""Написать тесты, которые нажимают Tab и Shift+Tab на первом и последнем
            элементе и проверяют, что фокус остаётся в окне, а после Escape возвращается на
            кнопку.""",
        weak="""Достаточно один раз проверить окно вручную мышкой."""),
}


def _key_text(start, keys, items):
    k = ", ".join("Shift+Tab" if s else "Tab" for s in keys)
    where = ("на контейнере окна" if start == CONTAINER else f"на «{start}»")
    return f"Фокус {where}, нажать: {k}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    title, labels = rng.choice(DIALOGS)
    n = rng.choice([3, 4])
    items = labels if n == 4 else [labels[0]] + labels[2:]
    before, after = rng.choice(BEFORE), rng.choice(AFTER)
    dom = ([[b, False, True] for b in before] + [[CONTAINER, True, False]] +
           [[x, True, True] for x in items] + [[a, False, True] for a in after])
    kind = rng.choice(["strict_first", "off_by_one"])
    starts = [CONTAINER] + items
    seqs = [[a] for a in (False, True)] + [[a, b] for a in (False, True) for b in (False, True)] + \
        [[a, b, c] for a in (False, True) for b in (False, True) for c in (False, True)]
    esc, safe = [], []
    for s in starts:
        for ks in seqs:
            assert _run("good", dom, items, s, ks) == "inside"
            (esc if _run(kind, dom, items, s, ks) == "escaped" else safe).append((s, ks))
    # ключ — короткий воспроизводящий сценарий; дистракторы — безопасные, в том числе у краёв
    esc.sort(key=lambda x: len(x[1]))
    short = [e for e in esc if len(e[1]) <= 2]
    key_sc = rng.choice(short or esc)
    edge = [x for x in safe if x[0] in (items[0], items[-1], CONTAINER)]
    rng.shuffle(edge)
    rest = [x for x in safe if x not in edge]
    rng.shuffle(rest)
    picked = []
    for x in edge[:2] + rest:
        if len(picked) == 3:
            break
        if _key_text(*x, items) not in [_key_text(*p, items) for p in picked]:
            picked.append(x)
    opts1, key1 = make_options(rng, (_key_text(*key_sc, items), None),
                               [(_key_text(*p, items), None) for p in picked], step=1)
    by_text = {_key_text(*sc, items): sc for sc in [key_sc] + picked}
    pool = [k for k in KIND_LINES if k not in ("good", kind)]
    good_trace = _trace("good", dom, items)
    pool = [k for k in pool if _trace(k, dom, items) != good_trace]
    dk = rng.sample(pool, 3)
    opts2, key2 = make_options(rng, ("Заменить функцию на:", _code("good")),
                               [("Заменить функцию на:", _code(k)) for k in dk], step=2)
    code = _code(kind)
    checks = []
    for o in opts1:
        s, ks = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="node",
                            program=_program(code, dom, items, "run", s, ks),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout="inside"))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="node", embeds_display_code=False,
                            program=_program(o.code, dom, items, "trace"),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=good_trace))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    order = (" → ".join(before) + " → [окно: " + " → ".join([f"{CONTAINER} (tabindex=-1)"] + items)
             + "] → " + " → ".join(after))
    stem = (f"Модальное окно «{title}». Порядок элементов в DOM: {order}. При открытии фокус "
            f"переводится на {CONTAINER} (tabindex=-1, в последовательность Tab не входит). "
            f"Обработчик keydown окна вызывает `nextFocus(event, items, document.activeElement)`, "
            f"где items — элементы окна по порядку: если функция вернула элемент, фокус "
            f"переводится на него (preventDefault), если null — браузер переводит фокус как "
            f"обычно к следующему (Shift+Tab — к предыдущему) элементу последовательности Tab "
            f"на странице. Требование: фокус клавиатуры не покидает окно, порядок обхода "
            f"циклический.")
    steps = ob3_steps(
        "Шаг 1. В каком сценарии фокус выйдет за пределы окна?",
        "Шаг 2. Выберите исправление nextFocus.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"strict_first": "i === 0 не ловит фокус на контейнере (i = -1): Shift+Tab уходит из окна",
           "off_by_one": "last = items.length: индекс последнего элемента никогда не совпадает, "
                         "Tab с последнего уходит из окна",
           "minus_one_null": "при фокусе на контейнере возвращается null — Shift+Tab уходит из окна",
           "no_shift_guard": "без проверки shiftKey Shift+Tab с последнего прыгает на первый",
           "always_next": "Shift+Tab тоже двигает фокус вперёд",
           "stuck_first": "Shift+Tab с первого элемента оставляет фокус на месте"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Дефект: {why[kind]}. Верное исправление обрабатывает оба края и "
                               f"контейнер (i = -1). Дистракторы шага 2: "
                               + "; ".join(why[k] for k in dk) + ".")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=title, verification="execution",
                         checks=checks, steps=steps, defect_type="focus_trap_edge",
                         display_code_note="Шаг 2 проверяется на модели страницы: все стартовые "
                                           "позиции × Tab/Shift+Tab сравниваются с эталоном.",
                         params={"subtype": kind, "distractors": dk, "condition": cond_name,
                                 "n_items": n})
