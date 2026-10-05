"""backend.py.rate_limiter_ob3 — открытая книга: ограничитель частоты со скользящим окном."""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.py.rate_limiter_ob3"

HEAD = '''from collections import deque


class SlidingWindowLimiter:
    """Не больше limit запросов на ключ за любые window секунд."""

    def __init__(self, limit, window, clock):
        self.limit = limit
        self.window = window
        self.clock = clock
        self.hits = {}

'''

ALLOW = {
    "good": ["    def allow(self, key):", "        now = self.clock()",
             "        q = self.hits.setdefault(key, deque())",
             "        while q and q[0] <= now - self.window:", "            q.popleft()",
             "        if len(q) >= self.limit:", "            return False",
             "        q.append(now)", "        return True"],
    "boundary": ["    def allow(self, key):", "        now = self.clock()",
                 "        q = self.hits.setdefault(key, deque())",
                 "        while q and q[0] < now - self.window:", "            q.popleft()",
                 "        if len(q) >= self.limit:", "            return False",
                 "        q.append(now)", "        return True"],
    "boundary_alt": ["    def allow(self, key):", "        now = self.clock()",
                     "        q = self.hits.setdefault(key, deque())",
                     "        while q and now - q[0] > self.window:", "            q.popleft()",
                     "        if len(q) >= self.limit:", "            return False",
                     "        q.append(now)", "        return True"],
    "off_by_one": ["    def allow(self, key):", "        now = self.clock()",
                   "        q = self.hits.setdefault(key, deque())",
                   "        while q and q[0] <= now - self.window:", "            q.popleft()",
                   "        if len(q) > self.limit:", "            return False",
                   "        q.append(now)", "        return True"],
    "count_rejected": ["    def allow(self, key):", "        now = self.clock()",
                       "        q = self.hits.setdefault(key, deque())",
                       "        while q and q[0] <= now - self.window:", "            q.popleft()",
                       "        q.append(now)", "        if len(q) > self.limit:",
                       "            return False", "        return True"],
}


def _sim(kind: str, limit: int, window: int, times: list[int]) -> str:
    q: list[int] = []
    out = []
    for now in times:
        if kind == "boundary":
            q = [t for t in q if not t < now - window]
        elif kind == "boundary_alt":
            q = [t for t in q if not now - t > window]
        else:
            q = [t for t in q if not t <= now - window]
        if kind == "count_rejected":
            q.append(now)
            out.append(len(q) <= limit)
        else:
            cap = limit + 1 if kind == "off_by_one" else limit
            ok = len(q) < cap
            if ok:
                q.append(now)
            out.append(ok)
    return "".join("1" if x else "0" for x in out)


def _program(allow_lines: list[str], limit: int, window: int, times: list[int]) -> str:
    return (HEAD + "\n".join(allow_lines) + "\n\n\n"
            f"_times = iter({times!r})\n_now = [0]\n\n\ndef _clock():\n    return _now[0]\n\n\n"
            f"lim = SlidingWindowLimiter({limit}, {window}, _clock)\nout = []\n"
            f"for _t in {times!r}:\n    _now[0] = _t\n    out.append('1' if lim.allow('user') else '0')\n"
            "print(''.join(out))")


