"""backend.arch.outbox_relay_fix — choose_fix (Lead): событие о каждом зафиксированном изменении при падении в любой точке.

Показан сервис, который фиксирует изменение в базе и сразу после фиксации публикует событие в брокер:
при падении процесса между фиксацией и публикацией событие теряется. Нужно выбрать замену модуля
(обработчики двух операций и ретранслятор), которая выполняет четыре требования: (1) о каждом
зафиксированном изменении событие доходит до брокера хотя бы раз при падении в любой точке (после
перезапуска ретранслятор дочитывает очередь); (2) нет событий об изменениях, которые не зафиксированы;
(3) события одной сущности — в порядке изменений; (4) повтор допустим — потребители удаляют дубли по id.

Варианты (большие фрагменты, каждый исполняется):
  * good — запись изменения и строки outbox в одной транзакции, ретранслятор публикует в порядке
    вставки и отмечает «отправлено» после публикации (хотя бы раз);
  * mark_before — ретранслятор отмечает «отправлено» до публикации: падение между ними теряет событие;
  * publish_in_tx — публикация внутри транзакции до фиксации: при падении на фиксации уходит событие о
    незафиксированном изменении;
  * sorted_ids — ретранслятор сортирует очередь по id события («ради детерминизма»): id вида
    «<сущность>:<событие>», и второе событие сущности по алфавиту раньше первого — порядок нарушен.
Состав дистракторов фиксирован. Ключ проверяется исполнением: модель базы с транзакциями и брокера,
падение процесса подставляется в каждую точку (каждая операция с базой и брокером), затем перезапуск и
проверка трёх инвариантов — на показанном коде (падает) и на каждом варианте.
"""
from __future__ import annotations

import re

from assessment_bank.gen_utils import build_variant, dedent, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.arch.outbox_relay_fix"

# контекст, таблица, первая операция, вторая операция, событие 1, событие 2, поле полезной нагрузки
CONTEXTS = [
    ("заказы маркетплейса", "orders", "place_order", "pay_order", "placed", "paid", "amount"),
    ("отклики на вакансии", "applications", "submit_application", "accept_application", "submitted",
     "accepted", "vacancy_id"),
    ("бронирования отелей", "bookings", "create_booking", "confirm_booking", "created", "confirmed", "room"),
    ("счета поставщиков", "invoices", "register_invoice", "pay_invoice", "registered", "paid", "amount"),
    ("заявки на кредит", "loans", "open_application", "approve_loan", "opened", "approved", "limit"),
    ("отправления службы доставки", "shipments", "register_shipment", "dispatch_shipment", "registered",
     "dispatched", "weight"),
    ("подписки на тариф", "subscriptions", "start_subscription", "cancel_subscription", "started", "cancelled",
     "plan"),
    ("обращения в поддержку", "tickets", "open_ticket", "close_ticket", "opened", "closed", "topic"),
]

BUGGY = '''
def {op1}(db, broker, {eid}, {field}):
    with db.transaction() as tx:
        tx.insert("{table}", {eid}, {{"{field}": {field}, "status": "{e1}"}})
    broker.publish(f"{{{eid}}}:{e1}", {{"type": "{e1}", "id": {eid}}})


def {op2}(db, broker, {eid}):
    with db.transaction() as tx:
        tx.update("{table}", {eid}, status="{e2}")
    broker.publish(f"{{{eid}}}:{e2}", {{"type": "{e2}", "id": {eid}}})
'''

HANDLERS_OUTBOX = '''
def {op1}(db, broker, {eid}, {field}):
    with db.transaction() as tx:
        tx.insert("{table}", {eid}, {{"{field}": {field}, "status": "{e1}"}})
        tx.insert("outbox", f"{{{eid}}}:{e1}", {{"type": "{e1}", "id": {eid}}})


def {op2}(db, broker, {eid}):
    with db.transaction() as tx:
        tx.update("{table}", {eid}, status="{e2}")
        tx.insert("outbox", f"{{{eid}}}:{e2}", {{"type": "{e2}", "id": {eid}}})
'''

RELAY = {
    "good": '''
def relay_once(db, broker, batch={batch}):
    for event_id, event in db.pending_outbox(limit=batch):   # в порядке вставки
        broker.publish(event_id, event)
        db.mark_sent(event_id)
''',
    "mark_before": '''
def relay_once(db, broker, batch={batch}):
    for event_id, event in db.pending_outbox(limit=batch):   # в порядке вставки
        db.mark_sent(event_id)          # чтобы второй экземпляр не взял ту же строку
        broker.publish(event_id, event)
''',
    "sorted_ids": '''
def relay_once(db, broker, batch={batch}):
    pending = db.pending_outbox(limit=batch)
    for event_id, event in sorted(pending, key=lambda row: row[0]):   # детерминированный порядок
        broker.publish(event_id, event)
        db.mark_sent(event_id)
''',
}

