"""backend.kafka.offset_commit_mcq — mcq_concept: ручной commitSync после пачки, падение посреди обработки.

Потребитель с `enable.auto.commit=false` получает пачку сообщений из одной партиции, обрабатывает по одному и
фиксирует offset один раз после всей пачки. Процесс падает, обработав k из N. Вопрос: с какого offset начнётся
чтение после перезапуска и сколько сообщений будут обработаны повторно. Ловушки: «коммит после каждого
сообщения» (чтение с места падения, дублей нет), «повторно вся пачка» (N вместо k), «offset зафиксирован при
poll()» (чтение после пачки, потеря k..N). Один подтип; варьируются контекст, offset, размер пачки и место
падения. Ключ проверяется исполнением модели потребителя (poll → обработка → commitSync, падение, перезапуск).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.kafka.offset_commit_mcq"

CONTEXTS = [("платежи", "payments", "billing"), ("заказы", "orders", "fulfillment"),
            ("клики", "clicks", "analytics"), ("уведомления", "notifications", "sender"),
            ("события доставки", "delivery-events", "tracking")]

SIM = '''COMMITTED, N, K = {committed}, {n}, {k}

committed = COMMITTED          # последний зафиксированный offset (следующий к чтению)
processed = []                 # что успели обработать (побочные эффекты уже случились)


def run(start, crash_after):
    """Один запуск потребителя: poll() пачки от start, обработка по одному, commitSync() после всей пачки."""
    global committed
    batch = list(range(start, start + N))
    done = 0
    for off in batch:
        processed.append(off)
        done += 1
        if crash_after is not None and done == crash_after:
            return False  # процесс упал до commitSync()
    committed = batch[-1] + 1
    return True


run(committed, K)              # первый запуск: падение после K сообщений
restart_from = committed       # после перезапуска чтение идёт с последнего зафиксированного offset
run(restart_from, None)
dup = sum(1 for off in set(processed) if processed.count(off) > 1)
OPTIONS = {options!r}
print(next(k for k, v in OPTIONS.items() if v == (restart_from, dup)))
'''


def _text(pair: tuple[int, int]) -> str:
    start, dup = pair
    if dup == 0:
        return f"Чтение с offset {start}; повторно не обработается ни одно сообщение"
    word = "сообщение" if dup % 10 == 1 and dup % 100 != 11 else (
        "сообщения" if 2 <= dup % 10 <= 4 and not 12 <= dup % 100 <= 14 else "сообщений")
    return f"Чтение с offset {start}; повторно обработаются {dup} {word}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, topic, group = rng.choice(CONTEXTS)
    committed = rng.choice([100, 250, 500, 1200, 2048, 4000, 7300]) + rng.randint(0, 99)
    n = rng.choice([10, 20, 25, 40, 50, 100])
    k = rng.randint(2, n - 2)
    partition = rng.randint(0, 11)
    pairs = [(committed, k),                 # верно: с зафиксированного offset, повторно k
             (committed + k, 0),             # «коммит после каждого сообщения»
             (committed, n),                 # «повторно вся пачка»
             (committed + n, 0)]             # «offset зафиксирован при poll()» — потеря сообщений
    opts, key = make_options(rng, (_text(pairs[0]), None), [(_text(p), None) for p in pairs[1:]])
    mapping = {o.id: pairs[[_text(p) for p in pairs].index(o.text)] for o in opts}
    program = SIM.format(committed=committed, n=n, k=k, options=mapping)
    checks = [Check(name="simulate", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=key, embeds_display_code=False)]
    stem = (f"Kafka, {ctx}: потребитель группы `{group}` читает партицию {partition} топика `{topic}` с "
            f"`enable.auto.commit=false`. Последний зафиксированный offset — {committed}. `poll()` вернул {n} "
            f"сообщений (offset {committed}–{committed + n - 1}); потребитель обрабатывает их по одному "
            f"(обработка — запись в базу) и после всей пачки вызывает `commitSync()`. Обработав {k} сообщений, "
            f"процесс упал. Что произойдёт после перезапуска потребителя?")
    why = (f"Коммит не состоялся, поэтому зафиксированным остаётся offset {committed}: чтение начнётся с него, "
           f"и первые {k} сообщений (offset {committed}–{committed + k - 1}), уже записанные в базу, будут "
           f"обработаны второй раз — это гарантия at-least-once, обработчик должен быть идемпотентным. "
           f"Коммита «после каждого сообщения» не было, а poll() сам по себе offset не фиксирует.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показанного кода нет; исполняется модель потребителя: poll пачки, "
                                           "обработка по одному, commitSync после пачки, падение и перезапуск.",
                         params={"committed": committed, "n": n, "k": k})