CONDITIONS = {
    "multi_instance": dict(
        text=("Сервис масштабировали до 6 экземпляров за балансировщиком, запросы одного "
              "пользователя попадают на разные экземпляры. Что станет с фактическим лимитом и "
              "как реализовать общий лимит? Какие компромиссы у вашего решения?"),
        criteria=[("effect", "Понимает, что лимит в памяти действует на экземпляр: фактически "
                             "до limit × 6 запросов, и зависит от балансировки", 0.3),
                  ("shared", "Переносит состояние в общее хранилище с атомарной операцией: "
                             "Redis ZSET + Lua (ZREMRANGEBYSCORE/ZCARD/ZADD) или INCR с "
                             "окнами; время берётся из одного источника", 0.45),
                  ("tradeoffs", "Обсуждает задержку и отказ хранилища (fail-open/fail-closed), "
                                "приближённые алгоритмы (token bucket, скользящий счётчик), "
                                "локальный кэш", 0.25)],
        strong="""Каждый экземпляр держит свою очередь в памяти, поэтому пользователь получит до
            limit × 6 запросов в окно, а при липкой балансировке — непредсказуемо. Общий лимит
            требует общего состояния с атомарностью: в Redis на ключ пользователя — ZSET с
            отметками времени; Lua-скрипт атомарно делает ZREMRANGEBYSCORE по (now − window],
            ZCARD, при наличии квоты ZADD и PEXPIRE на window. Время беру из Redis (TIME),
            чтобы не зависеть от расхождения часов серверов. Компромиссы: лишний сетевой вызов
            на запрос (~1 мс), поведение при недоступности Redis — для защиты от злоупотреблений
            обычно fail-open с локальным запасным лимитом, для платного API — fail-closed. При
            высокой нагрузке — приближённый скользящий счётчик из двух окон или token bucket:
            O(1) памяти на ключ.""",
        medium="""На каждом экземпляре свой счётчик, поэтому лимит фактически умножится на
            число экземпляров. Нужно хранить счётчики в Redis и делать проверку атомарно,
            например Lua-скриптом.""",
        weak="""Нужно разделить лимит на 6 и поставить каждому экземпляру limit / 6."""),
    "clock": dict(
        text=("Ограничитель в продакшене получает `clock=time.time`. Ночью NTP перевёл часы "
              "сервера на 40 секунд назад, а на другом сервере часы спешат. Что произойдёт с "
              "лимитами и как выбрать источник времени?"),
        criteria=[("effect", "Описывает последствия: при переводе назад отметки оказываются «в "
                             "будущем», окно не очищается и пользователи блокируются; при скачке "
                             "вперёд окно очищается досрочно", 0.35),
                  ("monotonic", "Для локального лимита — time.monotonic(), не зависящий от "
                                "перевода часов", 0.35),
                  ("distributed", "Для общего лимита — единый источник времени (часы "
                                  "хранилища), тесты с подменяемыми часами", 0.3)],
        strong="""time.time — настенные часы, они могут прыгать. После перевода на 40 секунд
            назад все сохранённые отметки окажутся «в будущем»: условие q[0] <= now − window не
            выполнится до тех пор, пока часы не догонят, и пользователи с заполненным окном
            будут получать отказ лишние 40 секунд; при скачке вперёд окно очистится досрочно и
            лимит ослабнет. Для лимита внутри процесса нужен time.monotonic(): он только
            растёт и не реагирует на NTP. Если лимит общий для серверов, локальные монотонные
            часы несравнимы между машинами — время должно браться из одного источника, например
            TIME в Redis внутри Lua-скрипта. Часы уже инъектируются через clock — это позволяет
            тестировать скачки времени подменными часами.""",
        medium="""Если часы переведут назад, старые запросы будут казаться новыми и пользователей
            начнёт блокировать. Нужно использовать time.monotonic, который не зависит от
            перевода часов.""",
        weak="""Нужно синхронизировать часы через NTP почаще."""),
    "memory": dict(
        text=("Лимит ставится по IP, за сутки приходят запросы с 20 млн разных адресов, многие "
              "по одному разу. Через несколько дней процесс падает по памяти. Почему, и как "
              "переделать хранение, чтобы память была ограничена?"),
        criteria=[("cause", "Видит, что ключи в self.hits никогда не удаляются: пустые deque "
                            "остаются навсегда, плюс до limit отметок на ключ", 0.35),
                  ("fix", "Удаляет пустые очереди / периодическая очистка, TTL-кэш с "
                          "вытеснением (LRU), или алгоритм с O(1) памяти на ключ (token "
                          "bucket, скользящий счётчик)", 0.4),
                  ("bounds", "Оценивает память и ставит верхнюю границу, хранение во внешнем "
                             "хранилище с expire", 0.25)],
        strong="""Словарь hits только растёт: даже когда очередь ключа опустела, ключ и пустая
            deque остаются, а при 20 млн разовых адресов в сутки это сотни байт на ключ —
            гигабайты за несколько дней. Исправления: после очистки окна удалять пустую
            очередь; периодически (или при каждом N-м вызове) проходить по ключам и удалять
            те, у которых последняя отметка старше окна; ограничить словарь LRU/TTL-кэшем с
            максимальным размером. Если лимит большой, хранить список отметок дорого —
            перехожу на token bucket (два числа на ключ) или скользящий счётчик из двух
            окон. В распределённом варианте — Redis с PEXPIRE на window, и память
            ограничивается автоматически. Проверяю тестом: после window без запросов размер
            hits возвращается к нулю.""",
        medium="""Ключи никогда не удаляются из словаря, поэтому память растёт. Нужно удалять
            пустые очереди или хранить данные в Redis с истечением срока.""",
        weak="""Нужно увеличить память сервера или перезапускать сервис каждую ночь."""),
    "feedback": dict(
        text=("Мобильный клиент при отказе сразу повторяет запрос в цикле, и в часы пик отказы "
              "лавинообразно растут. Как сервер должен сообщать об отказе и что изменить в "
              "клиенте и в алгоритме, чтобы повторы не усугубляли нагрузку?"),
        criteria=[("protocol", "Сервер отвечает 429 и Retry-After, вычисленным из окна (когда "
                               "освободится самая старая отметка), плюс заголовки RateLimit-*", 0.35),
                  ("client", "Клиент — экспоненциальная задержка с джиттером, уважение "
                             "Retry-After, ограничение числа повторов", 0.35),
                  ("algorithm", "Отказанные запросы не должны занимать квоту; при необходимости "
                                "— token bucket для сглаживания всплесков", 0.3)],
        strong="""Отказ — это 429 Too Many Requests с Retry-After: для скользящего окна его можно
            вычислить точно — q[0] + window − now, то есть когда освободится самая старая
            отметка; дополнительно RateLimit-Limit/Remaining/Reset, чтобы клиент видел запас.
            Клиент должен прекратить немедленные повторы: ждать Retry-After, а без него —
            экспоненциальная задержка с полным джиттером и потолок числа повторов; иначе в пик
            все клиенты повторяют синхронно. В алгоритме важно, что отказанный запрос не
            занимает квоту — иначе клиент, повторяющий в цикле, никогда не выйдет из
            блокировки. Для сглаживания всплесков подходит token bucket с небольшим burst.""",
        medium="""Сервер должен возвращать 429 с заголовком Retry-After, а клиент — ждать перед
            повтором, лучше с экспоненциальной задержкой.""",
        weak="""Нужно возвращать 500, чтобы клиент понял, что сервер перегружен."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sub = rng.choice(["boundary", "off_by_one", "count_rejected"])
    limit, window = rng.choice([2, 3]), rng.choice([5, 10])
    code = HEAD + "\n".join(ALLOW[sub])
    repro, clean = None, []
    for _ in range(3000):
        n = rng.randint(limit + 1, limit + 3)
        times = sorted(rng.sample(range(0, 3 * window), n))
        good, bad = _sim("good", limit, window, times), _sim(sub, limit, window, times)
        if good != bad and repro is None:
            repro = times
        # для off_by_one любой отказ уже воспроизводит дефект, поэтому «чистые» наборы — без отказов
        elif (good == bad and ("0" in good or sub == "off_by_one") and times not in clean
              and len(clean) < 3):
            clean.append(times)
        if repro and len(clean) == 3:
            break
    else:
        raise RuntimeError("не нашлись последовательности")
    desc = lambda ts: "t = " + ", ".join(map(str, ts))
    opts1, key1 = make_options(rng, (desc(repro), None), [(desc(c), None) for c in clean], step=1)
    by_text = {desc(repro): repro, **{desc(c): c for c in clean}}
    pool = [k for k in ("boundary", "boundary_alt", "off_by_one", "count_rejected") if k != sub]
    dk = rng.sample(pool, 3)
    opts2, key2 = make_options(rng, ("Заменить метод allow на:", "\n".join(ALLOW["good"])),
                               [("Заменить метод allow на:", "\n".join(ALLOW[k])) for k in dk], step=2)
    by_code = {"\n".join(ALLOW[k]): k for k in ALLOW}
    t_l, t_w, t_times = 2, 10, [0, 1, 2, 10, 11, 12, 21]
    checks = []
    for o in opts1:
        ts = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python",
                            program=_program(ALLOW[sub], limit, window, ts),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=_sim("good", limit, window, ts)))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python", embeds_display_code=False,
                            program=_program(ALLOW[by_code[o.code]], t_l, t_w, t_times),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=_sim("good", t_l, t_w, t_times)))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    ctx = rng.choice(["публичное API", "форма входа", "API отправки SMS", "поиск по каталогу"])
    stem = (f"Ограничитель частоты ({ctx}) должен пропускать не больше `limit` запросов на ключ за "
            f"любые `window` секунд: запрос в момент t учитывает принятые запросы из интервала "
            f"(t − window, t]; отклонённые запросы квоту не расходуют. Здесь limit = {limit}, "
            f"window = {window}, время — целые секунды, часы подменяются в тестах. Пользователи "
            f"жалуются на неверные отказы или пропуски сверх лимита.")
    steps = ob3_steps(
        "Шаг 1. При какой последовательности моментов запросов одного пользователя ответы "
        "ограничителя отличаются от требуемых?",
        "Шаг 2. Выберите исправленный метод allow.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"boundary": "отметка ровно в t − window не удаляется — граница окна включена",
           "off_by_one": "проверка > вместо >= пропускает limit + 1 запрос",
           "count_rejected": "отметка добавляется до проверки — отказанные запросы занимают квоту"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Дефект: {why[sub]}. Вариант `now - q[0] > window` эквивалентен "
                               "условию `q[0] < now - window` и сохраняет ошибку границы.")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="rate_window_logic",
                         params={"subtype": sub, "limit": limit, "window": window,
                                 "distractors": dk, "condition": cond_name})
