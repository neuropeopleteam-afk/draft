"""data_eng.stream.delivery_semantics_mcq — mcq_concept: гарантии доставки Kafka → БД по коду потребителя.

Потребитель зачисляет суммы из топика на баланс в БД. Пять вариантов кода (подтипы):
* after_batch — транзакция на сообщение, `consumer.commit()` после пачки → после падения повтор первых k (at-least-once);
* before_processing — `commit()` сразу после poll → хвост пачки потерян (at-most-once);
* db_offset_seek — offset сохраняется в той же транзакции, при старте `seek` на него → ровно один раз по эффекту;
* db_offset_noseek — offset сохраняется в той же транзакции, но при старте не используется: чтение идёт с
  зафиксированного в Kafka offset → повтор первых k (ловушка);
* dedup_processed — таблица обработанных ключей в той же транзакции → повторы доставки без повторного эффекта.
Процесс падает сразу после фиксации k-й транзакции; после перезапуска обрабатывает всё до конца. Дистракторы —
фиксированный состав: ровно один раз, повтор первых k, потеря хвоста, повтор только сообщения в момент падения.
Семантика — документация Apache Kafka (Consumer: offsets and consumer position, «storing offsets outside Kafka»).
Ключ — исполнение показанного кода с заглушками потребителя и БД (транзакция применяется только при выходе без
исключения) и внедрённым падением в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.stream.delivery_semantics_mcq"

CTX = [("зачисление платежей на счёт", "payments", "pay"), ("начисление бонусных баллов", "bonus-events", "bns"),
       ("пополнение кошелька", "wallet-topups", "top"), ("учёт поступлений на склад", "stock-in", "rcv"),
       ("начисление выплат курьерам", "courier-payouts", "pyt"), ("учёт показаний счётчиков", "meter-readings", "mtr")]

CODE = {
    "after_batch": ["def consume(consumer, db):",
                    "    for msg in consumer.poll():",
                    "        with db.transaction() as tx:",
                    "            tx.add_balance(msg.value)",
                    "    consumer.commit()"],
    "before_processing": ["def consume(consumer, db):",
                          "    batch = consumer.poll()",
                          "    consumer.commit()",
                          "    for msg in batch:",
                          "        with db.transaction() as tx:",
                          "            tx.add_balance(msg.value)"],
    "db_offset_seek": ["def consume(consumer, db):",
                       "    consumer.seek(db.saved_offset())",
                       "    for msg in consumer.poll():",
                       "        with db.transaction() as tx:",
                       "            tx.add_balance(msg.value)",
                       "            tx.save_offset(msg.offset + 1)",
                       "    consumer.commit()"],
    "db_offset_noseek": ["def consume(consumer, db):",
                         "    for msg in consumer.poll():",
                         "        with db.transaction() as tx:",
                         "            tx.add_balance(msg.value)",
                         "            tx.save_offset(msg.offset + 1)  # offset хранится вместе с данными",
                         "    consumer.commit()"],
    "dedup_processed": ["def consume(consumer, db):",
                        "    for msg in consumer.poll():",
                        "        with db.transaction() as tx:",
                        "            if tx.mark_processed(msg.key):  # False, если ключ уже записан",
                        "                tx.add_balance(msg.value)",
                        "    consumer.commit()"],
}
EFFECT = {"after_batch": "dup", "before_processing": "loss", "db_offset_seek": "exact",
          "db_offset_noseek": "dup", "dedup_processed": "exact"}

STUBS = '''from collections import namedtuple

Msg = namedtuple("Msg", "offset key value")
LOG = [Msg(*m) for m in MESSAGES]


class Crash(Exception):
    pass


class DB:
    def __init__(self, balance):
        self.balance, self.offset, self.keys, self.commits, self.crash_after = balance, 0, set(), 0, None

    def saved_offset(self):
        return self.offset

    def transaction(self):
        return Tx(self)


class Tx:
    def __init__(self, db):
        self.db, self.delta, self.off, self.new_keys = db, 0, None, set()

    def __enter__(self):
        if self.db.crash_after is not None and self.db.commits >= self.db.crash_after:
            raise Crash()
        return self

    def add_balance(self, v):
        self.delta += v

    def save_offset(self, o):
        self.off = o

    def mark_processed(self, key):
        if key in self.db.keys or key in self.new_keys:
            return False
        self.new_keys.add(key)
        return True

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:                       # фиксация только без исключения
            self.db.balance += self.delta
            self.db.keys |= self.new_keys
            if self.off is not None:
                self.db.offset = self.off
            self.db.commits += 1
        return False


class Consumer:
    committed = START                              # offset группы в Kafka

    def __init__(self):
        self.pos = Consumer.committed

    def seek(self, offset):
        self.pos = offset

    def poll(self):
        batch = [m for m in LOG if m.offset >= self.pos]
        self.pos = LOG[-1].offset + 1
        return batch

    def commit(self):
        Consumer.committed = self.pos
'''

RUN = '''

db = DB(BALANCE)
db.offset = START
db.crash_after = CRASH_AFTER
try:
    consume(Consumer(), db)
except Crash:
    pass
db.crash_after = None
consume(Consumer(), db)                            # перезапуск
print(db.balance)
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, topic, kp = rng.choice(CTX)
    sub = rng.choice(sorted(CODE))
    n = rng.randint(4, 6)
    start = rng.randint(100, 9000)
    vals = [rng.choice([100, 150, 200, 250, 300, 400, 500, 700, 1000]) for _ in range(n)]
    msgs = [(start + i, f"{kp}-{rng.randint(1000, 9999)}-{i}", v) for i, v in enumerate(vals)]
    k = rng.randint(2, n - 1)
    b0 = rng.choice([0, 1000, 2500, 5000])
    exact = b0 + sum(vals)
    out = {"exact": exact, "dup": exact + sum(vals[:k]), "loss": b0 + sum(vals[:k]), "one": exact + vals[k - 1]}
    right = out[EFFECT[sub]]
    code = "\n".join(CODE[sub])
    texts = {key: f"{v}" for key, v in out.items()}
    order = ["exact", "dup", "loss", "one"]
    rk = EFFECT[sub]
    opts, key = make_options(rng, (texts[rk], None), [(texts[x], None) for x in order if x != rk])
    tbl = "\n".join(f"  offset {o}, key {kk}, value {v}" for o, kk, v in msgs)
    stem = (f"Сервис «{ctx}» читает топик `{topic}` (одна партиция) и прибавляет value каждого сообщения к "
            f"балансу в БД. Зафиксированный offset группы в Kafka — {start}, в БД сохранён тот же offset, баланс "
            f"{b0}. В топике {n} сообщений:\n{tbl}\nКлюч key уникален для каждого события. Процесс упал сразу после "
            f"фиксации {k}-й транзакции БД; после перезапуска тот же код обработал топик до конца. Каким будет "
            "баланс?")
    expl = {"after_batch": f"Offset фиксируется в Kafka только после пачки: после падения чтение снова с {start}, "
                           f"первые {k} сообщений зачислены повторно.",
            "before_processing": "Offset зафиксирован сразу после poll: после перезапуска чтение идёт после пачки, "
                                 f"сообщения после {k}-го потеряны.",
            "db_offset_seek": "Offset хранится в той же транзакции, что и баланс, и при старте потребитель "
                              "переходит на него: каждая сумма применена ровно один раз.",
            "db_offset_noseek": "Offset сохраняется в БД, но при старте не используется: чтение идёт с "
                                f"зафиксированного в Kafka offset {start}, первые {k} сообщений зачислены повторно.",
            "dedup_processed": "Повторная доставка будет, но ключи уже записаны в той же транзакции: повторного "
                               "зачисления нет."}[sub] + f" Итог: {right}."
    prog = (f"MESSAGES = {msgs!r}\nSTART, BALANCE, CRASH_AFTER = {start}, {b0}, {k}\n\n" + STUBS + "\n\n" + code + RUN)
    checks = [Check(name="consumer_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=str(right))]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="python",
                         display_code_note="Показанный код исполняется дословно с заглушками потребителя Kafka и "
                                           "БД; падение внедряется после k-й транзакции",
                         params={"subtype": sub, "k": k, "n": n})