PUBLISH_IN_TX = '''
def {op1}(db, broker, {eid}, {field}):
    with db.transaction() as tx:
        tx.insert("{table}", {eid}, {{"{field}": {field}, "status": "{e1}"}})
        broker.publish(f"{{{eid}}}:{e1}", {{"type": "{e1}", "id": {eid}}})   # внутри транзакции


def {op2}(db, broker, {eid}):
    with db.transaction() as tx:
        tx.update("{table}", {eid}, status="{e2}")
        broker.publish(f"{{{eid}}}:{e2}", {{"type": "{e2}", "id": {eid}}})   # внутри транзакции


def relay_once(db, broker, batch={batch}):
    return None                          # очередь не нужна: публикуем в транзакции
'''

# Модель базы и брокера (вне показанного кода): каждая операция — точка возможного падения процесса.
WORLD = '''
import contextlib as _ctx


class Crash(Exception):
    pass


class World:
    def __init__(self, fail_at=None):
        self.tables = {{"{table}": {{}}, "outbox": {{}}}}
        self.seq = 0
        self.step = 0
        self.fail_at = fail_at
        self.published = []

    def tick(self):
        self.step += 1
        if self.fail_at is not None and self.step == self.fail_at:
            raise Crash()


class Tx:
    def __init__(self, w):
        self.w, self.ops = w, []

    def insert(self, table, key, value):
        self.w.tick()
        self.ops.append(("ins", table, key, value))

    def update(self, table, key, **fields):
        self.w.tick()
        self.ops.append(("upd", table, key, fields))


class DB:
    def __init__(self, w):
        self.w = w

    @_ctx.contextmanager
    def transaction(self):
        tx = Tx(self.w)
        yield tx                     # исключение внутри блока — откат (операции отброшены)
        self.w.tick()                # падение до фиксации — ничего не записано
        for op, table, key, value in tx.ops:
            if op == "ins" and table == "outbox":
                self.w.seq += 1
                self.w.tables["outbox"][key] = [self.w.seq, dict(value), False]
            elif op == "ins":
                self.w.tables[table][key] = dict(value)
            else:
                self.w.tables[table][key].update(value)

    def pending_outbox(self, limit=100):
        self.w.tick()
        rows = sorted((r[0], k, r[1]) for k, r in self.w.tables["outbox"].items() if not r[2])
        return [(k, dict(e)) for _s, k, e in rows[:limit]]

    def mark_sent(self, event_id):
        self.w.tick()
        self.w.tables["outbox"][event_id][2] = True


class Broker:
    def __init__(self, w):
        self.w = w

    def publish(self, event_id, event):
        self.w.tick()
        self.w.published.append((event_id, dict(event)))
'''

TEST = '''
_relay = globals().get("relay_once", lambda db, broker, batch=10: None)

def _scenario(fail_at):
    w = World(fail_at)
    db, broker = DB(w), Broker(w)
    try:
        {op1}(db, broker, "{a}", {v1})
        {op2}(db, broker, "{a}")
        {op1}(db, broker, "{b}", {v2})
        _relay(db, broker)
    except Crash:
        pass
    w.fail_at = None                 # перезапуск процесса: ретранслятор дочитывает очередь
    for _ in range(6):
        _relay(db, broker)
    return w

def _invariants(w):
    rows = w.tables["{table}"]
    ids = [e for e, _ in w.published]
    for key, row in rows.items():
        assert f"{{key}}:{e1}" in ids, "событие о зафиксированном изменении потеряно"
        if row["status"] == "{e2}":
            assert f"{{key}}:{e2}" in ids, "событие о зафиксированном изменении потеряно"
            assert ids.index(f"{{key}}:{e1}") < ids.index(f"{{key}}:{e2}"), "порядок событий сущности"
    for eid in ids:
        key, kind = eid.split(":")
        assert key in rows, "событие о незафиксированном изменении"
        if kind == "{e2}":
            assert rows[key]["status"] == "{e2}", "событие о незафиксированном изменении"

total = _scenario(None)
_invariants(total)
for fail_at in range(1, total.step + 1):
    _invariants(_scenario(fail_at))
'''

