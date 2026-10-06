"""frontend.js.debounce_ob3 — открытая книга: debounce для поиска с подсказками."""
from __future__ import annotations

import json

from assessment_bank.families.frontend._fake_timers import FAKE_TIMERS
from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.debounce_ob3"


def _code(kind: str) -> str:
    inner = {
        "good": ["    lastArgs = args;", "    clearTimeout(timer);"],
        "no_clear": ["    lastArgs = args;"],
        "first_args": ["    if (timer === null) lastArgs = args;", "    clearTimeout(timer);"],
        "clear_in_callback": ["    lastArgs = args;"],
        "leading": ["    if (timer === null) fn(...args);", "    clearTimeout(timer);"],
    }[kind]
    cb = {"clear_in_callback": ["      clearTimeout(timer);", "      timer = null;", "      fn(...lastArgs);"],
          "leading": ["      timer = null;"]}.get(kind, ["      timer = null;", "      fn(...lastArgs);"])
    lines = ["function debounce(fn, delay) {", "  let timer = null;", "  let lastArgs = null;",
             "  return (...args) => {"] + inner + ["    timer = setTimeout(() => {"] + cb + \
            ["    }, delay);", "  };", "}"]
    return "\n".join(lines)


def _sim(kind: str, delay: int, calls: list[tuple[int, str]]) -> str:
    timers: list[list] = []
    st = {"timer": None, "last": None, "seq": 0}
    fired: list[str] = []

    def schedule(at, cb):
        st["seq"] += 1
        timers.append([at, st["seq"], cb])
        return st["seq"]

    def clear(tid):
        timers[:] = [t for t in timers if t[1] != tid]

    def run_until(t):
        while True:
            timers.sort(key=lambda x: (x[0], x[1]))
            if not timers or timers[0][0] > t:
                return
            at, _, cb = timers.pop(0)
            cb(at)

    def cb(now):
        if kind == "clear_in_callback":
            clear(st["timer"])
        st["timer"] = None
        if kind != "leading":
            fired.append(f"{now}:{st['last']}")

    for t, q in calls:
        run_until(t)
        if kind == "first_args":
            if st["timer"] is None:
                st["last"] = q
        elif kind == "leading":
            if st["timer"] is None:
                fired.append(f"{t}:{q}")
        else:
            st["last"] = q
        if kind not in ("no_clear", "clear_in_callback"):
            clear(st["timer"])
        st["timer"] = schedule(t + delay, cb)
    run_until(10 ** 9)
    return " ".join(fired) or "(пусто)"


def _program(code: str, delay: int, calls) -> str:
    return (FAKE_TIMERS + "\n\n" + code + "\n\n;(async () => {\n  const fired = [];\n"
            f"  const run = debounce((q) => fired.push(__clock.now + ':' + q), {delay});\n"
            f"  for (const [t, q] of {json.dumps(calls, ensure_ascii=False)}) {{\n"
            "    await advanceTo(t);\n    run(q);\n  }\n  await advanceTo(1e9);\n"
            "  console.log(fired.join(' ') || '(пусто)');\n})();\n")


WORDS = ["ноутбук", "кофемашина", "наушники", "самокат", "палатка", "телевизор"]

