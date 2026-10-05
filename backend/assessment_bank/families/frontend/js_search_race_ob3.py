"""frontend.js.search_race_ob3 — открытая книга: гонка ответов при живом поиске."""
from __future__ import annotations

import json

from assessment_bank.families.frontend._fake_timers import FAKE_TIMERS
from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.search_race_ob3"

BUGGY = """function createSearch(api, render) {
  return async function onInput(query) {
    const items = await api.search(query);
    render(query, items);
  };
}"""
FIXES = {
    "good": """function createSearch(api, render) {
  let lastId = 0;
  return async function onInput(query) {
    const id = ++lastId;
    const items = await api.search(query);
    if (id === lastId) render(query, items);
  };
}""",
    "post_inc": """function createSearch(api, render) {
  let lastId = 0;
  return async function onInput(query) {
    const id = lastId++;
    const items = await api.search(query);
    if (id === lastId) render(query, items);
  };
}""",
    "check_before": """function createSearch(api, render) {
  let lastId = 0;
  return async function onInput(query) {
    const id = ++lastId;
    if (id !== lastId) return;
    const items = await api.search(query);
    render(query, items);
  };
}""",
    "latest_after": """function createSearch(api, render) {
  let latest = null;
  return async function onInput(query) {
    const items = await api.search(query);
    latest = query;
    if (latest === query) render(query, items);
  };
}""",
    "non_empty": """function createSearch(api, render) {
  return async function onInput(query) {
    const items = await api.search(query);
    if (items.length > 0) render(query, items);
  };
}""",
}


def _sim(kind, typed, lat):
    """typed: [[t, q]], lat: {q: мс} → последовательность отрисовок."""
    reqs = [(t + lat[q], i, t, q) for i, (t, q) in enumerate(typed)]
    renders = []
    for done, i, _t, q in sorted(reqs):
        issued_after = [j for j, (tj, _) in enumerate(typed) if j > i and tj <= done]
        if kind == "buggy":
            renders.append(q)
        elif kind == "good" and not issued_after:
            renders.append(q)
    return renders


def _program(code, typed, lat, mode):
    out = ("renders.length ? renders[renders.length - 1] : '(пусто)'" if mode == "final"
           else "renders.join(' ') || '(пусто)'")
    return (FAKE_TIMERS + "\n\n" + code + "\n\n;(async () => {\n"
            f"  const latency = {json.dumps(lat, ensure_ascii=False)};\n"
            "  const api = { search: (q) => new Promise((resolve) => "
            "setTimeout(() => resolve([q + ' — результат']), latency[q])) };\n"
            "  const renders = [];\n  const onInput = createSearch(api, (q, items) => renders.push(q));\n"
            f"  for (const [t, q] of {json.dumps(typed, ensure_ascii=False)}) {{\n"
            "    await advanceTo(t);\n    onInput(q);\n  }\n  await advanceTo(1e9);\n"
            f"  console.log({out});\n}})();\n")


