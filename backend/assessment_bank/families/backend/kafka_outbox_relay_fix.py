"""backend.kafka.outbox_relay_fix — choose_fix: relay transactional outbox помечает строки отправленными до подтверждения.

Relay читает неотправленные строки outbox, вызывает `producer.send()` и сразу помечает строку отправленной.
`send()` асинхронный: результат доставки приходит позже (future / callback), и при отказе брокера сообщение
теряется, а строка уже помечена. Состав вариантов фиксирован:
  * верный — ждать результат `send(...).get(timeout)`, помечать строку только после успеха, при ошибке
    остановить цикл (строка останется неотправленной и уйдёт в следующем проходе);
  * idempotent_only — включить идемпотентный продюсер и acks=all, цикл без изменений: идемпотентность
    защищает от дублей при повторах, но не от потери, когда результат не проверяется;
  * flush_after_mark — цикл без изменений, перед commit вызвать `producer.flush()`: flush ждёт отправки, но
    ошибки доставки не поднимает, помеченные строки с неудачной доставкой потеряны;
  * acks_zero_get — ждать `.get()`, но у продюсера `acks=0`: подтверждения брокера нет, future успешен всегда.
Проверка исполнением: подменный пакет kafka с брокером, который отвергает часть сообщений; верный вариант
помечает ровно доставленные строки, остальные помечают потерянные.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.kafka.outbox_relay_fix"

# (контекст, топик, функция, таблица)
CONTEXTS = [("заказы", "order-events", "relay_outbox", "outbox"), ("платежи", "payment-events", "relay_payments", "outbox_payments"),
            ("уведомления", "notification-events", "flush_outbox", "pending_events"),
            ("бронирование", "booking-events", "publish_outbox", "outbox_messages"),
            ("склад", "stock-events", "drain_outbox", "event_outbox")]
BROKERS = ['"kafka:9092"', '["kafka-1:9092", "kafka-2:9092"]', '"broker:9092"']

PRELUDE = '''import sys, types

FAILING = set({failing!r})      # сообщения, которые брокер отвергает (ключи строк outbox)
DELIVERED = []


class KafkaError(Exception):
    pass


class _Future:
    def __init__(self, ok, err):
        self.ok, self.err, self._cb, self._eb = ok, err, [], []

    def get(self, timeout=None):
        if not self.ok:
            raise self.err
        return None

    def add_callback(self, f, *a, **k):
        if self.ok:
            f(None, *a, **k)
        return self

    def add_errback(self, f, *a, **k):
        if not self.ok:
            f(self.err, *a, **k)
        return self


class KafkaProducer:
    def __init__(self, **config):
        self.config = config

    def send(self, topic, value=None, key=None, **kw):
        if self.config.get("acks", 1) == 0:   # без подтверждения брокера клиент считает отправку успешной
            if key not in FAILING:
                DELIVERED.append(key)
            return _Future(True, None)
        if key in FAILING:
            return _Future(False, KafkaError("NotLeaderForPartition"))
        DELIVERED.append(key)
        return _Future(True, None)

    def flush(self, timeout=None):
        pass


_kafka = types.ModuleType("kafka")
_kafka.KafkaProducer = KafkaProducer
_errors = types.ModuleType("kafka.errors")
_errors.KafkaError = KafkaError
_kafka.errors = _errors
sys.modules["kafka"], sys.modules["kafka.errors"] = _kafka, _errors


class _Row:
    def __init__(self, id, aggregate_id, payload):
        self.id, self.aggregate_id, self.payload = id, aggregate_id, payload


class FakeDb:
    def __init__(self, rows):
        self.rows, self.sent, self.committed = rows, set(), False

    def fetch_unsent(self, limit):
        return [r for r in self.rows if r.id not in self.sent][:limit]

    def mark_sent(self, row_id):
        self.sent.add(row_id)

    def commit(self):
        self.committed = True
'''

TEST = '''
db = FakeDb([_Row(i, f"{prefix}-{{i}}", {{"n": i}}) for i in range(1, {n_rows} + 1)])
try:
    {fn}(db)
except Exception:
    pass
delivered = {{int(k.split("-")[1]) for k in DELIVERED}}
lost_marked = db.sent - delivered           # помечены отправленными, но брокер их не принял
print("RESULT: PASS" if not lost_marked and db.sent == delivered else "RESULT: FAIL")
'''


def _rename(src: str, row: str, rows: str, batch_name: str) -> str:
    import re
    src = re.sub(r"\brows\b", rows, src)
    src = re.sub(r"\brow\b", row, src)
    return re.sub(r"\bbatch_size\b", batch_name, src)


def _code(ctx, variant: str, brokers: str, batch: int, timeout: int) -> str:
    _c, topic, fn, _table = ctx
    cfg = {"buggy": f"producer = KafkaProducer(bootstrap_servers={brokers}, acks=\"all\")",
           "correct": f"producer = KafkaProducer(bootstrap_servers={brokers}, acks=\"all\")",
           "idempotent_only": f"producer = KafkaProducer(\n    bootstrap_servers={brokers}, acks=\"all\", "
                              f"enable_idempotence=True, retries=5\n)",
           "flush_after_mark": f"producer = KafkaProducer(bootstrap_servers={brokers}, acks=\"all\")",
           "acks_zero_get": f"producer = KafkaProducer(bootstrap_servers={brokers}, acks=0)"}[variant]
    head = ["from kafka import KafkaProducer", "from kafka.errors import KafkaError", "", cfg, "", "",
            f"def {fn}(db, batch_size={batch}):", "    rows = db.fetch_unsent(batch_size)", "    for row in rows:"]
    if variant in ("buggy", "idempotent_only", "flush_after_mark"):
        body = [f'        producer.send("{topic}", key=row.aggregate_id, value=row.payload)',
                "        db.mark_sent(row.id)"]
        tail = (["    producer.flush()"] if variant == "flush_after_mark" else []) + ["    db.commit()"]
    else:
        body = ["        try:",
                f'            producer.send("{topic}", key=row.aggregate_id, value=row.payload).get(timeout={timeout})',
                "        except KafkaError:",
                "            break  # строка останется неотправленной — уйдёт в следующем проходе",
                "        db.mark_sent(row.id)"]
        tail = ["    db.commit()"]
    return "\n".join(head + body + tail) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    c, topic, fn, table = ctx
    brokers = rng.choice(BROKERS)
    batch = rng.choice([50, 100, 200, 500])
    timeout = rng.choice([5, 10, 30])
    n_rows = rng.randint(6, 12)
    prefix = rng.choice(["ORD", "PAY", "NTF", "BK", "SKU"])
    failing = sorted(rng.sample(range(2, n_rows + 1), rng.randint(1, 3)))
    failing_keys = [f"{prefix}-{i}" for i in failing]
    row, rows = rng.choice([("row", "rows"), ("item", "items"), ("rec", "pending"), ("msg", "batch"),
                            ("entry", "entries")])
    batch_name = rng.choice(["batch_size", "limit", "max_rows", "chunk"])
    buggy = _rename(_code(ctx, "buggy", brokers, batch, timeout), row, rows, batch_name)
    names = ["correct", "idempotent_only", "flush_after_mark", "acks_zero_get"]
    srcs = {n: _rename(_code(ctx, n, brokers, batch, timeout), row, rows, batch_name) for n in names}
    labels = {"correct": "Ждать результат send(...).get(), помечать строку только после успеха",
              "idempotent_only": "Включить enable_idempotence=True и retries, цикл без изменений",
              "flush_after_mark": "Цикл без изменений, перед commit вызвать producer.flush()",
              "acks_zero_get": "Ждать результат send(...).get(), у продюсера acks=0"}
    opts, key = make_options(rng, (labels["correct"], srcs["correct"]), [(labels[n], srcs[n]) for n in names[1:]])
    by_text = {o.text: o.id for o in opts}
    prelude = PRELUDE.format(failing=failing_keys)
    test = TEST.replace("{prefix}", prefix).format(n_rows=n_rows, fn=fn)
    checks = [Check(name="original_fails", runner="python", program=prelude + buggy + test, expect="fail")]
    for n in names:
        checks.append(Check(name=f"option:{by_text[labels[n]]}", runner="python", program=prelude + srcs[n] + test,
                            expect="pass" if n == "correct" else "fail", embeds_display_code=False))
    stem = (f"Kafka, {c}: события пишутся в таблицу `{table}` в одной транзакции с бизнес-данными, а relay "
            f"`{fn}` раз в секунду отправляет их в топик `{topic}` и помечает отправленными. При кратковременной "
            f"недоступности брокера часть событий пропадает: в `{table}` они отмечены как отправленные, "
            f"а в топике их нет. Какой вариант устраняет потерю?")
    why = ("`send()` асинхронный: он кладёт сообщение в буфер и возвращает future, а ошибка доставки приходит позже. "
           "Помечать строку можно только после подтверждённой доставки — `get()` поднимает исключение при отказе, "
           "и строка остаётся в outbox до следующего прохода. Идемпотентный продюсер защищает от дублей при "
           "повторах, но результат по-прежнему не проверяется; `flush()` ждёт отправки, но ошибок не поднимает; "
           "при `acks=0` подтверждения брокера нет, и `get()` всегда успешен.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak, context=c,
                         verification="execution", checks=checks, defect_type="unawaited_send",
                         display_code_note="Пакет kafka подменяется моделью брокера, отвергающего часть сообщений; "
                                           "показанный код исполняется дословно.",
                         params={"failing": failing, "n_rows": n_rows})