CONDITIONS = {
    "react": dict(
        text=("Функцию перенесли в React-компонент: `const onChange = debounce((q) => "
              "setQuery(q), 300)` прямо в теле компонента. Подсказки стали приходить на каждый "
              "символ, а после закрытия модального окна в консоли появляется предупреждение об "
              "обновлении размонтированного компонента. Почему и как правильно?"),
        criteria=[("identity", "Объясняет, что debounce создаётся заново на каждом рендере — у "
                               "каждого экземпляра свой таймер, ничего не отменяется", 0.4),
                  ("fix", "Сохраняет экземпляр между рендерами: useMemo/useRef/useCallback с "
                          "правильными зависимостями; учитывает устаревшее замыкание", 0.35),
                  ("cleanup", "Отменяет отложенный вызов при размонтировании (cancel в cleanup "
                              "useEffect)", 0.25)],
        strong="""Тело компонента выполняется на каждом рендере, а setQuery вызывает рендер —
            значит, после каждого символа создаётся новый debounce со своим timer, и
            clearTimeout отменяет только таймер своего экземпляра; в итоге срабатывает каждый
            вызов. Экземпляр нужно сохранить между рендерами: const debounced = useMemo(() =>
            debounce((q) => setQuery(q), 300), []) или в useRef. Если колбэк зависит от
            пропсов, держу актуальную функцию в ref и вызываю ref.current внутри, чтобы не
            ловить устаревшее замыкание. Отложенный вызов после размонтирования убираю:
            добавляю в debounce метод cancel (clearTimeout(timer)) и вызываю его в cleanup
            useEffect(() => () => debounced.cancel(), [debounced]). Тест — React Testing
            Library с поддельными таймерами: ввод пяти символов даёт один setQuery.""",
        medium="""debounce создаётся при каждом рендере, поэтому таймеры не отменяют друг друга.
            Нужно обернуть его в useMemo или useRef, а при размонтировании отменять таймер.""",
        weak="""Нужно увеличить задержку до 1000 мс, тогда запросов будет меньше."""),
    "race": dict(
        text=("После исправления debounce запросы подсказок уходят реже, но иногда под полем "
              "остаются подсказки для предыдущего текста: сервер отвечает за 100–900 мс. Решает "
              "ли debounce эту проблему? Что нужно добавить?"),
        criteria=[("not_solved", "Понимает, что debounce уменьшает число запросов, но не "
                                 "гарантирует порядок ответов: медленный ранний ответ может "
                                 "прийти после быстрого позднего", 0.35),
                  ("fix", "Отбрасывает устаревшие ответы: счётчик/идентификатор запроса, "
                          "сравнение с текущим текстом или AbortController для отмены", 0.4),
                  ("details", "Учитывает ошибки и индикатор загрузки устаревших запросов, "
                              "AbortError не показывается пользователю", 0.25)],
        strong="""Нет. debounce лишь откладывает и сокращает запросы, но если пользователь
            сделал паузу дольше задержки, уйдут два запроса, и ответ на первый может прийти
            позже второго — на экране останутся старые подсказки. Нужно отбрасывать устаревшие
            ответы: перед запросом увеличиваю счётчик requestId и запоминаю его; после await
            рендерю, только если id совпадает с текущим. Лучше дополнительно отменять прошлый
            запрос через AbortController — это экономит сеть и сервер. Ошибка или AbortError
            устаревшего запроса не должна показываться и не должна снимать индикатор загрузки
            актуального. Проверяю тестом с поддельным API, где первый ответ медленнее второго.""",
        medium="""Нет, debounce не защищает от того, что старый ответ придёт позже нового. Нужно
            проверять, что ответ относится к последнему запросу, например по счётчику, или
            отменять прошлый запрос через AbortController.""",
        weak="""Да, если увеличить задержку debounce, ответы будут приходить по порядку."""),
    "ux": dict(
        text=("Продакт просит: при нажатии Enter искать сразу, не дожидаясь задержки; при "
              "непрерывном наборе подсказки должны появляться хотя бы раз в секунду; ввод "
              "через IME (китайский, японский) не должен отправлять промежуточные символы. Как "
              "изменить debounce и обработчики?"),
        criteria=[("flush", "Добавляет flush/cancel: Enter вызывает отложенную функцию "
                            "немедленно и отменяет таймер, без двойного запроса", 0.35),
                  ("max_wait", "Реализует maxWait: принудительный вызов не реже раза в N мс "
                               "при непрерывном наборе", 0.35),
                  ("ime", "Игнорирует ввод во время composition (compositionstart/end, "
                          "isComposing), запускает поиск по compositionend", 0.3)],
        strong="""Расширяю debounce до объекта с методами: flush() — если есть отложенный вызов,
            очищает таймер и сразу вызывает fn(...lastArgs); cancel() — просто очищает. Enter
            вызывает flush(), поэтому запрос уходит сразу и не дублируется по таймеру. Для
            подсказок при непрерывном наборе — параметр maxWait: запоминаю время первого
            отложенного вызова серии и, если с него прошло maxWait = 1000 мс, вызываю fn, не
            дожидаясь паузы (так устроен debounce в lodash). Для IME слушаю
            compositionstart/compositionend: пока event.isComposing истинно, не планирую
            вызов, а по compositionend планирую с итоговым текстом. Всё покрываю тестами на
            поддельных таймерах: Enter → один вызов, непрерывный ввод 3 с → минимум 3 вызова.""",
        medium="""Нужно добавить метод flush, который вызывает функцию сразу по Enter, и параметр
            maxWait, чтобы при долгом наборе функция всё равно вызывалась. Во время ввода
            через IME проверять isComposing.""",
        weak="""По Enter можно просто вызвать поиск ещё раз отдельно от debounce."""),
    "testing": dict(
        text=("Нужно покрыть debounce модульными тестами в Jest/Vitest так, чтобы тесты были "
              "быстрыми и не нестабильными. Какие случаи вы проверите и как будете управлять "
              "временем?"),
        criteria=[("timers", "Использует поддельные таймеры (useFakeTimers, advanceTimersByTime), "
                             "а не реальные ожидания", 0.35),
                  ("cases", "Проверяет случаи: серия вызовов → один вызов с последними "
                            "аргументами; пауза больше задержки → два вызова; граница ровно "
                            "delay; аргументы и this; отмена", 0.45),
                  ("hygiene", "Изоляция: восстановление реальных таймеров, отсутствие "
                              "незавершённых таймеров в конце теста", 0.2)],
        strong="""Реальные ожидания делают тесты медленными и нестабильными, поэтому использую
            vi.useFakeTimers() (или jest.useFakeTimers()) и продвигаю время
            vi.advanceTimersByTime. Случаи: три вызова с интервалом 100 мс при delay 300 —
            ни одного вызова до 500 мс, затем ровно один с аргументами последнего; два вызова
            с паузой 400 мс — два вызова с соответствующими аргументами; граница: вызов через
            ровно delay после предыдущего — проверяю, что поведение соответствует
            спецификации; сохранение this и всех аргументов; cancel и flush, если они есть.
            Мок-функция vi.fn() для проверки числа вызовов и аргументов. В afterEach —
            vi.useRealTimers() и проверка vi.getTimerCount() === 0, чтобы утечки таймеров
            не влияли на соседние тесты.""",
        medium="""Нужно использовать фейковые таймеры Jest и проверять, что при нескольких
            быстрых вызовах функция вызывается один раз с последними аргументами, а при паузе
            — несколько раз.""",
        weak="""Можно вызвать функцию и подождать через setTimeout 500 мс, а потом проверить."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    # Калибровка 05.10: подтип разводил шаг 2 (no_clear 0,51 / first_args 0,66); зафиксирован
    # канонический дефект — таймер не сбрасывается (clearTimeout отсутствует).
    sub = rng.choice(["no_clear"])
    delay = rng.choice([200, 300, 400])
    word = rng.choice(WORDS)
    code = _code(sub)

    def seq():
        n = rng.randint(3, 4)
        t, out = 0, []
        for i in range(n):
            out.append([t, word[:i + 2]])
            t += rng.choice([delay // 4, delay // 2, delay + delay // 2, 2 * delay])
        return out

    repro, clean = None, []
    for _ in range(3000):
        c = seq()
        g, b = _sim("good", delay, c), _sim(sub, delay, c)
        if g != b and repro is None:
            repro = c
        elif g == b and c not in clean and len(clean) < 3:
            clean.append(c)
        if repro and len(clean) == 3:
            break
    else:
        raise RuntimeError("не нашлись последовательности")
    desc = lambda c: ", ".join(f"«{q}» в {t} мс" for t, q in c)
    opts1, key1 = make_options(rng, (desc(repro), None), [(desc(c), None) for c in clean], step=1)
    by_text = {desc(repro): repro, **{desc(c): c for c in clean}}
    pool = [k for k in ("no_clear", "first_args", "clear_in_callback", "leading") if k != sub]
    dk = rng.sample(pool, 3)
    opts2, key2 = make_options(rng, ("Заменить debounce на:", _code("good")),
                               [("Заменить debounce на:", _code(k)) for k in dk], step=2)
    by_code = {_code(k): k for k in ("good", "no_clear", "first_args", "clear_in_callback", "leading")}
    t_calls = [[0, "к"], [100, "ко"], [200, "кот"], [900, "д"], [1000, "до"]]
    checks = []
    for o in opts1:
        c = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="node", program=_program(code, delay, c),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=_sim("good", delay, c)))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="node", embeds_display_code=False,
                            program=_program(o.code, 300, t_calls),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=_sim("good", 300, t_calls)))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    ctx = rng.choice(["поиск по каталогу", "подсказки адреса", "поиск по документации", "фильтр таблицы"])
    stem = (f"Поле ввода ({ctx}) вызывает `debounce(fetchSuggestions, {delay})` на каждое изменение "
            f"текста. Требование: подсказки запрашиваются один раз — через {delay} мс после "
            f"последнего изменения — и для последнего введённого текста. Вызов, пришедший ровно в "
            f"момент срабатывания таймера, считается следующим. Пользователь набирает «{word}».")
    steps = ob3_steps(
        "Шаг 1. При каком вводе (текст поля и момент изменения) поведение отличается от "
        "требуемого?",
        "Шаг 2. Выберите исправленную реализацию debounce.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"no_clear": "без clearTimeout каждый вызов оставляет свой таймер — функция срабатывает "
                       "несколько раз (и все с последними аргументами)",
           "first_args": "аргументы запоминаются только в первом вызове серии — запрос уходит для "
                         "устаревшего текста"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Дефект: {why[sub]}. clearTimeout внутри колбэка отменяет не тот "
                               "таймер; вариант с вызовом при timer === null — это leading-режим.")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="debounce_logic",
                         params={"subtype": sub, "delay": delay, "distractors": dk,
                                 "condition": cond_name})
