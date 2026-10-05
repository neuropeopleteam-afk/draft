"""qa.api.cursor_pagination_ob3 — открытая книга: пропуск записей при курсорной пагинации.

Обработчик API сортирует записи по (время, id), но курсор следующей страницы — только
время последней записи, а фильтр строгий (``>``). Если у последней записи страницы и у
следующей одинаковое время, следующая запись пропадает: клиент никогда её не получит.

Шаг 1 — выбрать набор данных (при заданном limit), на котором клиент, листающий все
страницы, получит не все записи (ровно один из четырёх; в двух других наборах тоже есть
одинаковое время, но внутри одной страницы). Шаг 2 — выбрать исправление: курсор-пара
(время, id). Дистракторы: нестрогий фильтр ``>=`` (повторы и возможный бесконечный цикл),
курсор только по id при сортировке по времени, сортировка по id (нарушен контракт порядка),
запрос limit+1 без смены курсора. Скрытая проверка листает страницы на наборе данных с
совпадающим временем, немонотонными id, пустым хранилищем и границами страниц и требует:
все записи ровно по одному разу, порядок (время, id), страница не длиннее limit.
Шаг 3 — объяснение при новом условии (вставки во время листания, изменяемое поле
сортировки, курсор удалённой или поддельной записи, контрактные тесты пагинации).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, ob3_steps, rubric_from
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options

FAMILY_ID = "qa.api.cursor_pagination_ob3"

CONTEXTS = [
    ("лента событий аудита", "list_events", "событий", "created_at"),
    ("история заказов", "list_orders", "заказов", "placed_at"),
    ("чат поддержки", "list_messages", "сообщений", "sent_at"),
    ("платёжный шлюз", "list_payments", "платежей", "paid_at"),
    ("журнал входов", "list_logins", "входов", "logged_at"),
]


def _handler(kind, fn, ts):
    sig = f"def {fn}(store, cursor=None, limit=3):"
    srt_t = f'    rows = sorted(store, key=lambda e: (e["{ts}"], e["id"]))'
    if kind == "buggy":
        body = [srt_t, "    if cursor is not None:",
                f'        rows = [e for e in rows if e["{ts}"] > cursor]',
                "    page = rows[:limit]",
                f'    next_cursor = page[-1]["{ts}"] if len(page) == limit else None']
    elif kind == "good":
        body = [srt_t, "    if cursor is not None:",
                f'        rows = [e for e in rows if (e["{ts}"], e["id"]) > tuple(cursor)]',
                "    page = rows[:limit]",
                f'    last = (page[-1]["{ts}"], page[-1]["id"]) if page else None',
                "    next_cursor = last if len(page) == limit else None"]
    elif kind == "ge":
        body = [srt_t, "    if cursor is not None:",
                f'        rows = [e for e in rows if e["{ts}"] >= cursor]',
                "    page = rows[:limit]",
                f'    next_cursor = page[-1]["{ts}"] if len(page) == limit else None']
    elif kind == "id_only":
        body = [srt_t, "    if cursor is not None:",
                '        rows = [e for e in rows if e["id"] > cursor]',
                "    page = rows[:limit]",
                '    next_cursor = page[-1]["id"] if len(page) == limit else None']
    elif kind == "sort_id":
        body = ['    rows = sorted(store, key=lambda e: e["id"])', "    if cursor is not None:",
                '        rows = [e for e in rows if e["id"] > cursor]',
                "    page = rows[:limit]",
                '    next_cursor = page[-1]["id"] if len(page) == limit else None']
    elif kind == "overfetch":
        body = [srt_t, "    if cursor is not None:",
                f'        rows = [e for e in rows if e["{ts}"] > cursor]',
                "    page = rows[:limit + 1]",
                f'    next_cursor = page[limit - 1]["{ts}"] if len(page) > limit else None',
                "    page = page[:limit]"]
    else:
        raise ValueError(kind)
    return "\n".join([sig] + body + ['    return {"items": page, "next_cursor": next_cursor}'])


CLIENT = '''

def fetch_all(store, limit):
    out, cursor = [], None
    for _ in range(100):
        resp = {fn}(store, cursor, limit)
        assert len(resp["items"]) <= limit, "страница длиннее limit"
        out += resp["items"]
        cursor = resp["next_cursor"]
        if cursor is None:
            return out
    raise AssertionError("пагинация не заканчивается")


def ok(store, limit):
    want = [e["id"] for e in sorted(store, key=lambda e: (e["{ts}"], e["id"]))]
    try:
        got = [e["id"] for e in fetch_all(store, limit)]
    except AssertionError:
        return False
    return got == want


CASES = {cases!r}
good = all(ok([{{"id": i, "{ts}": t}} for i, t in rows], limit) for rows, limit in CASES)
print("RESULT: PASS" if good else "RESULT: FAIL")
'''


def _simulate(kind, fn, ts, rows, limit):
    ns: dict = {}
    exec(compile(_handler(kind, fn, ts), "<h>", "exec"), ns)  # код банка, детерминированный
    store = [{"id": i, ts: t} for i, t in rows]
    out, cur = [], None
    for _ in range(100):
        r = ns[fn](store, cur, limit)
        if len(r["items"]) > limit:
            return False
        out += r["items"]
        cur = r["next_cursor"]
        if cur is None:
            break
    else:
        return False
    return [e["id"] for e in out] == [e["id"] for e in sorted(store, key=lambda e: (e[ts], e["id"]))]


def _times(rng, n, dup_after):
    """n отсортированных времён ЧЧ:ММ; dup_after — позиции i, где t[i] == t[i+1]."""
    h = rng.choice([9, 10, 14, 18, 21])
    m = rng.randint(0, 20)
    out = []
    for i in range(n):
        if i and (i - 1) in dup_after:
            out.append(out[-1])
            continue
        m += rng.randint(1, 4) if i else 0
        out.append(f"{h:02d}:{m:02d}")
    return out


def _dataset(rng, n, limit, dups):
    times = _times(rng, n, dups)
    ids = rng.sample(range(101, 140), n)
    # внутри одинакового времени порядок по id — как в сортировке обработчика
    pairs = sorted(zip(times, ids))
    return [(i, t) for t, i in pairs]


def _fmt(rows):
    return "; ".join(f"id {i} — {t}" for i, t in rows)


CONDITIONS = {
    "inserts": dict(
        text=("Пока клиент листает страницы, в хранилище добавляются новые записи с текущим "
              "временем, а часть старых удаляется. Какие гарантии даёт курсорная пагинация по "
              "сравнению с offset/limit и как это протестировать?"),
        criteria=[("compare", "Сравнивает: offset сдвигается при вставках и удалениях "
                              "(пропуски и повторы), курсор по уникальному ключу сортировки "
                              "не теряет и не повторяет уже существующие записи", 0.4),
                  ("contract", "Формулирует гарантии контракта: каждая запись, существовавшая "
                               "всё время листания, ровно один раз; новые — могут попасть или "
                               "нет; порядок стабилен", 0.3),
                  ("tests", "Тест: между запросами страниц вставлять и удалять записи "
                            "(в начало, середину, на границу страницы) и проверять инварианты; "
                            "многократный прогон или свойство-ориентированный тест", 0.3)],
        strong="""При offset/limit вставка записи перед текущей позицией сдвигает все записи:
            клиент получит одну запись повторно, а удаление — приведёт к пропуску. Курсор,
            построенный на уникальном и неизменном ключе сортировки (время, id), задаёт
            позицию «после этой записи», поэтому вставки и удаления других записей не сдвигают
            его. Контракт: каждая запись, существовавшая всё время листания, придёт ровно один
            раз и в порядке (время, id); удалённые могут не прийти; новые придут, если их ключ
            больше курсора (новые записи с текущим временем окажутся в конце). Тест: листаю
            страницы и между запросами вставляю и удаляю записи — в начало, в середину, ровно
            на границу страницы и с тем же временем, что у курсора; проверяю инварианты
            «нет повторов», «все стабильные записи на месте», «порядок соблюдён». Сценарии
            генерирую случайно (property-based, например Hypothesis) и прогоняю многократно.""",
        medium="""Offset при вставках сдвигается, и записи повторяются или пропадают, а курсор
            по (время, id) этого не допускает. Нужно протестировать вставку и удаление между
            запросами страниц и проверить, что нет повторов и пропусков.""",
        weak="""Курсор и offset работают одинаково, разницы для тестов нет."""),
    "mutable": dict(
        text=("Продакт просит сортировать список по полю updated_at, которое меняется при каждом "
              "редактировании записи. Что сломается в курсорной пагинации и как это "
              "спроектировать и протестировать?"),
        criteria=[("problem", "Видит: запись, изменённая во время листания, переезжает в конец "
                              "или в начало — возможны повтор или пропуск; курсор на изменяемом "
                              "поле нестабилен", 0.4),
                  ("design", "Предлагает: стабильный ключ (created_at, id) для листания, "
                             "снимок или версию набора (as_of), явный контракт про изменённые "
                             "записи, синхронизация изменений отдельным механизмом", 0.35),
                  ("tests", "Тесты: изменить запись до и после курсора между страницами, "
                            "одинаковые updated_at, проверка документированного поведения", 0.25)],
        strong="""Если сортировать по изменяемому полю, запись, отредактированная во время
            листания, меняет позицию: уже выданная запись после правки окажется за курсором и
            придёт второй раз, а ещё не выданная может уйти «за спину» курсора и пропасть.
            Варианты дизайна: листать по стабильному ключу (created_at, id), а свежесть
            показывать отдельно; фиксировать снимок — курсор содержит момент as_of, и запрос
            видит версию данных на этот момент; либо явно задокументировать, что изменённые
            записи могут повториться, и дать клиенту удалять дубли по id. Для синхронизации
            изменений лучше отдельный механизм (журнал изменений с курсором по номеру
            версии). Тесты: между страницами изменяю запись до курсора и после него, делаю
            одинаковые updated_at на границе страницы и проверяю именно то поведение, которое
            записано в контракте.""",
        medium="""Если поле меняется, запись может переместиться в списке и прийти два раза
            или потеряться. Лучше листать по стабильному ключу, например created_at и id, и
            протестировать редактирование записей между запросами страниц.""",
        weak="""Ничего не сломается, курсор просто будет по updated_at."""),
    "cursor_abuse": dict(
        text=("Курсор передаётся клиенту в URL как пара (время, id) открытым текстом. Какие "
              "тесты API нужны для курсора: удалённая запись, ручная правка, мусор, курсор от "
              "другого фильтра или пользователя?"),
        criteria=[("cases", "Перечисляет случаи: курсор удалённой записи, неверный формат, "
                            "подделанное значение, курсор от другого фильтра/сортировки, "
                            "другого пользователя, устаревшая версия формата", 0.35),
                  ("expect", "Ожидаемое поведение: удалённая запись — продолжение со "
                             "следующей; мусор — 400 с понятной ошибкой, без 500; чужой "
                             "курсор не раскрывает чужие данные", 0.35),
                  ("design", "Предлагает непрозрачный подписанный курсор (HMAC, версия, "
                             "фильтр внутри), проверку подписи и тесты на неё", 0.3)],
        strong="""Курсор — это вход от клиента, его нужно тестировать как любой параметр.
            Случаи: курсор записи, которую удалили между запросами, — ожидаю продолжение со
            следующей записи, потому что фильтр «больше пары», а не поиск записи; мусор,
            пустая строка, неверное время или id не числом — 400 с понятной ошибкой, не 500 и
            не пустая страница; ручная правка значения не должна позволять обойти фильтр
            доступа — курсор применяется только вместе с проверкой прав пользователя; курсор,
            выданный для другого фильтра или сортировки, — 400, иначе результат будет
            бессмысленным. Лучше сделать курсор непрозрачным: base64 с версией формата,
            фильтром и подписью HMAC; тогда добавляю тесты на подделанную подпись, старую
            версию формата и курсор другого пользователя.""",
        medium="""Нужно проверить курсор удалённой записи, неправильный формат и подделанный
            курсор: сервер должен вернуть 400, а не 500. Курсор лучше сделать непрозрачным
            и подписанным.""",
        weak="""Курсор формирует сервер, поэтому тестировать его отдельно не нужно."""),
    "contract": dict(
        text=("Составьте набор контрактных тестов пагинации этого эндпоинта для регрессии: "
              "какие данные подготовить и что проверять на каждом ответе и по всем страницам."),
        criteria=[("data", "Данные: пусто, меньше limit, ровно limit и кратно limit, "
                           "совпадающее время на границе страницы, все записи с одним "
                           "временем, немонотонные id", 0.35),
                  ("checks", "Проверки: длина страницы ≤ limit, next_cursor отсутствует "
                             "только на последней, полнота и отсутствие повторов по id, "
                             "порядок сортировки, стабильность повторного запроса", 0.4),
                  ("params", "Параметры: границы limit (0, 1, максимум, больше максимума), "
                             "неверный курсор, код ответа и формат ошибки", 0.25)],
        strong="""Данные готовлю под границы: пустое хранилище; записей меньше limit; ровно
            limit и ровно 2·limit (проверка последней пустой страницы); две записи с
            одинаковым временем ровно на границе страницы; все записи с одним временем при
            limit меньше их числа; id не монотонны по времени, чтобы ловить сортировку по id.
            На каждом ответе: длина items ≤ limit, next_cursor есть, только если дальше есть
            данные (или документированное правило), схема ответа. По всем страницам: каждый id
            ровно один раз, порядок (время, id), объединение равно ожидаемому набору,
            повторный запрос с тем же курсором даёт ту же страницу. Параметры: limit 0, 1,
            максимум и больше максимума, отрицательный и нечисловой limit, мусорный курсор —
            ожидаемые коды 400 и формат ошибки. Такой набор быстрый и годится для каждого
            прогона регрессии.""",
        medium="""Проверить пустой список, несколько страниц, записи с одинаковым временем на
            границе страницы, что нет повторов и пропусков и порядок правильный, а также
            неверный limit и курсор.""",
        weak="""Достаточно проверить, что первая страница возвращает limit записей."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, what, ts = rng.choice(CONTEXTS)
    limit = rng.choice([2, 3])
    n = rng.choice([5, 6]) if limit == 2 else rng.choice([6, 7])
    boundary = [limit * k - 1 for k in range(1, (n - 1) // limit + 1)]  # i: t[i] == t[i+1] пересекает границу
    inside = [i for i in range(n - 1) if i not in boundary]
    for _ in range(300):
        repro = _dataset(rng, n, limit, {rng.choice(boundary)})
        cands = [_dataset(rng, n, limit, set())]
        for _k in range(2):
            cands.append(_dataset(rng, n, limit, {rng.choice(inside)}))
        if (not _simulate("buggy", fn, ts, repro, limit)
                and all(_simulate("buggy", fn, ts, d, limit) for d in cands)
                and len({_fmt(d) for d in cands + [repro]}) == 4):
            break
    else:
        raise RuntimeError("не удалось подобрать наборы")
    code = _handler("buggy", fn, ts)
    opts1, key1 = balanced_options(FAMILY_ID, seed, rng, (_fmt(repro), None),
                                   [(_fmt(d), None) for d in cands], step=1)
    by_text = {_fmt(d): d for d in [repro] + cands}
    # скрытые наборы для шага 2
    hidden = [([(i, t) for i, t in _dataset(rng, 7, 2, {1, 3})], 2),
              ([(105, "12:00"), (101, "12:00"), (109, "12:00"), (103, "12:00")], 2),
              ([], 3),
              ([(i, t) for i, t in _dataset(rng, 6, 3, {2})], 3),
              ([(130, "08:01"), (120, "08:02"), (110, "08:03"), (100, "08:04")], 2),
              ([(i, t) for i, t in _dataset(rng, 6, 2, set())], 2)]
    pool = ["ge", "id_only", "sort_id", "overfetch"]
    chosen = rng.sample(pool, 3)
    for d in chosen:
        assert not all(_simulate(d, fn, ts, r, lim) for r, lim in hidden), d
    assert all(_simulate("good", fn, ts, r, lim) for r, lim in hidden)
    opts2, key2 = balanced_options(FAMILY_ID, seed, rng, ("Заменить обработчик на:", _handler("good", fn, ts)),
                                   [("Заменить обработчик на:", _handler(d, fn, ts)) for d in chosen],
                                   step=2, salt="step2")
    checks = []
    for o in opts1:
        prog = code + CLIENT.format(fn=fn, ts=ts, cases=[(by_text[o.text], limit)])
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=prog,
                            expect="fail" if o.id == key1 else "pass"))
    for o in opts2:
        prog = o.code + CLIENT.format(fn=fn, ts=ts, cases=hidden)
        checks.append(Check(name=f"step2:{o.id}", runner="python", program=prog,
                            embeds_display_code=False,
                            expect="pass" if o.id == key2 else "fail"))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    stem = (f"Эндпоинт ({ctx}) отдаёт список {what} постранично: клиент передаёт `next_cursor` из "
            f"предыдущего ответа, пока он не станет `None`. Обработчик показан ниже. Контракт: "
            f"каждая запись ровно один раз, порядок по `{ts}`, при равенстве — по `id`, на "
            f"странице не больше `limit` записей. От пользователей пришла жалоба: «в выгрузке "
            f"не хватает записей», но воспроизвести её на тестовых данных пока не удалось.")
    steps = ob3_steps(
        f"Шаг 1. На каком наборе данных (limit={limit}, записи перечислены в порядке "
        f"сортировки) клиент, пролистав все страницы, получит не все записи?",
        "Шаг 2. Какой обработчик выполняет контракт на любых данных?",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"ge": "нестрогий фильтр повторяет последнюю запись страницы, а если вся страница с "
                 "одним временем — пагинация не заканчивается",
           "id_only": "курсор по id не согласован с сортировкой по времени: при немонотонных id "
                      "записи пропадают или повторяются",
           "sort_id": "сортировка по id нарушает контракт порядка по времени",
           "overfetch": "запрос limit+1 верно определяет, есть ли следующая страница, но курсор "
                        "по-прежнему только время — пропуск остаётся"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=(f"Курсор — только `{ts}` последней записи, а фильтр строгий: если "
                                f"следующая запись имеет то же время, она отсекается. Поэтому "
                                f"пропуск возникает, только когда одинаковое время приходится на "
                                f"границу страниц (позиции {limit} и {limit + 1}, {2 * limit} и "
                                f"{2 * limit + 1} …). Исправление — курсор-пара ({ts}, id) с "
                                f"тем же порядком, что у сортировки. Дистракторы шага 2: "
                                + "; ".join(why[d] for d in chosen) + f". Шаг 3 — «{cond_name}»."))
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="cursor_tie_skip",
                         display_code_note="Проверка листает все страницы клиентским циклом "
                                           "и сверяет id и порядок; показанный код исполняется "
                                           "дословно.",
                         params={"limit": limit, "n": n, "distractors": chosen,
                                 "condition": cond_name})
