"""common.dist.outbox_fix — choose_fix: двойная запись «БД + брокер» и transactional outbox.

Обработчик сохраняет сущность в БД и публикует событие в брокер. В исходном коде событие
публикуется после коммита: падение процесса между коммитом и публикацией теряет событие.
Требование: после любого падения и перезапуска (relay запускается снова) для каждой
закоммиченной сущности опубликовано событие, и нет событий о незакоммиченных сущностях;
дубли допустимы (потребители дедуплицируют по идентификатору).

Верный вариант — transactional outbox: строка outbox пишется в той же транзакции, relay
публикует и только после этого помечает строку отправленной (at-least-once).
Дистракторы фиксированы (урок калибровки 05.10: состав дистракторов не варьируется):
  * publish_in_tx — публикация внутри транзакции до коммита (падение на коммите → «призрак»);
  * mark_first — relay сначала помечает строку, потом публикует (падение между → потеря);
  * outbox_second_tx — outbox пишется второй транзакцией после коммита (падение между → потеря).
Проверка исполнением: модель БД с транзакциями и брокера, падение процесса инъецируется в
каждую возможную точку (каждая операция БД/брокера и коммит), после чего relay перезапускается;
инвариант проверяется для каждой точки.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.dist.outbox_fix"

# (контекст, таблица, сущность-параметр, поле события, тема брокера, функция-обработчик, доп. поле)
CONTEXTS = [
    ("интернет-магазин", "orders", "order", "order_id", "order-created", "place_order", "total"),
    ("платёжный шлюз", "payments", "payment", "payment_id", "payment-captured", "capture_payment", "amount"),
    ("сервис регистраций", "signups", "signup", "signup_id", "user-registered", "register_user", "email"),
    ("бронирование отелей", "bookings", "booking", "booking_id", "booking-confirmed", "confirm_booking", "nights"),
]

PRELUDE = '''from contextlib import contextmanager


class Crash(Exception):
    pass


class Faults:
    def __init__(self, at):
        self.at, self.n = at, 0

    def step(self):
        self.n += 1
        if self.n == self.at:
            raise Crash()


class Tx:
    def __init__(self, buf, faults):
        self.buf, self.f = buf, faults

    def insert(self, table, key, row):
        self.f.step()
        self.buf.setdefault(table, {})[key] = dict(row)


class DB:
    def __init__(self, faults):
        self.tables, self.f = {}, faults

    @contextmanager
    def transaction(self):
        buf = {}
        yield Tx(buf, self.f)
        self.f.step()  # коммит
        for t, rows in buf.items():
            self.tables.setdefault(t, {}).update(rows)

    def pending_outbox(self):
        return [(k, dict(r)) for k, r in sorted(self.tables.get("__OUTBOX__", {}).items())
                if not r["sent"]]

    def mark_sent(self, key):
        self.f.step()
        self.tables["__OUTBOX__"][key]["sent"] = True


class Broker:
    def __init__(self, faults):
        self.events, self.f = [], faults

    def publish(self, topic, event):
        self.f.step()
        self.events.append((topic, dict(event)))
'''


def _code(kind, C, ent_var, ob, kv, extra):
    _, table, ent, fld, topic, fn = C
    k, r = kv
    ins = f'        tx.insert("{table}", {ent_var}["id"], {ent_var})'
    ex_row = f', "{extra}": {ent_var}["{extra}"]' if extra else ""
    ex_ev = f', "{extra}": {r}["{extra}"]' if extra else ""
    ex_dir = f', "{extra}": {ent_var}["{extra}"]' if extra else ""
    out = (f'        tx.insert("{ob}", {ent_var}["id"], {{"{fld}": {ent_var}["id"]{ex_row}, '
           f'"topic": "{topic}", "sent": False}})')
    pub_direct = f'    broker.publish("{topic}", {{"{fld}": {ent_var}["id"]{ex_dir}}})'
    relay_ok = ["def relay(db, broker):",
                f"    for {k}, {r} in db.pending_outbox():",
                f'        broker.publish({r}["topic"], {{"{fld}": {r}["{fld}"]{ex_ev}}})',
                f"        db.mark_sent({k})"]
    head = [f"def {fn}(db, broker, {ent_var}):", "    with db.transaction() as tx:", ins]
    if kind == "buggy":
        return "\n".join(head + [pub_direct, "", "", "def relay(db, broker):",
                                 "    pass  # отдельной доставки событий нет"])
    if kind == "good":
        return "\n".join(head + [out, "", ""] + relay_ok)
    if kind == "publish_in_tx":
        return "\n".join(head + ["    " + pub_direct, "", "", "def relay(db, broker):",
                                 "    pass  # событие уже опубликовано в транзакции"])
    if kind == "mark_first":
        return "\n".join(head + [out, "", "", "def relay(db, broker):",
                                 f"    for {k}, {r} in db.pending_outbox():",
                                 f"        db.mark_sent({k})",
                                 f'        broker.publish({r}["topic"], {{"{fld}": {r}["{fld}"]{ex_ev}}})'])
    if kind == "outbox_second_tx":
        return "\n".join(head + ["    with db.transaction() as tx:", out, "", ""] + relay_ok)
    raise ValueError(kind)


def _test(C, ids, extra):
    _, table, ent, fld, topic, fn, _x = C
    ent_expr = '{"id": i, ' + (f'"{extra}": 100 * i' if extra else '"note": "x"') + '}'

    return f"""