CONDITIONS = {
    "react": dict(
        text=("Поиск переписали на React: запрос делается в `useEffect(() => {...}, [query])`. "
              "Как правильно отбросить устаревший ответ в этой модели и что изменится в "
              "режиме разработки со StrictMode?"),
        criteria=[("cleanup", "Использует cleanup эффекта: флаг ignore/cancelled или "
                              "AbortController.abort() при смене query и размонтировании", 0.4),
                  ("strict", "Понимает, что StrictMode в разработке монтирует эффект дважды — "
                             "корректный cleanup делает это безопасным", 0.3),
                  ("alternatives", "Упоминает библиотеки данных (TanStack Query/SWR) с ключом "
                                   "запроса и отменой, обработку ошибок AbortError", 0.3)],
        strong="""В эффекте заводим let ignore = false (или AbortController), запускаем запрос,
            после ответа вызываем setItems только если !ignore; cleanup эффекта выставляет
            ignore = true или вызывает controller.abort(). React вызывает cleanup перед
            следующим запуском эффекта при смене query и при размонтировании, поэтому любой
            ответ на устаревший query будет проигнорирован. AbortController вдобавок отменяет
            сам сетевой запрос; AbortError ловлю и не показываю пользователю. В StrictMode в
            разработке эффект монтируется, размонтируется и монтируется повторно — с
            корректным cleanup первый запрос просто отменяется, и это хорошая проверка. В
            реальном проекте удобнее TanStack Query: ключ ['search', query], отмена через
            signal и кэш результатов.""",
        medium="""В useEffect нужно завести флаг ignore и в функции очистки ставить его в true,
            чтобы не обновлять состояние от старого запроса. Можно также отменять запрос через
            AbortController.""",
        weak="""Нужно добавить query в зависимости useEffect, тогда React сам отменит старые
            запросы."""),
    "abort": dict(
        text=("Запросы поиска дорогие: каждый занимает до 2 с CPU на сервере, и при быстром "
              "наборе сервер обрабатывает много запросов, ответы на которые уже не нужны. "
              "Достаточно ли отбрасывать ответы на клиенте? Что вы сделаете на клиенте и на "
              "сервере?"),
        criteria=[("client", "Отменяет запросы через AbortController (fetch signal) и "
                             "сокращает их число: debounce, минимальная длина запроса", 0.35),
                  ("server", "Понимает, что отмена fetch закрывает соединение, но сервер "
                             "должен сам прекращать работу при разрыве (проверка отмены, "
                             "таймауты запроса к БД)", 0.35),
                  ("cache", "Кэш результатов по запросу, ограничение частоты, метрики доли "
                            "отменённых запросов", 0.3)],
        strong="""Отбрасывание на клиенте исправляет отображение, но не нагрузку: сервер всё
            равно считает ненужные ответы. На клиенте отменяю предыдущий запрос через
            AbortController — fetch закроет соединение; добавляю debounce 200–300 мс и
            минимальную длину запроса в 2–3 символа. На сервере отмена работает, только если
            обработчик реагирует на разрыв соединения: в асинхронном сервере проверяю
            отмену запроса и прерываю поиск, для БД — statement_timeout и отмена запроса
            при разрыве. Добавляю кэш результатов популярных префиксов на короткое время и
            ограничение частоты на пользователя. Метрики: доля отменённых запросов и
            нагрузка до и после.""",
        medium="""Нет, сервер всё равно обрабатывает старые запросы. Нужно отменять их через
            AbortController и добавить debounce, чтобы запросов было меньше.""",
        weak="""Достаточно, потому что пользователь видит правильный результат."""),
    "cache": dict(
        text=("Пользователи часто стирают последний символ и набирают его снова, а также "
              "возвращаются к предыдущим запросам. Как добавить кэш результатов поиска, чтобы "
              "интерфейс был быстрым, но не показывал устаревшие данные?"),
        criteria=[("cache", "Кэш по нормализованному запросу с ограничением размера (LRU) и "
                            "временем жизни", 0.35),
                  ("swr", "Стратегия stale-while-revalidate: показать из кэша сразу и "
                          "обновить в фоне; дедупликация одинаковых запросов в полёте", 0.35),
                  ("race", "Сохраняет защиту от гонок: ответ фонового обновления отрисовывается, "
                           "только если запрос всё ещё актуален", 0.3)],
        strong="""Ключ кэша — нормализованный запрос (trim, нижний регистр). Храню в LRU на
            50–100 записей с временем жизни 1–5 минут в зависимости от того, как быстро
            меняются данные. При вводе: если ответ есть в кэше — отрисовываю сразу; если он
            старше TTL — показываю его и параллельно перезапрашиваю (stale-while-revalidate).
            Одинаковые запросы в полёте дедуплицирую: храню промис по ключу, второй вызов
            ждёт тот же промис. Защиту от гонок не убираю: и ответ из сети, и фоновое
            обновление отрисовываются только если запрос всё ещё последний. При изменении
            данных (например, добавлен товар) кэш инвалидирую. Готовое решение — TanStack
            Query с staleTime и gcTime.""",
        medium="""Можно хранить результаты в Map по тексту запроса и показывать их сразу, если
            они есть. Нужно ограничить размер кэша и время жизни записей.""",
        weak="""Нужно сохранять все результаты в localStorage навсегда."""),
    "states": dict(
        text=("Под полем поиска есть индикатор загрузки и сообщение об ошибке. Иногда "
              "индикатор пропадает, хотя актуальный запрос ещё выполняется, а ошибка старого "
              "запроса затирает свежие результаты. Как организовать состояния загрузки и "
              "ошибок при нескольких запросах в полёте?"),
        criteria=[("ownership", "Связывает состояние с конкретным запросом: loading/error "
                                "меняет только актуальный запрос (тот же id/AbortController)", 0.4),
                  ("model", "Единая модель состояния (idle/loading/success/error) вместо "
                            "независимых флагов; отменённые запросы не порождают ошибку", 0.35),
                  ("ux", "Повтор запроса по ошибке, сохранение прошлых результатов во время "
                         "загрузки, aria-live для экранных дикторов", 0.25)],
        strong="""Индикатор и ошибку должны менять только ответы актуального запроса. Храню
            одно состояние {status: idle|loading|success|error, query, items, error} и
            requestId: перед запросом — status=loading с новым id; в finally и catch проверяю
            id === lastId, иначе ничего не меняю. Тогда завершение старого запроса не снимет
            индикатор нового, а его ошибка не затрёт свежие результаты. При отмене через
            AbortController AbortError не считается ошибкой. Во время загрузки оставляю
            прошлые результаты затемнёнными, а не пустой список; для ошибки — кнопка
            «Повторить». Изменения статуса объявляю через aria-live="polite". Тест:
            медленный упавший старый запрос и быстрый успешный новый — на экране результаты
            нового без ошибки.""",
        medium="""Нужно менять индикатор загрузки и ошибку только для последнего запроса,
            проверяя его идентификатор. Отменённые запросы не должны показывать ошибку.""",
        weak="""Нужно показывать индикатор загрузки, пока не завершатся все запросы."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    word = rng.choice(["кроссовки", "смартфон", "рюкзак", "монитор", "кресло", "термос"])
    qs = [word[:n] for n in range(2, 2 + rng.randint(3, 4))]

    def scenario(kind):
        for _ in range(500):
            t, typed = 0, []
            for q in qs:
                typed.append([t, q])
                t += rng.choice([80, 120, 200, 300])
            lat = {q: rng.choice([50, 100, 150, 250, 400, 700]) for q in qs}
            b, g = _sim("buggy", typed, lat), _sim("good", typed, lat)
            final_wrong = b[-1] != qs[-1]
            overlap = b != g
            if kind == "repro" and final_wrong:
                return typed, lat
            if kind == "overlap_ok" and overlap and not final_wrong:
                return typed, lat
            if kind == "sequential" and not overlap:
                return typed, lat
        raise RuntimeError("не нашёлся сценарий")

    cands = [scenario("repro"), scenario("overlap_ok"), scenario("overlap_ok"), scenario("sequential")]
    desc = lambda s: "; ".join(f"«{q}» в {t} мс, ответ через {s[1][q]} мс" for t, q in s[0])
    texts = [desc(c) for c in cands]
    if len(set(texts)) < 4:
        cands[2] = scenario("sequential")
        texts = [desc(c) for c in cands]
        if len(set(texts)) < 4:
            raise RuntimeError("совпали сценарии")
    opts1, key1 = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]], step=1)
    by_text = dict(zip(texts, cands))
    dk = rng.sample(["post_inc", "check_before", "latest_after", "non_empty"], 3)
    opts2, key2 = make_options(rng, ("Заменить на:", FIXES["good"]),
                               [("Заменить на:", FIXES[k]) for k in dk], step=2)
    t_typed = [[0, "мо"], [100, "мон"], [200, "мони"], [300, "монит"]]
    t_lat = {"мо": 500, "мон": 50, "мони": 300, "монит": 100}
    checks = []
    for o in opts1:
        typed, lat = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="node",
                            program=_program(BUGGY, typed, lat, "final"),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=qs[-1]))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="node", embeds_display_code=False,
                            program=_program(o.code, t_typed, t_lat, "all"),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=" ".join(_sim("good", t_typed, t_lat)) or "(пусто)"))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    ctx = rng.choice(["интернет-магазин", "маркетплейс", "сравнение цен", "каталог B2B"])
    stem = (f"Живой поиск ({ctx}): на каждое изменение поля вызывается `onInput(query)`, функция "
            f"`render` показывает результаты под полем. Пользователь набирает «{word}». "
            f"Требование: на экране всегда остаются результаты для последнего введённого текста. "
            f"Время ответа сервера заметно различается от запроса к запросу.")
    steps = ob3_steps(
        "Шаг 1. В каком сценарии (момент ввода и время ответа на каждый запрос) на экране в "
        "итоге останутся результаты не для последнего текста?",
        "Шаг 2. Выберите исправление.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"post_inc": "id = lastId++ никогда не равен lastId — результаты не отрисуются",
           "check_before": "проверка до await ничего не защищает",
           "latest_after": "latest присваивается после ответа — условие всегда истинно",
           "non_empty": "проверка непустого ответа не связана с порядком"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation="Ответы приходят не в порядке запросов: медленный ранний ответ "
                               "перезаписывает поздний. Верно — запоминать номер запроса и "
                               "отрисовывать только последний. Дистракторы: "
                               + "; ".join(why[k] for k in dk) + ".")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=BUGGY, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="stale_response_race",
                         params={"distractors": dk, "condition": cond_name})
