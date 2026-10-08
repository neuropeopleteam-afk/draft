"""backend.db.overbooking_ob3 — открытая книга: гонка «проверка, затем запись» при бронировании.

Обработчик бронирования выполняет несколько отдельных запросов в режиме autocommit: читает
состояние, проверяет в Python и пишет. Два одновременных запроса на последнее место
перепродают его. Подтипы: count_insert (вместимость + COUNT броней, затем INSERT) и
read_modify_write (чтение seats_left, запись вычисленного значения).

Шаг 1 — порядок выполнения запросов к БД двух обработчиков, воспроизводящий перепродажу.
Порядок задаётся детерминированно: обёртка соединения пропускает execute() только в свою
очередь по расписанию (потоки + Condition). Шаг 2 — атомарное исправление одним условным
оператором; каждый вариант прогоняется по ВСЕМ чередованиям запросов (до C(8,4) = 70).
Шаг 3 — PostgreSQL и транзакции, SERIALIZABLE, «горячая» строка, удержание брони.
"""
from __future__ import annotations

import itertools

from assessment_bank.gen_utils import (build_variant, dedent, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.db.overbooking_ob3"

INS = '"INSERT INTO bookings (event_id, user_id) VALUES (?, ?)", (event_id, user_id)'

BUGGY = {
    "count_insert": dedent(f'''
        def book(con, event_id, user_id):
            (capacity,) = con.execute(
                "SELECT capacity FROM events WHERE id = ?", (event_id,)).fetchone()
            (taken,) = con.execute(
                "SELECT COUNT(*) FROM bookings WHERE event_id = ?", (event_id,)).fetchone()
            if taken >= capacity:
                return False
            con.execute({INS})
            return True'''),
    "read_modify_write": dedent(f'''
        def book(con, event_id, user_id):
            (left,) = con.execute(
                "SELECT seats_left FROM events WHERE id = ?", (event_id,)).fetchone()
            if left <= 0:
                return False
            con.execute("UPDATE events SET seats_left = ? WHERE id = ?", (left - 1, event_id))
            con.execute({INS})
            return True'''),
}
STEP_NAMES = {"count_insert": "1 — чтение вместимости, 2 — подсчёт броней, 3 — вставка брони",
              "read_modify_write": "1 — чтение остатка мест, 2 — запись нового остатка, "
                                   "3 — вставка брони"}

FIXES = {
    "count_insert": {
        "good": dedent('''
            def book(con, event_id, user_id):
                cur = con.execute(
                    "INSERT INTO bookings (event_id, user_id) SELECT ?, ? WHERE "
                    "(SELECT COUNT(*) FROM bookings WHERE event_id = ?) < "
                    "(SELECT capacity FROM events WHERE id = ?)",
                    (event_id, user_id, event_id, event_id))
                if cur.rowcount != 1:
                    return False
                return True'''),
        "le_off_by_one": dedent('''
            def book(con, event_id, user_id):
                cur = con.execute(
                    "INSERT INTO bookings (event_id, user_id) SELECT ?, ? WHERE "
                    "(SELECT COUNT(*) FROM bookings WHERE event_id = ?) <= "
                    "(SELECT capacity FROM events WHERE id = ?)",
                    (event_id, user_id, event_id, event_id))
                return cur.rowcount == 1'''),
        "stale_param": dedent('''
            def book(con, event_id, user_id):
                (taken,) = con.execute(
                    "SELECT COUNT(*) FROM bookings WHERE event_id = ?", (event_id,)).fetchone()
                cur = con.execute(
                    "INSERT INTO bookings (event_id, user_id) SELECT ?, ? WHERE "
                    "? < (SELECT capacity FROM events WHERE id = ?)",
                    (event_id, user_id, taken, event_id))
                return cur.rowcount == 1'''),
        "recheck_delete": dedent(f'''
            def book(con, event_id, user_id):
                cur = con.execute({INS})
                (taken,) = con.execute(
                    "SELECT COUNT(*) FROM bookings WHERE event_id = ?", (event_id,)).fetchone()
                (capacity,) = con.execute(
                    "SELECT capacity FROM events WHERE id = ?", (event_id,)).fetchone()
                if taken > capacity:
                    con.execute("DELETE FROM bookings WHERE id = ?", (cur.lastrowid,))
                    return False
                return True'''),
        "or_ignore": dedent('''
            def book(con, event_id, user_id):
                (capacity,) = con.execute(
                    "SELECT capacity FROM events WHERE id = ?", (event_id,)).fetchone()
                (taken,) = con.execute(
                    "SELECT COUNT(*) FROM bookings WHERE event_id = ?", (event_id,)).fetchone()
                if taken >= capacity:
                    return False
                cur = con.execute(
                    "INSERT OR IGNORE INTO bookings (event_id, user_id) VALUES (?, ?)",
                    (event_id, user_id))
                return cur.rowcount == 1'''),
        "count_after": dedent(f'''
            def book(con, event_id, user_id):
                con.execute({INS})
                (taken,) = con.execute(
                    "SELECT COUNT(*) FROM bookings WHERE event_id = ?", (event_id,)).fetchone()
                (capacity,) = con.execute(
                    "SELECT capacity FROM events WHERE id = ?", (event_id,)).fetchone()
                return taken <= capacity'''),
    },
    "read_modify_write": {
        "good": dedent(f'''
            def book(con, event_id, user_id):
                cur = con.execute(
                    "UPDATE events SET seats_left = seats_left - 1 "
                    "WHERE id = ? AND seats_left > 0", (event_id,))
                if cur.rowcount != 1:
                    return False
                con.execute({INS})
                return True'''),
        "guard_ge": dedent(f'''
            def book(con, event_id, user_id):
                cur = con.execute(
                    "UPDATE events SET seats_left = seats_left - 1 "
                    "WHERE id = ? AND seats_left >= 0", (event_id,))
                if cur.rowcount != 1:
                    return False
                con.execute({INS})
                return True'''),
        "relative_no_guard": dedent(f'''
            def book(con, event_id, user_id):
                (left,) = con.execute(
                    "SELECT seats_left FROM events WHERE id = ?", (event_id,)).fetchone()
                if left <= 0:
                    return False
                con.execute("UPDATE events SET seats_left = seats_left - 1 WHERE id = ?", (event_id,))
                con.execute({INS})
                return True'''),
        "cas_no_rowcount": dedent(f'''
            def book(con, event_id, user_id):
                (left,) = con.execute(
                    "SELECT seats_left FROM events WHERE id = ?", (event_id,)).fetchone()
                if left <= 0:
                    return False
                con.execute("UPDATE events SET seats_left = ? WHERE id = ? AND seats_left = ?",
                            (left - 1, event_id, left))
                con.execute({INS})
                return True'''),
        "insert_first": dedent(f'''
            def book(con, event_id, user_id):
                con.execute({INS})
                cur = con.execute(
                    "UPDATE events SET seats_left = seats_left - 1 "
                    "WHERE id = ? AND seats_left > 0", (event_id,))
                return cur.rowcount == 1'''),
        "compensate": dedent(f'''
            def book(con, event_id, user_id):
                con.execute("UPDATE events SET seats_left = seats_left - 1 WHERE id = ?", (event_id,))
                (left,) = con.execute(
                    "SELECT seats_left FROM events WHERE id = ?", (event_id,)).fetchone()
                if left < 0:
                    con.execute("UPDATE events SET seats_left = seats_left + 1 WHERE id = ?", (event_id,))
                    return False
                con.execute({INS})
                return True'''),
    },
}

HARNESS = dedent('''
    import sqlite3
    import threading


    class _Gate:
        """Пропускает execute() строго по расписанию; слоты завершившихся потоков пропускаются."""

        def __init__(self, schedule):
            self.schedule, self.pos, self.done = list(schedule), 0, set()
            self.cv = threading.Condition()

        def wait(self, who):
            with self.cv:
                while self.pos < len(self.schedule) and self.schedule[self.pos] != who:
                    if self.schedule[self.pos] in self.done:
                        self.pos += 1
                        continue
                    self.cv.wait(1)

        def step(self):
            with self.cv:
                self.pos += 1
                self.cv.notify_all()

        def finish(self, who):
            with self.cv:
                self.done.add(who)
                self.cv.notify_all()


    class _Res:
        def __init__(self, cur):
            self._rows, self.rowcount, self.lastrowid = cur.fetchall(), cur.rowcount, cur.lastrowid

        def fetchone(self):
            return self._rows.pop(0) if self._rows else None


    class _Con:
        def __init__(self, con, gate, who):
            self._con, self._gate, self._who = con, gate, who

        def execute(self, sql, params=()):
            self._gate.wait(self._who)
            try:
                return _Res(self._con.execute(sql, params))
            finally:
                self._gate.step()


    def _run(schedule, capacity, taken):
        con = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, capacity INTEGER, seats_left INTEGER)")
        con.execute("CREATE TABLE bookings (id INTEGER PRIMARY KEY, event_id INTEGER, user_id INTEGER, "
                    "UNIQUE (event_id, user_id))")
        con.execute("INSERT INTO events VALUES (1, ?, ?)", (capacity, capacity - taken))
        con.executemany("INSERT INTO bookings (event_id, user_id) VALUES (1, ?)",
                        [(u,) for u in range(1, taken + 1)])
        gate, res = _Gate(schedule), {}

        def worker(who, uid):
            try:
                res[who] = book(_Con(con, gate, who), 1, uid)
            finally:
                gate.finish(who)

        threads = [threading.Thread(target=worker, args=(w, u)) for w, u in (("A", 901), ("B", 902))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3)
        (count,) = con.execute("SELECT COUNT(*) FROM bookings WHERE event_id = 1").fetchone()
        return res.get("A"), res.get("B"), count
    ''')


def _interleavings(k: int) -> list[str]:
    out = []
    for pos in itertools.combinations(range(2 * k), k):
        out.append("".join("A" if i in pos else "B" for i in range(2 * k)))
    return out


def _model_overbook(sub: str, sched: str) -> bool:
    """Независимая модель гонки для кода с дефектом (одно свободное место)."""
    a = [i for i, w in enumerate(sched) if w == "A"]
    b = [i for i, w in enumerate(sched) if w == "B"]
    if sub == "count_insert":   # шаг 2 — подсчёт, шаг 3 — вставка
        return a[1] < b[2] and b[1] < a[2]
    return a[0] < b[1] and b[0] < a[1]  # шаг 1 — чтение, шаг 2 — запись остатка


def _fmt(sched: str) -> str:
    cnt = {"A": 0, "B": 0}
    out = []
    for w in sched:
        cnt[w] += 1
        out.append(f"{w}{cnt[w]}")
    return " ".join(out)


CONDITIONS = {
    "postgres_rc": dict(
        text=("Сервис переносят на PostgreSQL (READ COMMITTED по умолчанию), и коллега "
              "предлагает просто обернуть исходный обработчик в BEGIN … COMMIT. Устранит ли это "
              "перепродажу? Какие способы защиты есть в PostgreSQL и чем они отличаются?"),
        criteria=[("rc", "Объясняет, что транзакция в READ COMMITTED не защищает: оба SELECT "
                         "видят одно и то же, оба INSERT проходят", 0.35),
                  ("options", "Называет рабочие способы: SELECT … FOR UPDATE строки события, "
                              "условный UPDATE счётчика с проверкой rowcount, SERIALIZABLE с "
                              "повтором, ограничение в БД", 0.4),
                  ("tradeoffs", "Сравнивает: блокировки и их порядок (deadlock), повторы при "
                                "40001, нагрузка на одну строку", 0.25)],
        strong="""Нет: в READ COMMITTED каждый SELECT видит данные, зафиксированные к его началу, и
            ничего не блокирует. Две транзакции одновременно прочитают «осталось одно место»,
            обе вставят бронь и зафиксируются — перепродажа сохранится. Рабочие варианты:
            (1) SELECT … FROM events WHERE id = $1 FOR UPDATE — вторая транзакция ждёт первую
            и после её COMMIT перечитывает актуальное значение; бронирования одного события
            идут строго по очереди, а при блокировке нескольких строк нужен единый порядок, иначе
            взаимоблокировки. (2) Атомарный условный UPDATE events SET seats_left = seats_left − 1
            WHERE id = $1 AND seats_left > 0 с проверкой числа затронутых строк — короткая
            блокировка строки, проверка и запись в одном операторе. (3) SERIALIZABLE — СУБД сама
            обнаружит конфликт и откатит одну транзакцию с 40001, её нужно повторить. (4) CHECK
            seats_left >= 0 как последняя линия защиты. Выбираю (2) и CHECK.""",
        medium="""Транзакция сама по себе не поможет на READ COMMITTED: оба запроса прочитают
            старое значение. Нужно SELECT FOR UPDATE или атомарный UPDATE с условием.""",
        weak="""Да, транзакция делает операции атомарными, поэтому перепродажи не будет."""),
    "serializable": dict(
        text=("Команда включила SERIALIZABLE в PostgreSQL. В час старта продаж 30 % запросов "
              "бронирования завершаются ошибкой `could not serialize access` (SQLSTATE 40001), "
              "пользователи видят 500. Что происходит и как это правильно обрабатывать?"),
        criteria=[("cause", "Объясняет: СУБД обнаруживает конфликт параллельных транзакций и "
                            "откатывает одну из них — это нормальное поведение уровня", 0.3),
                  ("retry", "Повтор всей транзакции с начала (не одного оператора) с "
                            "ограниченным числом попыток и задержкой с джиттером; "
                            "идемпотентность побочных эффектов", 0.4),
                  ("contention", "Снижает конфликты: короткие транзакции, условный UPDATE "
                                 "вместо чтения и записи, очередь на «горячее» событие", 0.3)],
        strong="""SERIALIZABLE в PostgreSQL работает оптимистично (SSI): транзакции не ждут друг
            друга, а при обнаружении опасной зависимости одна откатывается с 40001. При старте
            продаж все читают и пишут одно событие, поэтому конфликтов много, и 500 — следствие
            того, что приложение не повторяет. Обработка: перехватываю 40001 (и 40P01 —
            взаимоблокировку) и повторяю всю транзакцию с начала, включая чтения, — 3–5 попыток
            с экспоненциальной задержкой и джиттером; побочные эффекты (письма, платежи) —
            только после COMMIT или через outbox, чтобы повтор их не дублировал. Конфликты
            снижаю: транзакция бронирования должна быть короткой, без внешних вызовов внутри;
            проверку и запись лучше свести к условному UPDATE seats_left — он конфликтует реже.
            Слежу за метрикой доли повторов.""",
        medium="""Это конфликты сериализации — их нужно ловить и повторять транзакцию несколько
            раз, а транзакции делать короче.""",
        weak="""Нужно вернуть уровень READ COMMITTED, тогда ошибок не будет."""),
    "hot_row": dict(
        text=("На старте продаж популярного концерта приходит 5000 запросов в секунду на одно "
              "событие; условный UPDATE одной строки счётчика стал узким местом, задержки "
              "выросли до секунд. Как переработать бронирование, не допуская перепродажи?"),
        criteria=[("why", "Объясняет: все запросы сериализуются на блокировке одной строки, "
                          "пропускная способность ограничена временем удержания блокировки", 0.3),
                  ("design", "Предлагает: разбиение квоты на сегменты (N строк-счётчиков), "
                             "атомарный счётчик в Redis с последующей записью в БД, очередь/"
                             "комната ожидания, предварительные квоты", 0.45),
                  ("consistency", "Сохраняет инвариант и сверку: источник истины, CHECK, "
                                  "компенсация при сбое между счётчиком и БД", 0.25)],
        strong="""Все 5000 запросов в секунду обновляют одну строку, и каждый ждёт, пока предыдущий
            снимет блокировку и зафиксирует транзакцию, — пропускная способность ограничена
            временем одного коммита. Варианты: (1) разбить квоту на N сегментов — N строк с
            долями мест, запрос выбирает случайный сегмент и делает условный UPDATE, при нуле
            пробует следующий; конфликты падают в N раз. (2) Счётчик в Redis: атомарный DECR с
            проверкой (Lua), выигравшие получают временную бронь и записываются в БД асинхронно;
            БД с уникальным индексом и CHECK остаётся источником истины, расхождения
            сверяются и компенсируются. (3) Комната ожидания или очередь: запросы ставятся в
            очередь, один потребитель на событие раздаёт места последовательно и сообщает
            результат. Для билетов с конкретными местами — бронь конкретного места, а не
            общий счётчик. Проверяю нагрузочным тестом и метриками ожидания блокировок.""",
        medium="""Все запросы упираются в одну строку. Можно разделить места на несколько
            счётчиков или вести счётчик в Redis и затем записывать брони в базу.""",
        weak="""Нужно добавить индекс на events.id и увеличить пул соединений."""),
    "hold_ttl": dict(
        text=("Новое требование: место удерживается за пользователем 15 минут до оплаты, потом "
              "освобождается автоматически. Как изменить схему и обработчики, чтобы не было "
              "ни перепродажи, ни «зависших» мест, и что делать, если оплата пришла ровно в "
              "момент истечения брони?"),
        criteria=[("schema", "Статус и срок брони (held/paid/expired, expires_at); подсчёт "
                             "занятых мест учитывает только активные; атомарное условие", 0.35),
                  ("expiry", "Освобождение: фоновая задача или ленивая проверка по expires_at, "
                             "идемпотентно и атомарно", 0.3),
                  ("race", "Гонка оплаты и истечения: условный переход статуса (UPDATE … WHERE "
                           "status = 'held' AND expires_at > now()), возврат денег при "
                           "проигрыше", 0.35)],
        strong="""В bookings добавляю status (held, paid, expired) и expires_at. Создание брони —
            один условный INSERT: место свободно, если число броней со статусом paid или held с
            expires_at > now() меньше вместимости (или условный UPDATE счётчика, который
            увеличивается обратно при истечении). Освобождение: фоновая задача раз в минуту
            делает UPDATE … SET status = 'expired' WHERE status = 'held' AND expires_at <=
            now() — повтор безопасен; а проверка вместимости и так игнорирует просроченные
            брони, поэтому задержка задачи не создаёт зависших мест. Гонку оплаты и
            истечения решает условный переход: UPDATE … SET status = 'paid' WHERE id = $1 AND
            status = 'held' AND expires_at > now(); если затронуто 0 строк, бронь уже истекла —
            пытаюсь заново занять место тем же условным INSERT, а если мест нет, возвращаю
            деньги и сообщаю пользователю. Платёжный webhook обрабатываю идемпотентно по id
            платежа.""",
        medium="""Нужно хранить статус и время истечения брони, освобождать просроченные брони
            фоновой задачей и при оплате проверять, что бронь ещё действует.""",
        weak="""Можно раз в 15 минут удалять все неоплаченные брони."""),
}

CTX = [("билеты на концерт", "концерт"), ("запись на мастер-класс", "мастер-класс"),
       ("столики в ресторанах", "вечер в ресторане"), ("места на вебинар", "вебинар"),
       ("запись к врачу", "приём")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sub = rng.choice(["count_insert", "read_modify_write"])
    ctx, what = rng.choice(CTX)
    capacity = rng.randint(3, 40)
    taken = capacity - 1
    code = BUGGY[sub]
    sch3 = _interleavings(3)
    racy = [s for s in sch3 if _model_overbook(sub, s)]
    clean = [s for s in sch3 if not _model_overbook(sub, s)]
    # не берём совсем очевидные последовательные порядки в качестве «чистых» вариантов
    clean_nontrivial = [s for s in clean if s not in ("AAABBB", "BBBAAA")]
    repro = rng.choice(racy)
    picks = rng.sample(clean_nontrivial, 2) + [rng.choice(clean)]
    while len(set(picks)) < 3:
        picks = rng.sample(clean_nontrivial, 2) + [rng.choice(clean)]
    opts1, key1 = make_options(rng, (_fmt(repro), None), [(_fmt(s), None) for s in picks], step=1)
    by_text = {_fmt(s): s for s in [repro] + picks}
    # длины вариантов: «близкие» дистракторы — в пределах ±15 % от верного (есть и короче,
    # и длиннее), «длинные» — заметно длиннее; не больше одного длинного
    near = {"count_insert": ["le_off_by_one", "stale_param", "count_after"],
            "read_modify_write": ["guard_ge", "insert_first", "relative_no_guard"]}[sub]
    far = [k for k in FIXES[sub] if k != "good" and k not in near]
    if rng.random() < 0.7:
        dk = rng.sample(near, 2) + [rng.choice(far)]
    else:
        dk = list(near)
    rng.shuffle(dk)
    opts2, key2 = make_options(rng, ("Заменить обработчик на:", FIXES[sub]["good"]),
                               [("Заменить обработчик на:", FIXES[sub][k]) for k in dk], step=2)
    by_code = {v: k for k, v in FIXES[sub].items()}
    checks = []
    for o in opts1:
        prog = (HARNESS + "\n\n" + code + "\n\n\n" +
                f"_a, _b, _n = _run({by_text[o.text]!r}, {capacity}, {taken})\n"
                f"print(f\"{{_n}}/{capacity}\")\n")
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=prog,
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=f"{capacity}/{capacity}"))
    all4 = _interleavings(4)
    test = dedent(f"""
        bad = []
        for s in {all4!r}:
            a, b, n = _run(s, {capacity}, {taken})
            if n != {capacity} or sorted([a, b]) != [False, True]:
                bad.append(s)
        a, b, n = _run("AAAABBBB", {capacity}, {capacity - 2})
        if (a, b, n) != (True, True, {capacity}):
            bad.append("free")
        a, b, n = _run("ABABABAB", {capacity}, {capacity})
        if (a, b, n) != (False, False, {capacity}):
            bad.append("full")
        print("OK" if not bad else "BAD " + " ".join(bad[:3]))
        """)
    for o in opts2:
        prog = HARNESS + "\n\n" + o.code + "\n\n\n" + test
        checks.append(Check(name=f"step2:{o.id}", runner="python", program=prog,
                            embeds_display_code=False,
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout="OK"))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    stem = (f"Сервис бронирования ({ctx}). Таблицы: `events(id, capacity, seats_left)` и "
            f"`bookings(id, event_id, user_id)` с UNIQUE (event_id, user_id). Обработчик `book` "
            f"работает в SQLite в режиме autocommit: каждый запрос к БД — отдельная транзакция, "
            f"несколько экземпляров сервиса выполняют запросы вперемешку. Требование: броней на "
            f"событие не больше `capacity`; `book` возвращает True, только если бронь создана. "
            f"Вместимость события ({what}) — {capacity}, занято {taken}, свободно одно место; "
            f"после старта продаж поддержка получила жалобу на лишнюю бронь.")
    steps = ob3_steps(
        "Шаг 1. Пользователи A и B (разные) одновременно бронируют последнее место. Обозначение "
        f"Ak — k-й запрос к БД обработчика A ({STEP_NAMES[sub]}); если обработчик вернул "
        "False раньше, его оставшиеся шаги пропускаются. При каком порядке выполнения "
        "броней станет больше вместимости?",
        "Шаг 2. Выберите исправленный обработчик: без перепродажи и без лишних отказов при "
        "любом чередовании запросов к БД двух экземпляров.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"le_off_by_one": "условие `<=` пропускает вставку при уже заполненном событии — "
                            "броней становится capacity + 1",
           "guard_ge": "условие `seats_left >= 0` разрешает уменьшить остаток с 0 до −1 — "
                       "лишняя бронь",
           "stale_param": "условие INSERT сравнивает вместимость с числом, прочитанным "
                          "раньше, — проверка снова устаревает",
           "recheck_delete": "оба запроса вставляют, оба видят превышение и оба удаляют свою "
                             "бронь — место остаётся свободным, оба получают отказ",
           "or_ignore": "UNIQUE (event_id, user_id) защищает от повторной брони одного "
                        "пользователя, но не от перепродажи разным",
           "count_after": "проверка после вставки возвращает False, но лишняя бронь остаётся",
           "relative_no_guard": "относительный UPDATE без условия не теряет обновление, но "
                                "проверка остатка в Python устарела — обе брони проходят",
           "cas_no_rowcount": "у второго запроса UPDATE … AND seats_left = ? не меняет строку, "
                              "но rowcount не проверяется — бронь всё равно вставляется",
           "insert_first": "бронь вставляется до проверки и не удаляется при отказе",
           "compensate": "оба запроса уменьшают счётчик до −1, оба видят отрицательный "
                         "остаток и оба возвращают место — бронь не получает никто"}
    fix_text = {"count_insert": "проверка и вставка в одном операторе INSERT … SELECT … WHERE "
                                "(подзапрос COUNT) < capacity, результат — по rowcount",
                "read_modify_write": "условный UPDATE seats_left = seats_left − 1 WHERE … AND "
                                     "seats_left > 0 и проверка rowcount перед вставкой"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Перепродажа возникает, когда оба обработчика проверяют "
                               f"состояние до того, как другой его изменит. Исправление: "
                               f"{fix_text[sub]}. Дистракторы: "
                               + "; ".join(why[k] for k in dk) + ".")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="check_then_act_race",
                         params={"subtype": sub, "capacity": capacity, "repro": repro,
                                 "distractors": dk, "condition": cond_name})
