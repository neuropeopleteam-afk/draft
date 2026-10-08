"""common.alg.merge_intervals_ob3 — «экзамен с открытой книгой»: слияние интервалов.

Шаг 1 — выбрать вход, воспроизводящий дефект; шаг 2 — выбрать исправление;
шаг 3 — объяснить, что сломается при изменении условия (рубрика). Условие шага 3
выбирается независимо от дефекта, поэтому знание ответов шагов 1–2 мало помогает на шаге 3.
"""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       py_harness, rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.alg.merge_intervals_ob3"

CONTEXTS = [
    ("merge_bookings", "bookings", "бронирования переговорной", "минутах от начала дня", "переговорные"),
    ("merge_windows", "windows", "окна обслуживания серверов", "минутах от начала суток", "эксплуатация"),
    ("merge_shifts", "shifts", "смены дежурных инженеров", "часах от начала недели", "дежурства"),
    ("merge_downtime", "periods", "периоды простоя станка", "секундах от начала смены", "производство"),
    ("merge_subscriptions", "periods", "периоды действия подписки", "днях от начала года", "подписки"),
]
RES_NAMES = ["result", "merged", "blocks", "out"]
DEFECTS = ["missing_sort", "overwrite_end", "boundary"]


def _code(fname, arg, res, desc, unit, touch_merge, defect):
    op = "<=" if touch_merge else "<"
    if defect == "boundary":
        op = "<" if touch_merge else "<="
    loop = f"for start, end in {arg}:" if defect == "missing_sort" else \
        f"for start, end in sorted({arg}):"
    upd = f"{res}[-1][1] = end" if defect == "overwrite_end" else \
        f"{res}[-1][1] = max({res}[-1][1], end)"
    touch = "объединяются" if touch_merge else "остаются отдельными"
    return "\n".join([
        f"def {fname}({arg}):",
        f'    """Объединяет пересекающиеся {desc}: [start, end), время в {unit}.',
        "",
        f"    Интервалы, которые только касаются (конец одного = начало другого), {touch}.",
        '    Возвращает список [start, end], отсортированный по началу."""',
        f"    {res} = []",
        f"    {loop}",
        f"        if {res} and start {op} {res}[-1][1]:",
        f"            {upd}",
        "        else:",
        f"            {res}.append([start, end])",
        f"    return {res}",
    ])


def _ref(items, touch_merge):
    out = []
    for s, e in sorted(items):
        if out and (s <= out[-1][1] if touch_merge else s < out[-1][1]):
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _buggy(items, touch_merge, defect):
    out = []
    seq = items if defect == "missing_sort" else sorted(items)
    for s, e in seq:
        op_merge = touch_merge if defect != "boundary" else not touch_merge
        if out and (s <= out[-1][1] if op_merge else s < out[-1][1]):
            out[-1][1] = e if defect == "overwrite_end" else max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _rand_input(rng, scale):
    n = rng.randint(3, 5)
    items = []
    for _ in range(n):
        s = rng.randrange(0, 20) * scale
        items.append((s, s + rng.randint(1, 8) * scale))
    if rng.random() < 0.5:
        a = rng.choice(items)
        items.append((a[1], a[1] + rng.randint(1, 5) * scale))  # касание
    rng.shuffle(items)
    if rng.random() < 0.5:
        items.sort()
    return items[:6]


