"""common.time.tz_report_ob3 — открытая книга: границы календарного дня и часовой пояс.

Отчёт «выручка за день по московскому времени» считает границы дня неправильно: в UTC вместо
МСК или с включённой правой границей. Метки операций хранятся в UTC (aware datetime).
Шаги 1–2 проверяются исполнением; эталон — независимая модель на целых минутах.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.time.tz_report_ob3"
MSK = timezone(timedelta(hours=3))

CONTEXTS = [("daily_revenue", "orders", "amount", "выручка интернет-магазина"),
            ("daily_payouts", "payouts", "amount", "выплаты курьерам"),
            ("daily_refunds", "refunds", "amount", "возвраты покупателям"),
            ("daily_fees", "fees", "amount", "комиссия маркетплейса")]

START = {
    "good": "    start = datetime(day.year, day.month, day.day, tzinfo=MSK)",
    "utc": "    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)",
    "naive": "    start = datetime(day.year, day.month, day.day)",
    "plus3": "    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=3)",
}
COND = {"good": "        if start <= created_at < end:", "incl": "        if start <= created_at <= end:",
        "replace": "        if start <= created_at.replace(tzinfo=MSK) < end:"}


def _code(fn, coll, val, start_kind, cond_kind):
    return "\n".join([
        "from datetime import datetime, timedelta, timezone", "",
        "MSK = timezone(timedelta(hours=3))", "", "",
        f"def {fn}({coll}, day):",
        f'    """Сумма операций за календарный день day (date) по московскому времени."""',
        START[start_kind], "    end = start + timedelta(days=1)", "    total = 0",
        f"    for created_at, {val} in {coll}:  # created_at — aware datetime в UTC",
        COND[cond_kind], f"            total += {val}", "    return total"])


FIXES = {"good": ("good", "good"), "utc": ("utc", "good"), "incl": ("good", "incl"),
         "naive": ("naive", "good"), "plus3": ("plus3", "good"), "replace": ("good", "replace")}


def _model(events, day):
    lo = datetime(day.year, day.month, day.day, tzinfo=MSK)
    hi = lo + timedelta(days=1)
    return sum(a for t, a in events if lo <= t < hi)


def _lit(events):
    return "[" + ", ".join(
        f"(datetime({t.year}, {t.month}, {t.day}, {t.hour}, {t.minute}, tzinfo=timezone.utc), {a})"
        for t, a in events) + "]"


def _harness(code, fn, events, day):
    return (code + f"\n\n\nprint({fn}({_lit(events)}, __import__('datetime').date({day.year}, "
            f"{day.month}, {day.day})))\n")


def _utc(day, d_off, h, m):
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=d_off)
    return base + timedelta(hours=h, minutes=m)


def _fmt(t):
    return t.strftime("%Y-%m-%d %H:%M") + " UTC"


CONDITIONS = {
    "dst": dict(
        text=("Компания открывает офис в Берлине, отчёт нужен и по берлинскому времени. Коллега "
              "предлагает `BERLIN = timezone(timedelta(hours=1))` и тот же код. Что пойдёт не "
              "так и как считать границы дня правильно?"),
        criteria=[("dst", "Понимает, что у Европы/Берлина летнее время: смещение +1/+2, а день "
                          "перехода длится 23 или 25 часов; фиксированное смещение даёт сдвиг на час "
                          "полгода", 0.35),
                  ("fix", "Использует zoneinfo.ZoneInfo('Europe/Berlin'); начало и конец дня "
                          "вычисляет как локальную полночь дня и следующего дня отдельно, а не "
                          "start + 24 часа; сравнивает в UTC", 0.4),
                  ("ops", "Учитывает обновление tzdata и тесты на даты перехода (последнее "
                          "воскресенье марта и октября)", 0.25)],
        strong="""Фиксированное смещение +1 верно только зимой: в Берлине летнее время (+2), и
            полгода границы дня будут сдвинуты на час. Кроме того, в дни перехода сутки длятся 23
            или 25 часов, поэтому end = start + timedelta(days=1) с фиксированным смещением
            неверен. Беру ZoneInfo('Europe/Berlin'): start = datetime(d.year, d.month, d.day,
            tzinfo=tz), end — полночь следующей даты в той же зоне, отдельно, и сравниваю моменты
            (aware datetime сравниваются по UTC). Метки продолжаю хранить в UTC. Тесты — на
            последние воскресенья марта и октября: операция в 00:30 и 23:30 местного времени попадает
            в нужный день, а длина суток 23 и 25 часов. Слежу за обновлением tzdata в образе.""",
        medium="""Смещение в Берлине меняется летом и зимой, поэтому фиксированный timezone не
            подходит. Нужно использовать zoneinfo с зоной Europe/Berlin и считать полночь в этой
            зоне.""",
        weak="""Нужно поставить смещение +2, так будет правильно большую часть года."""),
    "storage": dict(
        text=("Отчёт переносят в SQL: операции лежат в PostgreSQL, сервер БД работает в UTC, а "
              "аналитик пишет `GROUP BY created_at::date`. Какие ошибки возможны и как написать "
              "запрос правильно, чтобы он ещё и использовал индекс по created_at?"),
        criteria=[("bug", "Видит, что ::date берёт дату в часовом поясе сессии (UTC), операции "
                          "00:00–03:00 МСК попадут в предыдущий день; различает timestamp и "
                          "timestamptz", 0.35),
                  ("fix", "Группирует по (created_at AT TIME ZONE 'Europe/Moscow')::date или "
                          "задаёт часовой пояс сессии; для одного дня фильтрует диапазоном "
                          "[начало дня МСК, следующий день) по самому столбцу", 0.4),
                  ("index", "Объясняет, что функция над столбцом мешает индексу, а диапазон по "
                            "столбцу — нет; при необходимости — индекс по выражению", 0.25)],
        strong="""created_at::date вычисляет дату в часовом поясе сессии, то есть в UTC: операции с
            00:00 до 03:00 по Москве уедут в предыдущие сутки. Если столбец timestamp без зоны,
            ещё и непонятно, в какой зоне записаны значения, — храню timestamptz. Для помесячной
            или посуточной группировки пишу (created_at AT TIME ZONE 'Europe/Moscow')::date либо
            SET TIME ZONE 'Europe/Moscow' в сессии отчёта. Для выборки одного дня использую
            диапазон по самому столбцу: created_at >= '2026-10-05 00:00+03' AND created_at <
            '2026-10-06 00:00+03' — он использует B-tree индекс по created_at, а выражение над
            столбцом — нет (если нужно часто, создаю индекс по выражению). Проверяю на операциях
            около полуночи по Москве.""",
        medium="""Дата будет вычисляться в UTC, и ночные операции попадут в прошлый день. Нужно
            использовать AT TIME ZONE 'Europe/Moscow' или фильтровать по диапазону времени.""",
        weak="""Нужно поменять часовой пояс сервера БД на московский."""),
    "user_tz": dict(
        text=("Отчёт смотрят продавцы маркетплейса из Калининграда (UTC+2) и Владивостока (UTC+10). "
              "Они жалуются, что «вчерашние» операции не совпадают с их собственным учётом. Как "
              "спроектировать отчёт по дням для пользователей в разных часовых поясах?"),
        criteria=[("choice", "Явно выбирает, в чьём часовом поясе считается день (продавца, "
                             "склада или компании), и показывает зону в интерфейсе", 0.3),
                  ("impl", "Хранит IANA-зону пользователя (Europe/Kaliningrad, Asia/Vladivostok), "
                           "метки — в UTC; границы дня вычисляет в зоне пользователя; агрегаты "
                           "считает на лету или в разрезе зоны", 0.45),
                  ("edge", "Учитывает смену зоны пользователем, кэш/предагрегаты по МСК, "
                           "согласованность с выгрузками и тесты на граничные операции", 0.25)],
        strong="""Сначала решаю продуктово: день считается в часовом поясе продавца, и в отчёте
            явно написано «время Владивостока (UTC+10)». В профиле храню IANA-имя зоны, а не
            смещение; все метки — в UTC. Границы дня для отчёта вычисляю как полночь даты в зоне
            продавца и полночь следующей даты, затем фильтрую диапазоном в UTC. Если сейчас
            есть предагрегаты по московским суткам, для чужих зон они не годятся: агрегирую по
            часам в UTC и складываю 24 часа нужного окна (для зон с получасовыми смещениями — по
            15 минут) либо считаю на лету. При смене зоны продавцом старые отчёты пересчитываются;
            выгрузки CSV используют ту же зону. Тесты: операции в 23:30 и 00:30 по Владивостоку.""",
        medium="""Нужно хранить часовой пояс каждого продавца и считать границы дня в его зоне, а
            в интерфейсе показывать, по какому времени построен отчёт.""",
        weak="""Нужно всем показывать отчёт по московскому времени, это стандарт."""),
    "testing": dict(
        text=("Этот дефект жил в проде полгода: тесты проходили, потому что CI запускается в "
              "часовом поясе Europe/Moscow, а тестовые операции создавались днём. Как построить "
              "тесты, чтобы такие ошибки ловились?"),
        criteria=[("boundaries", "Тестирует границы: операции ровно в полночь МСК, за минуту до и "
                                 "после, интервал 00:00–03:00 МСК, конец дня", 0.4),
                  ("env", "Не зависит от зоны машины: aware datetime в тестах, запуск CI с TZ=UTC "
                          "и с другой зоной, внедрение часов вместо datetime.now()", 0.35),
                  ("property", "Добавляет свойство: сумма по всем дням равна общей сумме, каждая "
                               "операция попадает ровно в один день (property-based)", 0.25)],
        strong="""Тесты проверяли «середину дня», где UTC и МСК дают одну дату. Нужны граничные
            случаи: операции в 00:00, 00:01, 02:59 и 23:59 по Москве (21:00, 21:01, 23:59 и 20:59
            UTC соседних дат) и ровно в полночь следующего дня — он не должен попасть в отчёт.
            Тестовые данные создаю только как aware datetime в UTC, без datetime.now() и
            локальной зоны машины; текущее время внедряю через параметр или поддельные часы.
            CI прогоняю минимум дважды — с TZ=UTC и TZ=Asia/Vladivostok, — чтобы скрытая
            зависимость от зоны проявилась. Добавляю свойство (hypothesis): для случайных меток
            каждая операция попадает ровно в один день, а сумма по дням равна общей.""",
        medium="""Нужно добавить тесты с операциями около полуночи по Москве и запускать CI в UTC,
            чтобы результат не зависел от часового пояса машины.""",
        weak="""Нужно добавить больше тестовых операций в разное время дня."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, coll, val, ctx = rng.choice(CONTEXTS)
    sub = rng.choice(["utc", "incl"])
    sk, ck = FIXES[sub]
    code = _code(fn, coll, val, sk, ck)
    day = date(2026, rng.randint(1, 12), rng.randint(2, 27))
    amt = rng.randint(3, 40) * 50
    m = rng.choice([0, 15, 30, 45])
    if sub == "utc":
        repro = _utc(day, -1, rng.choice([21, 22, 23]), m)        # 00:xx–02:xx МСК дня day
        clean = {"noon": _utc(day, 0, rng.randint(9, 14), m),
                 "late": _utc(day, 0, 20, rng.choice([0, 30, 59])),     # 23:xx МСК
                 "prev_evening": _utc(day, -1, rng.choice([18, 19, 20]), m),
                 "next_night": _utc(day, 1, rng.choice([0, 1]), m)}     # 03:xx–04:xx МСК след. дня
    else:
        repro = _utc(day, 0, 21, 0)                                 # ровно полночь МСК след. дня
        clean = {"midnight_start": _utc(day, -1, 21, 0),            # ровно полночь МСК дня day
                 "noon": _utc(day, 0, rng.randint(9, 14), m),
                 "late": _utc(day, 0, 20, rng.choice([30, 59])),
                 "after_end": _utc(day, 0, 21, rng.choice([1, 30]))}
    clean_names = rng.sample(sorted(clean), 3)
    pts = [repro] + [clean[k] for k in clean_names]
    texts = [f"Одна операция на {amt} ₽ с меткой {_fmt(t)}, отчёт за {day:%d.%m.%Y}" for t in pts]
    opts1, key1 = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]], step=1)
    by_text = dict(zip(texts, pts))
    wrong_pool = ["naive", "plus3", "replace", "incl" if sub == "utc" else "utc"]
    wrong = rng.sample(wrong_pool, 3)
    mk = lambda k: _code(fn, coll, val, *FIXES[k])
    opts2, key2 = make_options(rng, ("Заменить функцию на:", mk("good")),
                               [("Заменить функцию на:", mk(w)) for w in wrong], step=2)
    t_events = [(_utc(day, -1, 21, 0), 1), (_utc(day, -1, 22, 30), 2), (_utc(day, 0, 12, 0), 4),
                (_utc(day, 0, 20, 59), 8), (_utc(day, 0, 21, 0), 16), (_utc(day, -1, 20, 0), 32),
                (_utc(day, 0, 22, 0), 64)]
    checks = []
    for o in opts1:
        ev = [(by_text[o.text], amt)]
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=_harness(code, fn, ev, day),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=str(_model(ev, day))))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python", embeds_display_code=False,
                            program=_harness(o.code, fn, t_events, day),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=str(_model(t_events, day))))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    stem = (f"Функция `{fn}` ({ctx}) считает сумму за календарный день по московскому времени "
            f"(МСК = UTC+3, без перехода на летнее время). Метки `created_at` хранятся в UTC как "
            f"aware datetime. Бухгалтерия сверяет отчёт с кассой и находит расхождения в "
            f"отдельные дни.")
    steps = ob3_steps(
        "Шаг 1. На какой операции функция даёт результат, отличный от требуемого?",
        "Шаг 2. Выберите исправленную функцию.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    expl = ("Начало дня задано в UTC: функция считает окно [03:00 МСК дня; 03:00 МСК следующего "
            "дня), поэтому операции 00:00–02:59 МСК этого дня теряются, а такие же ночные операции "
            "следующего дня попадают в отчёт." if sub == "utc" else
            "Правая граница включена: операция ровно в 00:00 МСК следующего дня попадает в два "
            "отчёта сразу. Интервал дня — полуоткрытый [начало; начало следующего дня).")
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=expl + " Верно: начало дня — полночь в зоне МСК, сравнение "
                               "start <= created_at < end; наивный datetime нельзя сравнивать с "
                               "aware, replace(tzinfo=…) меняет момент времени, а +3 часа к "
                               "полуночи UTC сдвигает границу не в ту сторону.")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="day_window_boundary",
                         params={"subtype": sub, "distractors": wrong, "clean": clean_names,
                                 "condition": cond_name, "day": day.isoformat()})
