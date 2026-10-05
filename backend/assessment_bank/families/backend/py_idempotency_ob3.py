"""backend.py.idempotency_ob3 — открытая книга: идемпотентная обработка вебхуков.

Два подтипа дефекта: ключ дедупликации слишком грубый (payment_id — теряются возвраты)
или слишком мелкий (id + attempt — повторная доставка применяется дважды).
"""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       py_harness, rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.py.idempotency_ob3"

PROVIDERS = [("ЮKassa-подобный эквайринг", "payment", "интернет-магазин"),
             ("платёжный шлюз", "charge", "подписочный сервис"),
             ("агрегатор СБП", "transfer", "маркетплейс"),
             ("биллинг партнёра", "invoice", "B2B-платформа")]

KEYS = {"good": 'event["id"]', "coarse": 'event["{obj}_id"]',
        "fine": '(event["id"], event["attempt"])', "per_type": '(event["{obj}_id"], event["type"])'}


def _code(obj: str, key_kind: str, local_set: bool = False) -> str:
    key = KEYS[key_kind].format(obj=obj)
    lines = ["processed = set()", "balances = {}", "", "",
             "def handle_event(event):"]
    if local_set:
        lines.append("    processed = set()")
    lines += [f"    key = {key}",
              "    if key in processed:",
              '        return "duplicate"',
              f'    sign = -1 if event["type"] == "{obj}.refunded" else 1',
              '    account = event["account"]',
              '    balances[account] = balances.get(account, 0) + sign * event["amount"]',
              "    processed.add(key)",
              '    return "ok"']
    return "\n".join(lines)


def _ev(eid, pid, typ, amount, attempt, account="acc-1"):
    return dict(id=eid, pid=pid, type=typ, amount=amount, attempt=attempt, account=account)


def _apply(events, obj):
    seen, bal = set(), {}
    for e in events:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        sign = -1 if e["type"] == "refunded" else 1
        bal[e["account"]] = bal.get(e["account"], 0) + sign * e["amount"]
    return repr(dict(sorted(bal.items())))


def _literal(events, obj):
    parts = []
    for e in events:
        parts.append('{"id": "%s", "%s_id": "%s", "type": "%s.%s", "amount": %d, "attempt": %d, '
                     '"account": "%s"}' % (e["id"], obj, e["pid"], obj, e["type"], e["amount"],
                                          e["attempt"], e["account"]))
    return "[\n    " + ",\n    ".join(parts) + ",\n]"


def _describe(events):
    return "; ".join(f"{e['id']} ({e['type']}, {e['pid']}, {e['amount']} ₽, попытка {e['attempt']})"
                     for e in events)


def _harness(code, events, obj):
    return code + "\n\n\nfor e in " + _literal(events, obj) + ":\n    handle_event(e)\n" \
        "print(dict(sorted(balances.items())))"


