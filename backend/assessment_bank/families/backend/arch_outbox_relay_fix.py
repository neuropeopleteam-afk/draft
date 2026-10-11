"""backend.arch.outbox_relay_fix — choose_fix (Lead): событие о каждом зафиксированном изменении при падении в любой точке.

Показан сервис, который фиксирует изменение в базе и сразу после фиксации публикует событие в брокер:
при падении процесса между фиксацией и публикацией событие теряется. Нужно выбрать замену модуля
(обработчики двух операций и ретранслятор), которая выполняет четыре требования: (1) о каждом
зафиксированном изменении событие доходит до брокера хотя бы раз при падении в любой точке (после
перезапуска ретранслятор дочитывает очередь); (2) нет событий об изменениях, которые не зафиксированы;
(3) события одной сущности — в порядке изменений; (4) повтор допустим — потребители удаляют дубли по id.

Варианты (большие фрагменты, каждый исполняется) построены по схеме 2×2 от верного (запись изменения и
строки outbox в одной транзакции, ретранслятор публикует в порядке вставки и отмечает «отправлено» после
публикации): из пула правил выбираются два (a, b), варианты — верный, нарушено a, нарушено b, нарушены оба.
Пул:
  * mark_before — ретранслятор отмечает «отправлено» до публикации: падение между ними теряет событие;
  * sorted_ids — ретранслятор сортирует очередь по id события («ради детерминизма»): id вида
    «<сущность>:<событие>», и второе событие сущности по алфавиту раньше первого — порядок нарушен;
  * publish_in_tx — первая операция публикует внутри транзакции до фиксации: при падении на фиксации уходит
    событие о незафиксированном изменении;
  * split_tx — вторая операция пишет строку outbox отдельной транзакцией после изменения: падение между
    ними оставляет изменение без события.
Каждый вариант отличается от двух других на одно правило и от третьего — на два; у каждого варианта свои
имена и необязательный комментарий, поэтому ни длина, ни сходство вариантов не выдают ключ.
Ключ проверяется исполнением: модель базы с транзакциями и брокера,
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

RELAY_GOOD = '''
def relay_once(db, broker, batch={batch}):
    for event_id, event in db.pending_outbox(limit=batch):   # в порядке вставки
        broker.publish(event_id, event)
        db.mark_sent(event_id)
'''

# правило -> (фрагмент верного модуля, замена); фрагменты разных правил не пересекаются
MUTATIONS = {
    "mark_before": ("        broker.publish(event_id, event)\n        db.mark_sent(event_id)\n",
                    "        db.mark_sent(event_id)\n        broker.publish(event_id, event)\n"),
    "sorted_ids": ("    for event_id, event in db.pending_outbox(limit=batch):   # в порядке вставки\n",
                   "    for event_id, event in sorted(db.pending_outbox(limit=batch)):   # детерминированно\n"),
    "publish_in_tx": ("        tx.insert(\"outbox\", f\"{{{eid}}}:{e1}\", {{\"type\": \"{e1}\", \"id\": {eid}}})\n",
                      "        broker.publish(f\"{{{eid}}}:{e1}\", {{\"type\": \"{e1}\", \"id\": {eid}}})   # до фиксации\n"),
    "split_tx": ("        tx.update(\"{table}\", {eid}, status=\"{e2}\")\n        tx.insert(\"outbox\",",
                 "        tx.update(\"{table}\", {eid}, status=\"{e2}\")\n    with db.transaction() as tx:\n"
                 "        tx.insert(\"outbox\","),
}
PAIRS = [(x, y) for i, x in enumerate(sorted(MUTATIONS)) for y in sorted(MUTATIONS)[i + 1:]]
WHY = {"mark_before": "отметка «отправлено» до публикации теряет событие при падении между шагами",
       "sorted_ids": "сортировка по id ставит второе событие сущности раньше первого — порядок нарушен",
       "publish_in_tx": "публикация внутри транзакции отправляет событие о незафиксированном изменении при падении "
                        "на фиксации",
       "split_tx": "строка outbox в отдельной транзакции: падение между транзакциями оставляет изменение без события"}
NOTES = ["# изменение и событие — атомарно", "# outbox: событие пишется вместе с изменением",
         "# доставка «хотя бы раз», дубли — по id"]

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
    code_buggy = dedent(BUGGY.format(**f)) + "\n"
    a_, b_ = rng.choice(PAIRS)
    sets = {"good": [], a_: [a_], b_: [b_], f"{a_}+{b_}": [a_, b_]}
    note = rng.choice(NOTES)
    good_tpl = dedent(HANDLERS_OUTBOX) + "\n\n\n" + dedent(RELAY_GOOD) + "\n"
    opt_code = {}
    # у каждого варианта — свои имена и необязательный комментарий; порядок обращений к rng не зависит от текста
    for k, muts in sets.items():
        src = good_tpl.format(**f)
        for mname in muts:
            old, new = MUTATIONS[mname]
            old, new = old.format(**f), new.format(**f)
            if src.count(old) != 1:
                raise ValueError(f"фрагмент правила {mname} не найден ровно один раз")
            src = src.replace(old, new)
        names = {"tx": rng.choice(["tx", "txn", "t"]), "event_id": rng.choice(["event_id", "msg_id", "ev_id"]),
                 "event": rng.choice(["event", "payload", "msg"])}
        src = re.sub(r"\b(tx|event_id|event)\b", lambda m: names[m.group(1)], src)
        if rng.random() < 0.5:
            src = src.replace(f"def {op1}(", f"{note}\ndef {op1}(", 1)
        opt_code[k] = src
    if len(set(opt_code.values())) != 4:
        raise ValueError("варианты 2×2 совпадают")
    chosen = [a_, b_, f"{a_}+{b_}"]
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
            "Остальные нарушают правила: " + f"{WHY[a_]}; {WHY[b_]}; третий вариант нарушает оба.")),
        context=ctx, verification="execution", checks=checks, defect_type="dual_write",
        display_code_note=("Ответ проверяется исполнением: модель базы с транзакциями и брокера, падение процесса "
                           "подставляется в каждую точку, затем перезапуск и проверка инвариантов."),
        params={"table": table, "e1": e1, "e2": e2, "batch": batch, "eid": eid, "a": a, "b": b,
                "distractors": chosen})

