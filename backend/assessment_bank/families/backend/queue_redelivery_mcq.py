"""backend.queue.redelivery_mcq — mcq_concept: повторная доставка сообщений из очереди.

Три сценария доставки «как минимум один раз»:
* visibility — обработка дольше visibility timeout: сообщение снова выдаётся другим воркерам;
* crash — падение потребителя до/после ack при ручном подтверждении (prefetch = 1);
* nested — внутренние повторы обработчика × maxReceiveCount очереди до переноса в DLQ.
Ключ проверяется исполнением: программа моделирует брокер по шагам (события доставки,
подтверждения, падения) и печатает букву варианта, совпавшего с результатом моделирования.
"""
from __future__ import annotations

import math

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.queue.redelivery_mcq"

CONTEXTS = [("начисление бонусов", "начислений бонусов", "начислить бонус"),
            ("отправка писем", "отправленных писем", "отправить письмо"),
            ("списание оплаты", "списаний", "списать оплату"),
            ("выпуск PDF-счетов", "сформированных счетов", "сформировать счёт"),
            ("push-уведомления", "отправленных уведомлений", "отправить уведомление")]


def _times(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} раз"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} раза"
    return f"{n} раз"


SIM = {
    "visibility": '''\
P, V = {P}, {V}
starts, t, acked = 0, 0, False
while not acked:
    starts += 1          # сообщение выдано воркеру, обработка началась в момент t
    next_visible = t + V
    if P < next_visible:  # первая обработка закончилась и подтвердила сообщение раньше
        acked = True
    t = next_visible
result = starts
''',
    "crash": '''\
N, K, MODE, POINT = {N}, {K}, {mode!r}, {point!r}
queue = list(range(1, N + 1))
effects, crashed = 0, False
while queue:
    msg = queue[0]
    if MODE == "ack_before":
        queue.pop(0)                       # подтверждено при получении
        if msg == K and not crashed:
            crashed = True                 # падение после ack, до эффекта
            continue
        effects += 1
    else:
        if msg == K and not crashed and POINT == "before_effect":
            crashed = True                 # падение до эффекта: сообщение не подтверждено
            continue
        effects += 1
        if msg == K and not crashed:
            crashed = True                 # падение после эффекта, до ack
            continue
        queue.pop(0)
result = effects
''',
    "nested": '''\
R, INNER = {R}, {r}
calls, receives, in_dlq = 0, 0, False
while not in_dlq:
    receives += 1
    for attempt in range(1 + INNER):
        calls += 1                         # каждая попытка падает: ошибка постоянная
    if receives >= R:
        in_dlq = True
result = calls
''',
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, effects_word, unit = rng.choice(CONTEXTS)
    kind = rng.choice(["visibility", "crash", "nested"])
    if kind == "visibility":
        V = rng.choice([10, 15, 20, 30])
        while True:
            P = rng.randint(V + 1, 4 * V + V // 2)
            if P % V:
                break
        ans = math.ceil(P / V)
        pool = [1, ans - 1, ans + 1, ans + 2, 2 * ans]
        vals = dict(P=P, V=V)
        stem = (f"Очередь с visibility timeout (как в SQS или Yandex Message Queue), сценарий: "
                f"{ctx}. Visibility timeout — {V} с; обработка одного сообщения занимает {P} с; "
                f"воркер подтверждает (удаляет) сообщение только после завершения обработки; "
                f"свободных воркеров достаточно. Сколько раз начнётся обработка одного и того же "
                f"сообщения к моменту первого подтверждения?")
        fmt = _times
        why = (f"Пока обработка идёт, сообщение каждые {V} с снова становится видимым и уходит "
               f"другому воркеру: старты в 0, {V}, … с, пока время меньше {P} с — всего "
               f"⌈{P}/{V}⌉ = {ans}. Нужно увеличить visibility timeout или продлевать его во "
               f"время обработки и делать обработчик идемпотентным.")
    elif kind == "crash":
        N = rng.randint(5, 12)
        K = rng.randint(2, N - 1)
        mode, point = rng.choice([("ack_after", "after_effect"), ("ack_after", "before_effect"),
                                  ("ack_before", "after_ack")])
        ans = {"after_effect": N + 1, "before_effect": N, "after_ack": N - 1}[point]
        pool = [N - 1, N, N + 1, N + K, 2 * N]
        vals = dict(N=N, K=K, mode=mode, point=point)
        ack = ("подтверждает сообщение (ack) после выполнения действия" if mode == "ack_after"
               else "подтверждает сообщение (ack) сразу при получении, затем выполняет действие")
        where = {"after_effect": "после выполнения действия, но до ack",
                 "before_effect": "до выполнения действия",
                 "after_ack": "после ack, но до выполнения действия"}[point]
        stem = (f"RabbitMQ, ручное подтверждение, prefetch = 1, сценарий: {ctx}. В очереди {N} "
                f"сообщений; на каждое выполняется одно действие — {unit}. Потребитель {ack}. "
                f"На {K}-м сообщении процесс падает {where}; после рестарта брокер заново "
                f"доставляет неподтверждённые сообщения, обработчик не идемпотентен. Сколько "
                f"всего будет {effects_word}?")
        fmt = lambda x: f"{x} шт."
        why = {"after_effect": f"Действие по {K}-му сообщению выполнено, но ack не дошёл — после "
                               f"рестарта оно повторится: {N} + 1. Нужна идемпотентность по id сообщения.",
               "before_effect": f"Сообщение {K} не подтверждено и будет доставлено снова; действие "
                                f"по нему ещё не выполнялось — итого ровно {N}.",
               "after_ack": f"Сообщение {K} уже подтверждено и не вернётся, действие потеряно: "
                            f"{N} − 1. Подтверждать нужно после действия."}[point]
    else:
        R = rng.randint(2, 5)
        r = rng.randint(1, 4)
        ans = R * (1 + r)
        pool = [R, R + r, R * r, (R + 1) * (1 + r), R * (1 + r) + 1]
        vals = dict(R=R, r=r)
        stem = (f"Очередь с DLQ (как в SQS), сценарий: {ctx}. maxReceiveCount = {R}: после {R} "
                f"неудачных получений сообщение переносится в очередь недоставленных сообщений. "
                f"Обработчик при ошибке сам повторяет вызов внешнего сервиса (повторов внутри одной "
                f"доставки: {r}) и затем пробрасывает исключение. Сообщение содержит некорректные данные и падает всегда. "
                f"Сколько раз будет вызван внешний сервис до переноса сообщения в DLQ?")
        fmt = _times
        why = (f"Получений {R}, в каждом — первый вызов и повторов: {r}, то есть вызовов за одну доставку: {1 + r}; {R} × {1 + r} = {ans}. "
               f"Вложенные повторы перемножаются; ошибки данных не стоит повторять вовсе — "
               f"такое сообщение сразу отправляют в DLQ.")
    distractors = []
    for x in pool:
        if x != ans and x >= 0 and x not in distractors:
            distractors.append(x)
    picked = rng.sample(distractors, 3)
    opts, key = make_options(rng, (fmt(ans), None), [(fmt(x), None) for x in picked])
    sim = SIM[kind].format(**vals)
    mapping = {o.id: o.text for o in opts}
    program = (sim + f"\nOPTIONS = {mapping!r}\n"
               f"print(next(k for k, text in OPTIONS.items() if text == FMT(result)))\n")
    fmt_src = ("def FMT(n):\n    if n % 10 == 1 and n % 100 != 11:\n        return f'{n} раз'\n"
               "    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):\n"
               "        return f'{n} раза'\n    return f'{n} раз'\n" if fmt is _times
               else "def FMT(n):\n    return f'{n} шт.'\n")
    program = fmt_src + "\n" + program
    checks = [Check(name="simulate", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=key, embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показанного кода нет; исполняется пошаговая модель "
                                           "брокера, печатающая букву верного варианта.",
                         params={"kind": kind, **vals, "answer": ans})