CONDITIONS = {
    "concurrency": dict(
        text=("Обработчик запускается в 8 воркерах, а провайдер при таймауте присылает повтор "
              "через 200 мс, пока первая попытка ещё обрабатывается. Хватит ли исправления? "
              "Как обеспечить однократное применение события при конкурентной обработке?"),
        criteria=[("race", "Видит гонку check-then-act: две попытки одновременно проходят "
                           "проверку `key in processed` до добавления ключа", 0.35),
                  ("atomic", "Делает проверку и применение атомарными: уникальный индекс на "
                             "event_id и INSERT ... ON CONFLICT DO NOTHING в той же транзакции, "
                             "что и изменение баланса; либо блокировка/advisory lock", 0.4),
                  ("shared", "Переносит состояние из памяти процесса в общее хранилище; "
                             "проверка — тест с параллельной доставкой одного события", 0.25)],
        strong="""Нет: множество processed живёт в памяти каждого воркера, а проверка и
            добавление разделены во времени. Две доставки одного события в разные воркеры
            (или в один, но конкурентно) обе пройдут проверку и дважды изменят баланс.
            Нужна атомарность в общем хранилище: таблица processed_events с уникальным ключом
            event_id; в одной транзакции INSERT INTO processed_events ... ON CONFLICT DO NOTHING
            RETURNING и, только если строка вставлена, UPDATE баланса. Конкурирующая
            транзакция упрётся в уникальный индекс и увидит дубль. Альтернатива — SELECT ...
            FOR UPDATE по платежу или advisory lock по event_id. Проверяю нагрузочным тестом:
            100 параллельных доставок одного события дают одно изменение баланса.""",
        medium="""При нескольких воркерах множество в памяти не общее, и два воркера могут
            обработать одно событие. Нужно хранить обработанные id в базе с уникальным
            индексом и проверять там.""",
        weak="""Нужно поставить threading.Lock вокруг функции, тогда дублей не будет."""),
    "crash": dict(
        text=("Процесс может упасть в любой момент: после изменения баланса, но до "
              "`processed.add(key)`, или наоборот. Провайдер повторит доставку. Что произойдёт "
              "в каждом случае и как сделать обработку корректной при сбоях?"),
        criteria=[("cases", "Разбирает оба порядка: сбой после изменения баланса → повтор "
                            "применится второй раз; отметка до применения → событие потеряется", 0.35),
                  ("transaction", "Объединяет изменение баланса и отметку об обработке в одну "
                                  "транзакцию одной базы (или журнал событий с уникальным id)", 0.4),
                  ("ack", "Подтверждает доставку провайдеру (2xx) только после фиксации "
                          "транзакции; побочные эффекты наружу — через outbox", 0.25)],
        strong="""Если упасть после изменения баланса, но до отметки, повторная доставка снова
            пройдёт проверку и спишет деньги второй раз. Если поменять порядок — отметить, а
            потом применять, — сбой между шагами приведёт к потере события: повтор будет
            отброшен как дубль. Выход — атомарность: отметка об обработке и изменение баланса
            в одной транзакции одной базы; при сбое откатываются оба действия, и повтор
            обработается заново. Ответ 2xx провайдеру отдаю только после COMMIT. Если есть
            внешние побочные эффекты (письмо, вызов другого сервиса), записываю их в outbox в
            той же транзакции и отправляю отдельным процессом с собственной идемпотентностью.""",
        medium="""Если процесс упадёт между изменением баланса и сохранением ключа, повтор
            обработается второй раз. Нужно делать оба действия в одной транзакции базы данных.""",
        weak="""Нужно обернуть код в try/except и логировать ошибки."""),
    "memory": dict(
        text=("Сервис работает месяцами и обрабатывает 3 млн событий в сутки; множество "
              "`processed` растёт без ограничений, после рестарта оно пустое. Какие проблемы это "
              "создаёт и как бы вы хранили ключи идемпотентности?"),
        criteria=[("problems", "Называет обе проблемы: рост памяти до OOM и потерю истории при "
                               "рестарте/деплое (повторы после рестарта применятся)", 0.35),
                  ("storage", "Хранит ключи в постоянном хранилище (таблица с уникальным "
                              "индексом, Redis SET NX с TTL) и обосновывает срок хранения окном "
                              "повторов провайдера", 0.4),
                  ("cleanup", "Описывает очистку: TTL/партиции по дате, удаление старше окна "
                              "с запасом; мониторинг размера", 0.25)],
        strong="""Множество в памяти даёт две проблемы: линейный рост (3 млн ключей в сутки —
            сотни мегабайт в месяц, в итоге OOM) и потерю истории при каждом рестарте или
            деплое — повтор, пришедший после перезапуска, применится второй раз. Ключи
            храню в базе: таблица processed_events(event_id PRIMARY KEY, processed_at), вставка
            в той же транзакции, что и изменение баланса. Срок хранения определяется окном
            повторов провайдера (например, 72 часа) плюс запас — неделя; таблицу партиционирую
            по дню и удаляю старые секции целиком. Если нужен Redis — SET key NX EX 604800,
            но тогда атомарность с балансом теряется, поэтому для денег предпочитаю базу.""",
        medium="""Память будет расти, и после перезапуска все ключи пропадут. Лучше хранить
            ключи в Redis или базе с TTL, например на несколько дней.""",
        weak="""Можно периодически очищать множество processed, например раз в сутки."""),
    "ordering": dict(
        text=("Провайдер не гарантирует порядок: событие `refunded` может прийти раньше "
              "`succeeded` того же платежа, а частичных возвратов бывает несколько. Как изменить "
              "модель обработки, чтобы итоговое состояние было верным при любом порядке?"),
        criteria=[("problem", "Понимает, что суммирование событий по мере прихода даёт временно "
                              "неверный (отрицательный) баланс и ломает проверки бизнес-правил "
                              "вроде «нельзя вернуть больше оплаченного»", 0.3),
                  ("model", "Предлагает модель: хранить события по платежу и вычислять "
                            "состояние, конечный автомат с допустимыми переходами, буфер/отложенная "
                            "обработка «раннего» события или запрос актуального статуса у "
                            "провайдера", 0.45),
                  ("tests", "Тесты на перестановки последовательности событий и сумму "
                            "частичных возвратов", 0.25)],
        strong="""При сложении по мере прихода возврат, пришедший раньше оплаты, временно
            уводит баланс в минус, а проверка «возврат не больше оплаты» сработает ложно.
            Переход к модели состояния платежа: все события пишу в журнал (event_id уникален),
            а состояние платежа вычисляю из полного набора событий — оплачено, сумма
            возвратов, остаток. Переходы конечного автомата проверяю: refunded без succeeded
            сохраняю как «ожидает» и применяю, когда придёт оплата, или запрашиваю актуальный
            статус платежа у провайдера по API. Для частичных возвратов ключ — id события, а
            инвариант — сумма возвратов не больше оплаты. Тестирую всеми перестановками
            последовательности событий: итог одинаков.""",
        medium="""Нужно хранить статус платежа и проверять, что возврат приходит после оплаты.
            Если возврат пришёл раньше, его можно отложить и обработать позже.""",
        weak="""Нужно сортировать события по времени прихода перед обработкой."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    provider, obj, ctx = rng.choice(PROVIDERS)
    sub = rng.choice(["coarse", "fine"])
    code = _code(obj, sub)
    n = lambda: f"evt_{rng.randint(1000, 9999)}"
    p1, p2 = f"{obj[:2]}_{rng.randint(10, 99)}", f"{obj[:2]}_{rng.randint(100, 199)}"
    a1, a2 = rng.randint(5, 90) * 100, rng.randint(5, 90) * 100
    r1 = rng.randint(1, a1 // 200) * 100
    ids = []
    while len(ids) < 3:
        x = n()
        if x not in ids:
            ids.append(x)
    e_ok, e_ref, e_other = ids
    retry = [_ev(e_ok, p1, "succeeded", a1, 1), _ev(e_ok, p1, "succeeded", a1, 2)]
    refund = [_ev(e_ok, p1, "succeeded", a1, 1), _ev(e_ref, p1, "refunded", r1, 1)]
    two = [_ev(e_ok, p1, "succeeded", a1, 1), _ev(e_other, p2, "succeeded", a2, 1)]
    single = [_ev(e_ok, p1, "succeeded", a1, 1)]
    if sub == "coarse":
        repro, clean = refund, [retry, two, single]
    else:
        repro, clean = retry, [refund, two, single]
    opts1, key1 = make_options(rng, (_describe(repro), None), [(_describe(c), None) for c in clean], step=1)
    by_text = {_describe(repro): repro, **{_describe(c): c for c in clean}}
    other = "fine" if sub == "coarse" else "coarse"
    dkinds = rng.sample([other, "per_type", "local_set"], 3)
    fix_code = lambda k: _code(obj, "good", local_set=True) if k == "local_set" else _code(obj, k)
    opts2, key2 = make_options(rng, ("Заменить обработчик на:", _code(obj, "good")),
                               [("Заменить обработчик на:", fix_code(k)) for k in dkinds], step=2)
    t_events = [_ev("evt_1", "p_1", "succeeded", 5000, 1), _ev("evt_1", "p_1", "succeeded", 5000, 2),
                _ev("evt_2", "p_1", "refunded", 1000, 1), _ev("evt_3", "p_1", "refunded", 700, 1),
                _ev("evt_3", "p_1", "refunded", 700, 2), _ev("evt_4", "p_2", "succeeded", 300, 1, "acc-2")]
    checks = []
    for o in opts1:
        ev = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=_harness(code, ev, obj),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=_apply(ev, obj)))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python",
                            program=_harness(o.code, t_events, obj), embeds_display_code=False,
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=_apply(t_events, obj)))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    stem = (f"Сервис ({ctx}) принимает вебхуки от провайдера ({provider}) и ведёт балансы счетов. "
            f"Провайдер доставляет события «как минимум один раз»: повторная доставка того же "
            f"события приходит с тем же `id` и увеличенным `attempt`. Разные события одного "
            f"платежа (`{obj}.succeeded`, `{obj}.refunded`, в том числе несколько частичных "
            f"возвратов) имеют разные `id`. Каждое событие должно примениться к балансу ровно "
            f"один раз. Бухгалтерия видит расхождения балансов.")
    steps = ob3_steps(
        "Шаг 1. Какая последовательность событий (id, тип, платёж, сумма, попытка) приведёт к "
        "неверному балансу?",
        "Шаг 2. Выберите исправленный обработчик.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=("Ключ дедупликации по платежу склеивает разные события платежа — "
                                "возврат отбрасывается как дубль." if sub == "coarse" else
                                "Ключ (id, attempt) различает попытки доставки одного события — "
                                "повтор применяется второй раз.")
                   + " Правильный ключ — id события; множество processed внутри функции "
                     "создаётся заново при каждом вызове и ничего не защищает.")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="idempotency_key",
                         params={"subtype": sub, "distractors": dkinds, "condition": cond_name})