IDS = {"orders": ["o-101", "o-202", "o-317", "o-408"], "applications": ["ap-11", "ap-27", "ap-35", "ap-49"],
       "bookings": ["bk-5", "bk-12", "bk-19", "bk-33"], "invoices": ["inv-71", "inv-84", "inv-90", "inv-96"],
       "loans": ["ln-3", "ln-8", "ln-14", "ln-21"], "shipments": ["sh-40", "sh-52", "sh-66", "sh-78"],
       "subscriptions": ["sub-6", "sub-13", "sub-24", "sub-58"], "tickets": ["t-301", "t-415", "t-522", "t-640"]}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, op1, op2, e1, e2, field = rng.choice(CONTEXTS)
    assert e2 < e1, "второе событие по алфавиту должно быть раньше первого (иначе sorted_ids не ловится)"
    eid = rng.choice(["key", "entity_id", f"{table[:-1]}_id"])
    batch = rng.choice([10, 20, 50, 100])
    a, b = rng.sample(IDS[table], 2)
    v1, v2 = rng.sample([120, 250, 400, 75, 990, 31], 2)
    f = dict(op1=op1, op2=op2, e1=e1, e2=e2, table=table, field=field, eid=eid, batch=batch)
    names = {"tx": rng.choice(["tx", "txn", "t"]), "event_id": rng.choice(["event_id", "msg_id", "ev_id"]),
             "event": rng.choice(["event", "payload", "msg"]), "pending": rng.choice(["pending", "rows", "queue"]),
             "row": rng.choice(["row", "item", "r"])}

    def ren(src: str) -> str:   # поверхностные имена; порядок обращений к rng не зависит от текста
        return re.sub(r"\b(tx|event_id|event|pending|row)\b", lambda m: names[m.group(1)], src)

    code_buggy = ren(dedent(BUGGY.format(**f))) + "\n"
    hand = dedent(HANDLERS_OUTBOX.format(**f))
    opt_code = {k: ren(v) for k, v in {
        "good": hand + "\n\n\n" + dedent(RELAY["good"].format(**f)),
        "mark_before": hand + "\n\n\n" + dedent(RELAY["mark_before"].format(**f)),
        "publish_in_tx": dedent(PUBLISH_IN_TX.format(**f)),
        "sorted_ids": hand + "\n\n\n" + dedent(RELAY["sorted_ids"].format(**f)),
    }.items()}
    chosen = ["mark_before", "publish_in_tx", "sorted_ids"]
    opts, key = make_options(rng, ("Заменить модуль на:", opt_code["good"]),
                             [("Заменить модуль на:", opt_code[d]) for d in chosen])
    by_code = {c: k for k, c in opt_code.items()}
    world = dedent(WORLD.format(table=table))
    test = TEST.format(op1=op1, op2=op2, e1=e1, e2=e2, table=table, a=a, b=b, v1=v1, v2=v2)

    def prog(code: str) -> str:
        return py_harness(world + "\n\n\n" + code, test)

    checks = [Check(name="buggy_fails", runner="python", program=prog(code_buggy), expect="fail",
                    embeds_display_code=False)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python", program=prog(opt_code[by_code[o.code]]),
                            embeds_display_code=False, expect="pass" if o.id == key else "fail"))
    lead = rng.choice([
        f"Сервис «{ctx}» после фиксации изменения в базе сразу публикует событие в брокер. Разбор инцидента: "
        f"процесс перезапустился между фиксацией и публикацией — часть событий потеряна, соседние сервисы "
        f"разошлись с базой.",
        f"В сервисе «{ctx}» потребители событий иногда «не видят» зафиксированные изменения: событие "
        f"публикуется после фиксации транзакции, и падение процесса между этими шагами его теряет.",
        f"Сверка данных «{ctx}» показала: в соседних сервисах нет части изменений, хотя в базе они есть. "
        f"Причина — публикация события после фиксации без гарантии доставки.",
    ])
    stem = (f"{lead}\n\nИнтерфейсы: `db.transaction()` — контекст транзакции (`tx.insert(таблица, ключ, строка)`, "
            f"`tx.update(таблица, ключ, поле=значение)`; исключение внутри — откат); таблица `outbox` — очередь "
            f"событий в той же базе; `db.pending_outbox(limit)` — неотправленные строки outbox в порядке вставки; "
            f"`db.mark_sent(id)`; `broker.publish(id, событие)`. `relay_once` — ретранслятор, запускается по "
            f"расписанию и после перезапуска процесса.\n\n"
            f"Нужна замена модуля, при которой: (1) о каждом зафиксированном изменении событие доходит до брокера "
            f"хотя бы раз при падении процесса в любой точке; (2) нет событий об изменениях, которые не "
            f"зафиксированы; (3) события одной сущности приходят в порядке изменений ({e1} раньше {e2}); "
            f"(4) повтор события допустим — потребители удаляют дубли по id события. Какая замена выполняет все "
            f"четыре требования?")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code_buggy, options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=(
            "Верно: изменение и строка outbox пишутся в одной транзакции (нет события без изменения и изменения "
            "без события), ретранслятор публикует в порядке вставки и отмечает «отправлено» только после "
            "публикации — при падении между ними событие уйдёт повторно, что допустимо (дубли по id). "
            "Отметка до публикации теряет событие при падении между шагами; публикация внутри транзакции "
            "отправляет событие о незафиксированном изменении при падении на фиксации; сортировка по id "
            f"ставит «{e2}» раньше «{e1}» — порядок событий сущности нарушен.")),
        context=ctx, verification="execution", checks=checks, defect_type="dual_write",
        display_code_note=("Ответ проверяется исполнением: модель базы с транзакциями и брокера, падение процесса "
                           "подставляется в каждую точку, затем перезапуск и проверка инвариантов."),
        params={"table": table, "e1": e1, "e2": e2, "batch": batch, "eid": eid, "a": a, "b": b,
                "distractors": chosen})

