"""common.conc.async_lost_update_ob3 — открытая книга: потерянное обновление в asyncio.

Проверка «прочитать — проверить — await — записать»: между чтением остатка и записью
корутина отдаёт управление, и параллельные резервирования работают со старым значением.
Asyncio детерминирован, поэтому шаги 1–2 проверяются исполнением без флаков.
"""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.conc.async_lost_update_ob3"

CONTEXTS = [("reserve", "stock", "item", "audit", ["sku-17", "sku-42", "sku-93"], "склад интернет-магазина"),
            ("book_seats", "seats_left", "show", "notify_crm", ["concert-1", "concert-2", "stand-up"],
             "продажа билетов"),
            ("take_slots", "slots", "day", "log_event", ["mon", "tue", "wed"], "слоты доставки"),
            ("enroll", "places", "course", "send_metric", ["python-1", "sql-2", "go-3"], "запись на курсы")]


def _code(fn, store, arg, aud, kind):
    head = ["import asyncio", "", f"{store} = {{}}"]
    if kind in ("good_lock", "lock_write_only"):
        head.append("lock = asyncio.Lock()")
    head += ["", "", f"async def {aud}({arg}, qty):",
             "    await asyncio.sleep(0)  # сетевой вызов", "", ""]
    body = {
        "buggy": [f"async def {fn}({arg}, qty):", f"    available = {store}.get({arg}, 0)",
                  "    if available < qty:", "        return False", f"    await {aud}({arg}, qty)",
                  f"    {store}[{arg}] = available - qty", "    return True"],
        "good_lock": [f"async def {fn}({arg}, qty):", "    async with lock:",
                      f"        available = {store}.get({arg}, 0)", "        if available < qty:",
                      "            return False", f"        await {aud}({arg}, qty)",
                      f"        {store}[{arg}] = available - qty", "    return True"],
        "good_reorder": [f"async def {fn}({arg}, qty):", f"    available = {store}.get({arg}, 0)",
                         "    if available < qty:", "        return False",
                         f"    {store}[{arg}] = available - qty", f"    await {aud}({arg}, qty)",
                         "    return True"],
        "lock_inside": [f"async def {fn}({arg}, qty):", "    lock = asyncio.Lock()", "    async with lock:",
                        f"        available = {store}.get({arg}, 0)", "        if available < qty:",
                        "            return False", f"        await {aud}({arg}, qty)",
                        f"        {store}[{arg}] = available - qty", "    return True"],
        "lock_write_only": [f"async def {fn}({arg}, qty):", f"    available = {store}.get({arg}, 0)",
                            "    if available < qty:", "        return False", f"    await {aud}({arg}, qty)",
                            "    async with lock:", f"        {store}[{arg}] = available - qty",
                            "    return True"],
        "reread_write": [f"async def {fn}({arg}, qty):", f"    if {store}.get({arg}, 0) < qty:",
                         "        return False", f"    await {aud}({arg}, qty)",
                         f"    {store}[{arg}] = {store}[{arg}] - qty", "    return True"],
        "yield_first": [f"async def {fn}({arg}, qty):", "    await asyncio.sleep(0)",
                        f"    available = {store}.get({arg}, 0)", "    if available < qty:",
                        "        return False", f"    await {aud}({arg}, qty)",
                        f"    {store}[{arg}] = available - qty", "    return True"],
    }[kind]
    return "\n".join(head + body)


def _serial(initial, calls):
    """Эталон: резервирования применяются по одному в порядке запуска."""
    st, res = dict(initial), []
    for item, q in calls:
        if st.get(item, 0) >= q:
            st[item] = st.get(item, 0) - q
            res.append(True)
        else:
            res.append(False)
    return f"{res}\n{dict(sorted(st.items()))}"