CONDITIONS = {
    "stream": {
        "text": ("Интервалы теперь поступают потоком — по одному, до 10⁶ за сутки, и после "
                 "каждого нового интервала сервис должен сразу отвечать, свободен ли "
                 "запрошенный слот [s, e). Что станет проблемой в исправленной функции, что вы "
                 "поменяете и как проверите, что новая версия работает правильно?"),
        "criteria": [
            ("complexity", "Видит, что пересортировка всего списка на каждый интервал даёт "
                           "O(n log n) на событие и O(n² log n) на поток — недопустимо при 10⁶", 0.35),
            ("structure", "Предлагает инкрементальную структуру: отсортированный контейнер / "
                          "сбалансированное дерево / дерево интервалов, вставка с поиском соседей "
                          "бинарным поиском и слиянием за O(log n + k)", 0.4),
            ("verification", "Описывает проверку: сравнение с эталонной функцией на случайных "
                             "потоках после каждого шага, граничные случаи (касание, вложение), "
                             "нагрузочный тест", 0.25),
        ],
        "strong": """Сейчас на каждый новый интервал функцию пришлось бы вызывать заново, а она
            сортирует весь список: O(n log n) на событие и O(n² log n) на поток — на 10⁶
            интервалов это часы. Я храню уже объединённые интервалы в отсортированной
            структуре (SortedList из sortedcontainers или сбалансированное дерево по началу).
            При вставке бинарным поиском нахожу соседей, сливаю с ними пересекающиеся и
            удаляю поглощённые — амортизированно O(log n + k). Слот [s, e) свободен, если у
            предшественника по началу конец ≤ s (с учётом правила касания), а следующий
            начинается не раньше e. Проверяю property-тестом: на случайных потоках после
            каждого шага результат совпадает с исходной функцией; отдельно — касание,
            вложение, дубликаты; плюс нагрузочный тест на 10⁶ вставок с замером времени.""",
        "medium": """Функция будет работать медленно, потому что каждый раз сортирует все
            интервалы заново. Лучше хранить уже объединённый список и вставлять новый интервал
            в нужное место через bisect, потом объединять с соседями. Проверить можно на
            большом количестве случайных данных.""",
        "weak": """Ничего не сломается: функция работает правильно, её можно просто вызывать
            после каждого нового интервала.""",
    },
    "timezones": {
        "text": ("Время теперь приходит строками «ЧЧ:ММ» в местном времени разных офисов "
                 "(Калининград, Москва, Новосибирск), а интервал может переходить через "
                 "полночь, например 23:30–00:30. Что сломается в исправленной функции, как "
                 "вы её адаптируете и какими тестами это проверите?"),
        "criteria": [
            ("normalization", "Требует привести время к одной шкале: абсолютные моменты (UTC, "
                              "datetime с часовым поясом), а не строки местного времени", 0.4),
            ("midnight", "Замечает, что при переходе через полночь end < start: сравнение строк и "
                         "сортировка ломаются; предлагает хранить дату или переносить конец на "
                         "следующие сутки", 0.35),
            ("tests", "Предлагает тесты: интервалы разных офисов, пересекающиеся только в UTC; "
                      "переход через полночь; касание на границе суток", 0.25),
        ],
        "strong": """Строки «ЧЧ:ММ» сравниваются лексикографически, и это совпадает с порядком
            времени только в пределах одних суток и одного пояса. Интервал 10:00 в Новосибирске
            и 10:00 в Москве — это разные моменты (разница 4 часа), а 23:30–00:30 даёт end <
            start, и функция посчитает его пустым или «обратным». Поэтому на входе я перевожу
            всё в абсолютное время: дата + время + часовой пояс офиса → datetime в UTC (или
            timestamp), а конец, оказавшийся раньше начала, переношу на следующие сутки. Само
            слияние после этого не меняется. Тесты: два офиса, интервалы которых пересекаются
            только после перевода в UTC; интервал через полночь; касание ровно в 00:00;
            регрессионные тесты старых сценариев на одной зоне.""",
        "medium": """Нужно перевести время в минуты и учесть часовые пояса офисов, например
            привести всё к московскому времени. Интервал через полночь надо обработать
            отдельно, иначе конец окажется меньше начала. Добавить тесты на такие случаи.""",
        "weak": """Строки «ЧЧ:ММ» сортируются правильно, поэтому функция будет работать и
            так, достаточно заменить числа на строки.""",
    },
    "indices": {
        "text": ("Теперь для каждого исходного интервала нужно вернуть ещё и номер "
                 "объединённого блока, в который он попал (например, чтобы уведомить всех "
                 "участников блока). Исходный порядок входа важен. Что мешает сделать это в "
                 "текущей функции, как вы её измените и как проверите?"),
        "criteria": [
            ("order", "Видит, что sorted() теряет связь с исходными позициями: нужно сортировать "
                      "индексы (или пары (интервал, индекс)), а не сами интервалы", 0.4),
            ("mapping", "Строит отображение «исходный индекс → номер блока» за один проход после "
                        "сортировки, сохраняя O(n log n)", 0.35),
            ("tests", "Проверяет: неотсортированный вход, дубликаты одинаковых интервалов, "
                      "вложенные интервалы, касание; инвариант — каждый интервал лежит внутри "
                      "своего блока", 0.25),
        ],
        "strong": """sorted(intervals) возвращает новые кортежи без информации о том, где они
            стояли во входе, а одинаковые интервалы вообще неразличимы. Я сортирую не
            интервалы, а индексы: order = sorted(range(n), key=lambda i: intervals[i]). Иду по
            order, веду текущий блок и для каждого i записываю block_of[i] = номер текущего
            блока; новый блок открываю, когда начало не пересекается с текущим концом по
            тому же правилу касания. Сложность остаётся O(n log n). Тесты: неотсортированный
            вход; два одинаковых интервала на разных позициях; вложенный интервал; касание; и
            проверка инварианта — каждый исходный интервал целиком лежит внутри блока со
            своим номером, а блоки не пересекаются.""",
        "medium": """После сортировки теряются исходные позиции. Можно сортировать пары
            (интервал, индекс) и при объединении запоминать, в какой блок попал каждый индекс.
            Проверить на неотсортированных данных.""",
        "weak": """Можно после объединения для каждого исходного интервала искать блок
            перебором — это и есть ответ, ничего менять в функции не нужно.""",
    },
    "gap": {
        "text": ("Требование изменилось: между соседними интервалами нужна пауза не меньше "
                 "{gap} единиц времени (уборка, прогрев оборудования). Интервалы, между которыми "
                 "пауза меньше {gap}, должны считаться одним блоком. Что и где нужно изменить в "
                 "исправленной функции, какие граничные случаи особенно опасны и как вы их "
                 "проверите?"),
        "criteria": [
            ("condition", "Меняет условие слияния на сравнение с концом блока плюс пауза "
                          "(start < last_end + gap) и явно разбирает, что происходит при паузе "
                          "ровно gap", 0.4),
            ("boundaries", "Называет опасные границы: пауза gap − 1, gap, gap + 1; касание; "
                           "параметризация вместо магического числа", 0.35),
            ("tests", "Предлагает табличные/параметризованные тесты на эти границы и "
                      "сравнение с эталонной реализацией на случайных данных", 0.25),
        ],
        "strong": """Меняется только условие слияния: блок продолжается, если следующий
            интервал начинается раньше, чем «конец блока + пауза», то есть start < last_end +
            gap. По требованию пауза ровно gap допустима, поэтому строгое неравенство; при
            паузе gap − 1 интервалы сливаются, при gap и gap + 1 — нет. gap делаю параметром
            функции со значением по умолчанию, а не числом в коде. Самые опасные места —
            ровно эти границы и прежнее правило касания (gap = 0 должно воспроизводить старое
            поведение). Тесты: параметризованная таблица на паузы gap − 1, gap, gap + 1,
            вложенные интервалы внутри паузы, gap = 0 как регрессия; плюс сравнение с простой
            эталонной реализацией на случайных входах.""",
        "medium": """Нужно в условии сравнивать start с концом последнего блока плюс пауза.
            Проверить случаи, когда пауза чуть меньше и чуть больше нужной, и вынести паузу в
            параметр.""",
        "weak": """Достаточно увеличить концы всех интервалов на величину паузы, и функция
            заработает.""",
    },
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fname, arg, desc, unit, ctx = rng.choice(CONTEXTS)
    res = rng.choice(RES_NAMES)
    touch_merge = rng.random() < 0.5
    defect = rng.choice(DEFECTS)
    scale = rng.choice([1, 5, 10, 15])
    code = _code(fname, arg, res, desc, unit, touch_merge, defect)
    lines = code.splitlines()

    # шаг 1: ровно один вход воспроизводит дефект
    repro, clean = None, []
    for _ in range(4000):
        inp = _rand_input(rng, scale)
        bad = _buggy(inp, touch_merge, defect) != _ref(inp, touch_merge)
        overlapping = len(_ref(inp, touch_merge)) < len(inp)
        if bad and repro is None:
            repro = inp
        elif not bad and overlapping and len(clean) < 3 and inp not in clean:
            clean.append(inp)
        if repro is not None and len(clean) == 3:
            break
    if repro is None or len(clean) < 3:
        raise RuntimeError("не удалось подобрать входы для шага 1")
    opts1, key1 = make_options(rng, (repr(repro), None), [(repr(c), None) for c in clean], step=1)

    # шаг 2: исправления
    op_ok = "<=" if touch_merge else "<"
    if defect == "missing_sort":
        ln = 7
        good = f"    for start, end in sorted({arg}):"
        bad_fixes = [f"    for start, end in sorted({arg}, key=lambda iv: iv[1]):",
                     f"    for start, end in reversed({arg}):",
                     f"    for start, end in sorted({arg}, reverse=True):"]
    elif defect == "overwrite_end":
        ln = 9
        good = f"            {res}[-1][1] = max({res}[-1][1], end)"
        bad_fixes = [f"            {res}[-1][1] = min({res}[-1][1], end)",
                     f"            {res}[-1] = [start, end]",
                     f"            {res}[-1][1] = end if end > start else {res}[-1][1]"]
    else:
        ln = 8
        good = f"        if {res} and start {op_ok} {res}[-1][1]:"
        bad_fixes = [f"        if {res} and {res}[-1][1] {op_ok} start:",
                     f"        if {res} and start {op_ok} {res}[-1][0]:",
                     f"        if {res} and end {op_ok} {res}[-1][1]:"]
    rng.shuffle(bad_fixes)
    # текст — подпись, сама строка кода показывается один раз (в блоке кода)
    fix_opts = [(f"Заменить строку {ln} на:", good)] + [(f"Заменить строку {ln} на:", b) for b in bad_fixes]
    opts2, key2 = make_options(rng, fix_opts[0], fix_opts[1:], step=2)

    cases = [repro] + clean + [
        [], [(0, 5 * scale)], [(10 * scale, 20 * scale), (12 * scale, 14 * scale)],
        [(5 * scale, 9 * scale), (1 * scale, 3 * scale), (2 * scale, 6 * scale)],
        [(0, 4 * scale), (4 * scale, 8 * scale), (8 * scale, 9 * scale)],
        [(3 * scale, 7 * scale), (3 * scale, 7 * scale), (1 * scale, 2 * scale)],
        [(1 * scale, 10 * scale), (2 * scale, 3 * scale), (4 * scale, 5 * scale), (11 * scale, 12 * scale)]]
    tests = (f"cases = {[(c, _ref(c, touch_merge)) for c in cases]!r}\n"
             f"for inp, expected in cases:\n    assert {fname}(list(inp)) == expected, (inp, expected)")
    checks = []
    for o in opts1:
        inp = repro if o.text == repr(repro) else next(c for c in clean if repr(c) == o.text)
        body = f"assert {fname}({inp!r}) == {_ref(inp, touch_merge)!r}"
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=py_harness(code, body),
                            expect="fail" if o.id == key1 else "pass"))
    for o in opts2:
        patched = "\n".join(lines[:ln - 1] + [o.code] + lines[ln:])
        checks.append(Check(name=f"step2:{o.id}", runner="python",
                            program=py_harness(patched, tests),
                            expect="pass" if o.id == key2 else "fail", embeds_display_code=False))

    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    gap = rng.choice([5, 10, 15, 30])
    cond_text = cond["text"].format(gap=gap)
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    touch_txt = "объединяются" if touch_merge else "считаются отдельными"
    stem = (f"Функция `{fname}` объединяет {desc}. Интервалы полуоткрытые [start, end), время в "
            f"{unit}; касающиеся интервалы по требованию {touch_txt}. Результат — список "
            f"объединённых интервалов, отсортированный по началу. В коде есть дефект.")
    steps = ob3_steps(
        "Шаг 1. Воспроизведите дефект: на каком из входов функция вернёт результат, "
        "не соответствующий требованию?",
        "Шаг 2. Выберите исправление, после которого функция работает по требованию на "
        "любых входах.",
        "Шаг 3. " + cond_text + " Ответьте развёрнуто (5–10 предложений).")
    defect_ru = {"missing_sort": "вход не сортируется перед проходом — неотсортированные "
                                 "пересечения не сливаются",
                 "overwrite_end": "конец блока перезаписывается концом текущего интервала, "
                                  "вложенный интервал «укорачивает» блок",
                 "boundary": "условие касания противоречит требованию"}[defect]
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Дефект: {defect_ru}. Шаг 1 — вход {repro}; шаг 2 — "
                               f"`{good.strip()}`; шаг 3 — условие «{cond_name}», по рубрике.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="interval_merge_logic",
                         params={"defect": defect, "touch_merge": touch_merge,
                                 "condition": cond_name, "scale": scale})