ids = {ids!r}
for at in range(1, 30):
    f = Faults(at)
    db, broker = DB(f), Broker(f)
    try:
        for i in ids:
            {fn}(db, broker, {ent_expr})
        relay(db, broker)
    except Crash:
        pass
    f.at = None            # перезапуск: relay отрабатывает без сбоев
    relay(db, broker)
    committed = set(db.tables.get({table!r}, {{}}))
    published = {{e[{fld!r}] for t, e in broker.events if t == {topic!r}}}
    assert published <= committed, f'точка {{at}}: событие о незакоммиченной записи'
    assert committed <= published, f'точка {{at}}: событие потеряно'
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    C7 = rng.choice(CONTEXTS)
    ctx, table, ent, fld, topic, fn, extra_f = C7
    C = C7[:6]
    ent_var = rng.choice([ent, "item", "record"])
    ob = rng.choice(["outbox", "outbox_events", "event_outbox"])
    kv = rng.choice([("key", "row"), ("k", "rec"), ("ref", "entry")])
    extra = extra_f if rng.random() < 0.5 else None
    prelude = PRELUDE.replace("__OUTBOX__", ob)
    ids = sorted(rng.sample(range(1, 90), rng.randint(1, 2)))
    buggy = _code("buggy", C, ent_var, ob, kv, extra)
    chosen = ["publish_in_tx", "mark_first", "outbox_second_tx"]
    opts, key = make_options(rng, ("Заменить код на:", _code("good", C, ent_var, ob, kv, extra)),
                             [("Заменить код на:", _code(d, C, ent_var, ob, kv, extra)) for d in chosen])
    test = _test(C + (None,), ids, extra)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(prelude + "\n\n" + buggy, test),
                    expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python",
                            program=py_harness(prelude + "\n\n" + o.code, test),
                            embeds_display_code=False, expect="pass" if o.id == key else "fail"))
    lead = rng.choice([
        f"Сервис «{ctx}»: `{fn}` сохраняет запись в таблицу `{table}` и публикует событие "
        f"`{topic}` в брокер.",
        f"В сервисе «{ctx}» обработчик `{fn}` пишет запись в `{table}`, а другие сервисы узнают о "
        f"ней из события `{topic}` в брокере.",
        f"«{ctx.capitalize()}»: после записи в `{table}` обработчик `{fn}` должен оповестить "
        f"подписчиков событием `{topic}`."])
    stem = (f"{lead} Процесс может упасть в любой момент (после падения его перезапускают, "
            f"фоновая `relay` запускается снова). Интерфейсы: `db.transaction()` — атомарная "
            f"транзакция, коммит при выходе из блока; `tx.insert(table, key, row)`; "
            f"`db.pending_outbox()` — неотправленные строки таблицы `{ob}`; `db.mark_sent(key)` — "
            f"отдельная атомарная запись; `broker.publish(topic, event)`. Требование: после любого "
            f"падения и перезапуска для каждой закоммиченной записи опубликовано событие и нет "
            f"событий о незакоммиченных записях; дубли допустимы — подписчики дедуплицируют по "
            f"`{fld}`. Какая замена выполняет требование?")
    why = {"publish_in_tx": "публикация до коммита: падение на коммите оставляет событие о записи, "
                            "которой нет",
           "mark_first": "relay помечает строку отправленной до публикации: падение между ними "
                         "теряет событие навсегда",
           "outbox_second_tx": "outbox пишется второй транзакцией: падение между транзакциями "
                               "теряет событие"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Transactional outbox: запись и строка outbox коммитятся атомарно, "
                                "relay публикует и только потом помечает строку — при падении "
                                "между публикацией и пометкой событие уйдёт повторно (это "
                                "допустимо), но не потеряется. В исходном коде падение после "
                                "коммита до публикации теряет событие. Остальные варианты: "
                                + "; ".join(why[d] for d in chosen) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="dual_write",
                         params={"distractors": chosen, "ids": ids, "outbox_table": ob})