def _harness(code, fn, store, initial, calls, mode):
    if mode == "gather":
        run = f"    res = list(await asyncio.gather({', '.join(f'{fn}({i!r}, {q})' for i, q in calls)}))"
    else:
        run = "    res = []\n" + "\n".join(f"    res.append(await {fn}({i!r}, {q}))" for i, q in calls)
    return (code + f"\n\n\nasync def __bank_main():\n    {store}.update({initial!r})\n{run}\n"
            f"    print(res)\n    print(dict(sorted({store}.items())))\n\n\nasyncio.run(__bank_main())\n")


def _describe(initial, calls, mode, fn):
    st = ", ".join(f"{k}: {v}" for k, v in initial.items())
    cl = ", ".join(f"{fn}({i!r}, {q})" for i, q in calls)
    how = "одновременно через asyncio.gather" if mode == "gather" else "по очереди, каждый с await"
    return f"Остаток {{{st}}}; {how}: {cl}"


CONDITIONS = {
    "multiprocess": dict(
        text=("Остатки переносят из словаря в PostgreSQL, а сервис запускают в 4 процессах uvicorn "
              "на двух серверах. Поможет ли ваше исправление? Как гарантировать, что остаток не "
              "уйдёт в минус и обновления не потеряются?"),
        criteria=[("scope", "Понимает, что asyncio.Lock и порядок операций защищают только внутри "
                            "одного цикла событий одного процесса; между процессами гонка остаётся", 0.35),
                  ("atomic", "Переносит проверку и списание в БД атомарно: UPDATE ... SET qty = qty - :q "
                             "WHERE id = :id AND qty >= :q с проверкой числа изменённых строк, либо "
                             "SELECT ... FOR UPDATE в транзакции, либо версия строки (оптимистичная "
                             "блокировка) с повтором", 0.4),
                  ("ops", "Учитывает побочные эффекты и проверку: вызов аудита вне транзакции или "
                          "через outbox, тест с параллельными запросами к нескольким экземплярам", 0.25)],
        strong="""Нет: и asyncio.Lock, и перестановка записи до await работают только внутри одного
            цикла событий. Четыре процесса на двух серверах читают одну строку параллельно, и
            «прочитать — проверить — записать» снова теряет обновления. Проверку и списание делаю
            одной атомарной операцией в БД: UPDATE stock SET qty = qty - :q WHERE item = :item AND
            qty >= :q; если затронута 0 строк — отказ. Альтернатива — SELECT ... FOR UPDATE в
            транзакции или столбец version с условием в UPDATE и повтором при конфликте. Аудит не
            держу внутри транзакции: пишу событие в outbox той же транзакцией и отправляю отдельно.
            Проверяю нагрузочным тестом: 200 параллельных резервирований на остаток 50 дают ровно
            50 успешных и остаток 0.""",
        medium="""Lock в памяти не работает между процессами. Нужно делать списание в базе одним
            UPDATE с условием qty >= :q или блокировать строку через SELECT FOR UPDATE.""",
        weak="""Нужно использовать asyncio.Lock во всех процессах, тогда гонки не будет."""),
    "threads": dict(
        text=("Функцию переписали на обычный `def` (вместо `await` — синхронный вызов аудита) и "
              "запускают в пуле из 20 потоков. Сохранится ли проблема? Что изменится в исправлении?"),
        criteria=[("race", "Понимает, что гонка сохраняется: GIL не делает последовательность "
                           "чтение-проверка-запись атомарной, поток может переключиться в любой момент", 0.35),
                  ("fix", "Использует threading.Lock (asyncio.Lock не потокобезопасен и не работает "
                          "без цикла событий); держит блокировку только на чтение-проверку-запись, "
                          "а медленный вызов выносит за её пределы", 0.4),
                  ("alt", "Называет альтернативы и проверку: атомарная операция в общем хранилище, "
                          "очередь с одним обработчиком на ключ; стресс-тест с барьером", 0.25)],
        strong="""Сохранится и станет менее предсказуемой: GIL защищает отдельные операции байткода,
            но не последовательность «прочитать остаток — сравнить — записать»; поток может быть
            вытеснен между шагами даже без явного ожидания. asyncio.Lock здесь не подходит — он
            не потокобезопасен и требует цикла событий. Беру threading.Lock (по ключу товара, если
            ключей много) и держу его только на время чтения, проверки и записи; синхронный вызов
            аудита выношу после освобождения блокировки, иначе 20 потоков встанут в очередь на
            сетевом вызове. Если данные в БД — лучше атомарный UPDATE с условием. Проверяю тестом
            с threading.Barrier, который одновременно отпускает 20 потоков, и повторяю его много раз.""",
        medium="""Проблема останется, потому что потоки переключаются между чтением и записью. Нужен
            threading.Lock вокруг проверки и записи, asyncio.Lock для потоков не подходит.""",
        weak="""В потоках проблемы не будет, потому что в Python есть GIL."""),
    "timeout": dict(
        text=("Вызов аудита иногда зависает на 30 секунд. После исправления с блокировкой "
              "пользователи жалуются, что резервирование популярного товара «висит». Почему и как "
              "переделать, сохранив корректность остатков?"),
        criteria=[("cause", "Видит, что медленный ввод-вывод выполняется под блокировкой: все "
                            "резервирования ключа ждут друг друга, задержки складываются", 0.35),
                  ("fix", "Сужает критическую секцию: атомарно проверить и списать без await внутри, "
                          "а аудит выполнить после (или через очередь/outbox); блокировка по ключу, "
                          "а не глобальная", 0.4),
                  ("resilience", "Таймауты на внешний вызов, решение при сбое аудита (компенсация "
                                 "или повтор из очереди), метрики времени ожидания блокировки", 0.25)],
        strong="""Под блокировкой выполняется сетевой вызов аудита, поэтому один зависший вызов на
            30 секунд держит lock, и все следующие резервирования этого товара (а при глобальной
            блокировке — всех товаров) стоят в очереди. Критическая секция должна содержать только
            проверку и списание, без await внутри: в asyncio это делается синхронно — прочитать,
            проверить, записать, — а аудит вызывается после. Надёжнее отправлять аудит через
            очередь или outbox, чтобы его сбой не терял запись. Блокировки, если нужны, делаю по
            ключу товара. На внешний вызов ставлю таймаут (asyncio.timeout), при ошибке аудита
            резервирование не откатываю, а повторяю отправку события. Слежу за метрикой времени
            ожидания блокировки и p99 резервирования.""",
        medium="""Аудит выполняется под блокировкой, и все ждут медленный вызов. Нужно вызывать аудит
            после освобождения блокировки и поставить таймаут на вызов.""",
        weak="""Нужно увеличить таймаут клиента, чтобы запросы не обрывались."""),
    "testing": dict(
        text=("Тимлид просит тест, который ловит эту ошибку в CI стабильно, а не «иногда». Как вы "
              "его построите и как убедитесь, что исправление действительно работает?"),
        criteria=[("deterministic", "Строит детерминированное чередование: asyncio.gather с точкой "
                                    "переключения (sleep(0)/подменённый аудит с asyncio.Event), "
                                    "чтобы обе корутины прочитали остаток до записи", 0.4),
                  ("assertions", "Проверяет инварианты: число успешных резервирований и итоговый "
                                 "остаток равны последовательному исполнению, остаток не "
                                 "отрицателен", 0.35),
                  ("coverage", "Проверяет, что тест падает на старом коде (мутация), и добавляет "
                               "нагрузочный/многопроцессный тест для общего хранилища", 0.25)],
        strong="""Опираюсь на детерминизм asyncio: подменяю аудит заглушкой, которая ждёт
            asyncio.Event, запускаю два резервирования через gather, даю обеим корутинам дойти до
            ожидания и только потом выставляю событие. На старом коде обе прочитают один и тот же
            остаток — тест падает всегда. Проверяю инварианты, а не конкретные строки: число
            успешных резервирований и итоговый остаток совпадают с последовательным исполнением,
            остаток не отрицателен. Обязательно убеждаюсь, что тест красный на старой версии и
            зелёный на новой. Для варианта с базой добавляю интеграционный тест: 100 параллельных
            запросов к нескольким процессам сервиса и проверка остатка.""",
        medium="""Нужно запустить несколько резервирований через asyncio.gather и проверить, что
            итоговый остаток равен ожидаемому. Аудит можно заменить заглушкой со sleep(0).""",
        weak="""Нужно запустить тест много раз подряд, рано или поздно ошибка проявится."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, store, arg, aud, items, ctx = rng.choice(CONTEXTS)
    it, other = rng.sample(items, 2)
    S = rng.randint(6, 12)
    q1 = rng.randint(2, S // 2)
    q2 = rng.randint(2, S // 2)
    code = _code(fn, store, arg, aud, "buggy")
    over = rng.random() < 0.5
    if over:
        q2 = S - q1 + rng.randint(1, min(3, q1))
    repro = ({it: S}, [(it, q1), (it, q2)], "gather")
    clean_pool = {
        "sequential": ({it: S}, [(it, q1), (it, q2)], "seq"),
        "different": ({it: S, other: S}, [(it, q1), (other, q2)], "gather"),
        "single_reject": ({it: S}, [(it, S + rng.randint(1, 4))], "seq"),
        "first_rejected": ({it: S}, [(it, S + rng.randint(1, 3)), (it, q1)], "gather"),
    }
    clean_names = rng.sample(sorted(clean_pool), 3)
    scen = [repro] + [clean_pool[k] for k in clean_names]
    texts = [_describe(i, c, m, fn) for i, c, m in scen]
    opts1, key1 = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]], step=1)
    by_text = dict(zip(texts, scen))
    good = rng.choice(["good_lock", "good_reorder"])
    wrong = rng.sample(["lock_inside", "lock_write_only", "reread_write", "yield_first"], 3)
    opts2, key2 = make_options(rng, ("Заменить код на:", _code(fn, store, arg, aud, good)),
                               [("Заменить код на:", _code(fn, store, arg, aud, w)) for w in wrong],
                               step=2)
    T = rng.randint(8, 14)
    qs = [rng.randint(T // 3 + 1, T // 2) for _ in range(3)]
    t_init, t_calls = {it: T}, [(it, q) for q in qs]
    checks = []
    for o in opts1:
        init, calls, mode = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python",
                            program=_harness(code, fn, store, init, calls, mode),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=_serial(init, calls)))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python", embeds_display_code=False,
                            program=_harness(o.code, fn, store, t_init, t_calls, "gather"),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=_serial(t_init, t_calls)))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    stem = (f"Асинхронный сервис ({ctx}) резервирует остаток функцией `{fn}`: если остатка "
            f"хватает — уменьшает его и возвращает True, иначе возвращает False. `{aud}` — "
            f"сетевой вызов (в примере заменён на `asyncio.sleep(0)`). Требование: результат должен "
            f"быть таким же, как если бы резервирования выполнялись по одному в порядке запуска. "
            f"На нагрузке остатки расходятся с журналом заказов.")
    steps = ob3_steps(
        "Шаг 1. При каком сценарии результат (ответы функции и итоговый остаток) отличается от "
        "требуемого?",
        "Шаг 2. Выберите исправленный код.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why_good = ("asyncio.Lock делает чтение, проверку и запись одной критической секцией" if
                good == "good_lock" else "запись выполняется сразу после проверки, до await, — "
                "между ними нет точки переключения")
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=("Между чтением остатка и записью стоит await: другая корутина "
                                "успевает прочитать то же значение, и одно из списаний теряется "
                                "(или остаток уходит в минус). Сценарии без пересечения корутин "
                                "или с отказом до await дают верный результат. Верное исправление: "
                                + why_good + "."))
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="lost_update_across_await",
                         params={"good": good, "distractors": wrong, "clean": clean_names,
                                 "condition": cond_name, "oversell": over})
