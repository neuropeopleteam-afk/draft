"""backend.kafka.partition_key_bug — find_bug: ключ сообщения по статусу вместо идентификатора сущности.

Продюсер публикует события жизненного цикла заказа (created → paid → shipped …) в топик с несколькими
партициями. Kafka гарантирует порядок только внутри партиции, а партиция выбирается по ключу
(murmur2 от байтов ключа, как в Java-клиенте и kafka-python). Дефект: `key=status` — события одного заказа
расходятся по разным партициям, и потребитель видит `shipped` раньше `paid`. Исправление — ключ по
идентификатору заказа в той же строке. Один подтип; варьируются контекст, статусы, число партиций,
настройки продюсера (acks, linger_ms, retries — строки-ловушки), имена. Проверка исполнением: подменный
`kafka.KafkaProducer` считает партицию алгоритмом murmur2 Kafka; дефектный код раскладывает события одного
заказа по нескольким партициям, исправленный — ровно по одной.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.kafka.partition_key_bug"

# (контекст, сущность, id-поле, топик, функция, статусы по порядку)
CONTEXTS = [("интернет-магазин", "заказа", "одного и того же заказа", "order_id", "order-events", "publish_order_event",
             ["created", "paid", "packed", "shipped", "delivered"]),
            ("платёжный сервис", "платежа", "одного и того же платежа", "payment_id", "payment-events", "publish_payment_event",
             ["initiated", "authorized", "captured", "settled"]),
            ("служба доставки", "посылки", "одной и той же посылки", "parcel_id", "parcel-events", "emit_parcel_event",
             ["accepted", "in_transit", "arrived", "handed_over"]),
            ("поддержка", "обращения", "одного и того же обращения", "ticket_id", "ticket-events", "publish_ticket_event",
             ["opened", "assigned", "answered", "closed"]),
            ("бронирование", "брони", "одной и той же брони", "booking_id", "booking-events", "send_booking_event",
             ["requested", "confirmed", "checked_in", "completed"])]

MURMUR_SRC = '''def murmur2(data: bytes) -> int:
    """murmur2 как в org.apache.kafka.common.utils.Utils (и kafka-python); результат — беззнаковый 32-битный."""
    length, m, r = len(data), 0x5BD1E995, 24
    h = (0x9747B28C ^ length) & 0xFFFFFFFF
    for i in range(length // 4):
        k = int.from_bytes(data[4 * i:4 * i + 4], "little")
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
    rem = length % 4
    base = length - rem
    if rem == 3:
        h ^= data[base + 2] << 16
    if rem >= 2:
        h ^= data[base + 1] << 8
    if rem >= 1:
        h ^= data[base]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h


def partition_for(key: bytes, n_partitions: int) -> int:
    return (murmur2(key) & 0x7FFFFFFF) % n_partitions
'''
_ns: dict = {}
exec(MURMUR_SRC, _ns)  # noqa: S102 — наш код модели
_partition_for = _ns["partition_for"]

PRELUDE = '''import sys, types

N_PARTITIONS = {n_partitions}
SENT = []

''' + MURMUR_SRC + '''

class _Future:
    def get(self, timeout=None):
        return None

    def add_callback(self, *a, **k):
        return self

    def add_errback(self, *a, **k):
        return self


class KafkaProducer:
    def __init__(self, **config):
        self.config = config

    def send(self, topic, value=None, key=None, headers=None, partition=None, timestamp_ms=None):
        ks = self.config.get("key_serializer")
        kb = ks(key) if (ks and key is not None) else key
        if partition is None:
            partition = partition_for(kb, N_PARTITIONS) if kb is not None else 0
        SENT.append((topic, partition, key, value))
        return _Future()

    def flush(self, timeout=None):
        pass


_kafka = types.ModuleType("kafka")
_kafka.KafkaProducer = KafkaProducer
sys.modules["kafka"] = _kafka
'''

TEST = '''
IDS = {ids!r}
STATUSES = {statuses!r}
for _id in IDS:
    for _st in STATUSES:
        {fn}(_id, _st, {{"attempt": 1}})
by_id = {{}}
for _topic, _part, _key, _val in SENT:
    by_id.setdefault(_val[{id_field!r}], set()).add(_part)
ok = len(SENT) == len(IDS) * len(STATUSES) and all(len(parts) == 1 for parts in by_id.values())
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''


def _code(ctx, buggy: bool, extras: list[str], ser_first: bool, var: str, payload_name: str) -> str:
    _c, _ent, _same, id_field, topic, fn, _statuses = ctx
    prod = ["producer = KafkaProducer(", '    bootstrap_servers="kafka:9092",']
    ser = ['    key_serializer=lambda k: k.encode("utf-8"),',
           '    value_serializer=lambda v: json.dumps(v).encode("utf-8"),']
    prod += (ser + extras) if ser_first else (extras + ser)
    prod.append(")")
    key = f"key={'status' if buggy else id_field},"
    lines = ["import json", "", "from kafka import KafkaProducer", "", ""] + prod + ["", "",
             f"def {fn}({id_field}: str, status: str, {payload_name}: dict) -> None:",
             f'    {var} = {{"{id_field}": {id_field}, "status": status, **{payload_name}}}',
             "    producer.send(",
             f'        "{topic}",',
             f"        {key}",
             f"        value={var},",
             "    )"]
    return "\n".join(lines) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    c, ent, same, id_field, topic, fn, statuses = ctx
    statuses = statuses[: rng.randint(3, len(statuses))]
    extras_pool = ['    acks="all",', f"    linger_ms={rng.choice([5, 10, 20, 50])},",
                   f"    retries={rng.choice([3, 5, 10])},", '    compression_type="gzip",']
    extras = rng.sample(extras_pool, rng.randint(1, 3))
    ser_first = rng.random() < 0.5
    var = rng.choice(["event", "msg", "record", "payload"])
    payload_name = "extra" if var == "payload" else rng.choice(["payload", "data", "details"])
    prefix = rng.choice(["ORD", "PAY", "P", "TCK", "BK", "A"])
    ids = [f"{prefix}-{rng.randint(1000, 99999)}" for _ in range(rng.randint(3, 5))]
    # число партиций: при ключе по статусу события одного объекта должны разойтись хотя бы по двум партициям
    for n_partitions in rng.sample([4, 6, 8, 12, 16], 5):
        parts = {_partition_for(s.encode(), n_partitions) for s in statuses}
        if len(parts) >= 2:
            break
    else:
        raise AssertionError("статусы попали в одну партицию при всех вариантах")
    buggy = _code(ctx, True, extras, ser_first, var, payload_name)
    fixed = _code(ctx, False, extras, ser_first, var, payload_name)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    prelude = PRELUDE.format(n_partitions=n_partitions)
    test = TEST.format(ids=ids, statuses=statuses, fn=fn, id_field=id_field)
    checks = [Check(name="buggy_fails", runner="python", program=prelude + buggy + test, expect="fail"),
              Check(name="fixed_passes", runner="python", program=prelude + fixed + test, expect="pass",
                    embeds_display_code=False)]
    chain = " → ".join(statuses)
    stem = (f"Kafka, {c}: события {ent} публикуются в топик `{topic}` ({n_partitions} партиций) и должны "
            f"обрабатываться в порядке {chain}. Потребитель (одна группа, по экземпляру на партицию) иногда получает "
            f"`{statuses[-1]}` раньше `{statuses[1]}` для {same}. Укажите номер строки с ошибкой.")
    why = (f"Строка {key}: ключ сообщения — статус, а партиция выбирается хэшем ключа (murmur2), поэтому события "
           f"одного {ent} попадают в разные партиции, и порядок между ними Kafka не гарантирует. Ключом должен быть "
           f"`{id_field}`: все события {ent} — в одной партиции, порядок внутри неё сохраняется.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=c,
                         verification="execution", checks=checks, defect_type="wrong_partition_key",
                         display_code_note="Пакет kafka подменяется моделью: партиция считается murmur2 от байтов "
                                           "ключа, как в Java-клиенте и kafka-python; показанный код исполняется дословно.",
                         params={"fixed_code": fixed, "n_partitions": n_partitions})
