"""backend.reliability.retry_deadline_ob3 — открытая книга: повторы с экспоненциальной задержкой и общим дедлайном.

Требования к call_with_retry: не больше max_attempts вызовов; повторяется только
TransientError; задержка перед k-м повтором base · 2^(k−1); повтор не начинается, если
ожидание закончится не раньше дедлайна; каждый вызов получает timeout = min(per_try,
остаток бюджета). Подтипы дефекта: попытки «на единицу больше», повтор PermanentError,
проверка дедлайна без учёта задержки, timeout без ограничения остатком бюджета.
Время — подменяемые часы; вызов, который дольше timeout, завершается TransientError через
timeout секунд. Эталон — модель на Python; ключи шагов 1–2 проверяются исполнением.
"""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.reliability.retry_deadline_ob3"

HEAD = '''class TransientError(Exception):
    """Временная ошибка: 503, разрыв соединения, таймаут."""


class PermanentError(Exception):
    """Постоянная ошибка: 400, 404, ошибка валидации."""


'''

LINES = {
    "sig": "def call_with_retry(op, clock, sleep, deadline, base, max_attempts, per_try):",
    "start": "    start = clock()",
    "attempt": "    attempt = 1",
    "loop": "    while True:",
    "timeout": "        timeout = min(per_try, start + deadline - clock())",
    "try": "        try:",
    "call": "            return op(timeout)",
    "except": "        except TransientError:",
    "delay": "            delay = base * 2 ** (attempt - 1)",
    "check": "            if attempt >= max_attempts or clock() + delay >= start + deadline:",
    "raise": "                raise",
    "inc": "            attempt += 1",
    "sleep": "            sleep(delay)",
}
ORDER = ["sig", "start", "attempt", "loop", "timeout", "try", "call", "except", "delay", "check",
         "raise", "inc", "sleep"]
VARIANT_LINES = {
    "good": {},
    "off_by_one": {"check": "            if attempt > max_attempts or clock() + delay >= start + deadline:"},
    "retries_permanent": {"except": "        except Exception:"},
    "ignores_delay": {"check": "            if attempt >= max_attempts or clock() >= start + deadline:"},
    "uncapped_timeout": {"timeout": "        timeout = per_try"},
    "check_after_sleep": {"check": "            if attempt >= max_attempts:",
                          "sleep": "            sleep(delay)\n"
                                   "            if clock() >= start + deadline:\n"
                                   "                raise"},
}
SUBTYPES = ["off_by_one", "retries_permanent", "ignores_delay", "uncapped_timeout"]


def _func(kind: str) -> str:
    over = VARIANT_LINES[kind]
    return "\n".join(over.get(k, LINES[k]) for k in ORDER)


def _model(kind: str, sc: list[tuple[int, int]], p: dict) -> str:
    """Независимая пошаговая модель политики повторов; вывод как у программы проверки."""
    now, calls = 0, 0
    D, B, M, P = p["deadline"], p["base"], p["max_attempts"], p["per_try"]
    start, attempt = now, 1
    while True:
        timeout = P if kind == "uncapped_timeout" else min(P, start + D - now)
        code, dur = sc[calls]
        calls += 1
        if dur > timeout:
            now += max(timeout, 0)
            err = "TransientError"
        else:
            now += dur
            err = {503: "TransientError", 400: "PermanentError", 200: None}[code]
        if err is None:
            return f"calls={calls} t={now} ok"
        if err == "PermanentError" and kind != "retries_permanent":
            return f"calls={calls} t={now} PermanentError"
        delay = B * 2 ** (attempt - 1)
        limit_hit = attempt > M if kind == "off_by_one" else attempt >= M
        if kind in ("ignores_delay", "check_after_sleep"):
            late = now >= start + D
        else:
            late = now + delay >= start + D
        if kind == "check_after_sleep":
            if limit_hit:
                return f"calls={calls} t={now} {err}"
            attempt += 1
            now += delay
            if now >= start + D:
                return f"calls={calls} t={now} {err}"
            continue
        if limit_hit or late:
            return f"calls={calls} t={now} {err}"
        attempt += 1
        now += delay


def _program(func: str, scenarios: list[list[tuple[int, int]]], p: dict) -> str:
    return (HEAD + func + "\n\n\n" + f"""def _run(scenario):
    now = [0]
    calls = [0]

    def clock():
        return now[0]

    def sleep(s):
        now[0] += s

    def op(timeout):
        code, dur = scenario[calls[0]]
        calls[0] += 1
        if dur > timeout:
            now[0] += max(timeout, 0)
            raise TransientError("timeout")
        now[0] += dur
        if code == 503:
            raise TransientError("503")
        if code == 400:
            raise PermanentError("400")
        return "ok"

    try:
        res = call_with_retry(op, clock, sleep, deadline={p['deadline']}, base={p['base']},
                              max_attempts={p['max_attempts']}, per_try={p['per_try']})
    except Exception as e:
        res = type(e).__name__
    print(f"calls={{calls[0]}} t={{now[0]}} {{res}}")


for _sc in {scenarios!r}:
    _run(_sc)
""")


def _desc(sc: list[tuple[int, int]]) -> str:
    return ", ".join(f"{c}/{d}с" for c, d in sc)


CONDITIONS = {
    "storm": dict(
        text=("Внешний сервис деградировал: отвечает 503 на половину запросов. Эту функцию "
              "вызывают 2000 экземпляров клиента одновременно. Что произойдёт с нагрузкой на "
              "сервис и что вы добавите в политику повторов и вокруг неё?"),
        criteria=[("effect", "Видит шторм повторов: нагрузка умножается до max_attempts раз "
                             "и синхронизируется по времени — волны без джиттера", 0.35),
                  ("policy", "Джиттер (full/decorrelated), бюджет повторов (доля от успешных "
                             "запросов), уважение Retry-After", 0.35),
                  ("breaker", "Circuit breaker / адаптивный троттлинг, быстрый отказ и "
                              "деградация функциональности, метрики повторов", 0.3)],
        strong="""Повторы умножают нагрузку: при 50 % отказов каждый исходный запрос даёт в среднем
            почти два вызова, а при полном отказе — max_attempts, и всё это в тот момент, когда
            сервис и так перегружен. Без джиттера 2000 клиентов, получивших ошибку одновременно,
            повторяют одновременно — волны через base, 2·base, 4·base. Добавляю полный джиттер
            (задержка случайна в [0, base·2^k]), бюджет повторов на клиента (например, повторы
            не больше 10 % от успешных запросов за окно, как retry budget в Envoy/Finagle) и
            уважение Retry-After. Вокруг — circuit breaker: при доле ошибок выше порога он
            размыкается, запросы сразу получают отказ или кэшированный ответ, затем пробные
            запросы в полуоткрытом состоянии. Метрики: число повторов, состояние предохранителя,
            чтобы видеть, что повторы не стали основной нагрузкой.""",
        medium="""Все клиенты начнут повторять одновременно, и сервис получит ещё больше запросов.
            Нужно добавить случайный джиттер к задержке и circuit breaker, который временно
            перестаёт вызывать сервис.""",
        weak="""Нужно увеличить max_attempts, чтобы запросы чаще проходили."""),
    "non_idempotent": dict(
        text=("Через эту функцию вызывают `POST /charges` платёжного провайдера. Иногда ответ "
              "приходит дольше timeout, и функция повторяет запрос. Какая проблема возникает и "
              "как сделать повторы безопасными?"),
        criteria=[("problem", "Таймаут не означает, что запрос не выполнен: провайдер мог "
                              "списать деньги, повтор даёт двойное списание", 0.35),
                  ("idempotency", "Ключ идемпотентности, один на логическую операцию и общий "
                                  "для всех повторов; сервер дедуплицирует", 0.4),
                  ("classify", "Различает ошибки до отправки (соединение не установлено) и "
                               "после; сверка статуса операции, неповторяемые методы", 0.25)],
        strong="""Таймаут на стороне клиента — неопределённый исход: запрос мог дойти, провайдер
            списал деньги, а потерялся только ответ. Повтор POST без защиты создаёт второе
            списание. Решение — ключ идемпотентности: генерирую его один раз на логическую
            операцию (например, из id заказа) до первой попытки и передаю в заголовке
            Idempotency-Key во всех повторах; провайдер возвращает сохранённый результат вместо
            нового списания. Политику делю по типам ошибок: отказ соединения до отправки можно
            повторять всегда, таймаут после отправки — только с ключом; 4xx не повторяются. Если
            ключей нет, вместо повтора запрашиваю статус операции по своему id и сверяю.
            Неидемпотентные операции без ключа функция повторять не должна — это стоит сделать
            явным параметром.""",
        medium="""Если ответ не дошёл, а платёж прошёл, повтор спишет деньги второй раз. Нужно
            передавать ключ идемпотентности, одинаковый для всех повторов.""",
        weak="""Нужно увеличить timeout, чтобы ответ успевал прийти."""),
    "nested": dict(
        text=("Запрос проходит цепочку gateway → orders → payments → банк, и на каждом из трёх "
              "уровней используется эта функция с max_attempts = 3. Банк перестал отвечать. "
              "Сколько запросов получит банк на один запрос пользователя и как это исправить?"),
        criteria=[("math", "Считает умножение повторов: 3 × 3 × 3 = 27 вызовов банка на один "
                           "запрос пользователя", 0.3),
                  ("one_layer", "Повторы на одном уровне (ближайшем к сбою или к клиенту), "
                                "остальные — без повторов или с бюджетом", 0.35),
                  ("deadline", "Передача дедлайна вниз по цепочке (оставшийся бюджет в "
                               "заголовке), отмена работы после истечения", 0.35)],
        strong="""Повторы перемножаются: каждый из трёх вызовов payments → банк повторяется трижды,
            orders повторяет payments трижды, gateway — orders трижды: 27 вызовов банка на один
            запрос, и это при уже лежащем банке. Плюс верхние уровни ждут, пока нижние
            исчерпают свои попытки, и их собственные таймауты истекают раньше — работа внизу
            продолжается впустую. Исправление: повторы только на одном уровне — обычно у
            клиента банка, где известна семантика ошибок; выше — без повторов или с общим
            бюджетом повторов. Дедлайн передаю вниз: gateway ставит общий бюджет, каждый
            уровень передаёт остаток в заголовке (как grpc-timeout) и использует
            min(свой таймаут, остаток); после истечения работа отменяется. Ошибку «бюджет
            исчерпан» не повторяют выше.""",
        medium="""Повторы на трёх уровнях перемножаются — до 27 запросов. Нужно оставить повторы
            только на одном уровне и передавать таймаут вниз.""",
        weak="""Банк получит 9 запросов; нужно уменьшить max_attempts до 2."""),
    "propagation": dict(
        text=("Входящий HTTP-запрос имеет дедлайн 2 с (балансировщик закрывает соединение). "
              "Обработчик последовательно вызывает два сервиса через эту функцию с deadline = "
              "2 для каждого. Что не так и как правильно распределять и передавать бюджет "
              "времени?"),
        criteria=[("problem", "Два вызова по 2 с могут занять до 4 с: ответ после закрытия "
                              "соединения бесполезен, работа идёт впустую", 0.35),
                  ("budget", "Один общий дедлайн запроса (абсолютное время), каждому вызову — "
                             "остаток минус запас, передача дедлайна вниз", 0.4),
                  ("cancel", "Отмена при разрыве соединения/истечении (asyncio.timeout, "
                             "cancel), метрики превышения дедлайна", 0.25)],
        strong="""Каждый вызов получает собственные 2 с, поэтому вместе они могут занять 4 с, а
            балансировщик закроет соединение через 2 — второй вызов и повторы тратят ресурсы
            ради ответа, который никто не получит. Правильно — один дедлайн на запрос в
            абсолютном времени (start + 2 с минус запас на сериализацию ответа), который
            передаётся во все вызовы: deadline каждого вызова — остаток общего бюджета, а
            сервисам ниже передаётся заголовок с остатком. Если остатка не хватает даже на
            минимальную попытку, сразу отвечаю 503/504 без вызова. При разрыве клиентом
            соединения отменяю работу (asyncio.timeout/cancel). Отслеживаю метрику «запросов,
            завершённых после дедлайна».""",
        medium="""Два вызова по 2 секунды не уложатся в общий дедлайн 2 секунды. Нужно считать
            общий остаток времени и передавать его в каждый вызов.""",
        weak="""Нужно увеличить таймаут балансировщика до 10 секунд."""),
}

CTX = ["клиент платёжного провайдера", "клиент сервиса геокодинга", "вызов API службы доставки",
       "клиент объектного хранилища", "вызов сервиса рекомендаций"]


# наборы (deadline, base, max_attempts, per_try), при которых проявляется каждый из пяти
# дефектов (подобраны перебором по модели) — параметры не выдают подтип
PARAMS = [(12, 1, 3, 5), (12, 1, 3, 6), (12, 1, 3, 7), (12, 1, 3, 8), (12, 1, 3, 9),
          (13, 1, 3, 5), (13, 1, 3, 7), (13, 1, 3, 8), (13, 1, 3, 9), (14, 1, 3, 6),
          (14, 1, 3, 8), (14, 1, 3, 9), (15, 1, 3, 6), (15, 1, 3, 9), (16, 1, 3, 7),
          (17, 1, 3, 7), (18, 1, 3, 8), (19, 1, 3, 8), (19, 2, 3, 7), (19, 2, 3, 8),
          (20, 1, 3, 9), (20, 2, 3, 7), (20, 2, 3, 8), (21, 1, 3, 9), (21, 1, 4, 6),
          (21, 1, 4, 7), (21, 1, 4, 8), (21, 1, 4, 9), (21, 2, 3, 8), (21, 2, 3, 9),
          (22, 1, 4, 6), (22, 1, 4, 7), (22, 1, 4, 8), (22, 2, 3, 8), (22, 2, 3, 9),
          (23, 1, 4, 7), (23, 1, 4, 8), (23, 2, 3, 9), (24, 1, 4, 7), (24, 1, 4, 8),
          (24, 1, 4, 9), (24, 2, 3, 9), (25, 1, 4, 8), (25, 1, 4, 9), (26, 1, 4, 8),
          (26, 1, 4, 9), (26, 3, 3, 9), (27, 1, 4, 9), (27, 3, 3, 9), (28, 1, 4, 9)]


def _rand_sc(rng, n: int, p: dict) -> list[tuple[int, int]]:
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.5:
            out.append((503, rng.randint(1, 3)))
        elif r < 0.65:
            out.append((400, rng.randint(1, 2)))
        elif r < 0.8:
            out.append((200, rng.randint(p["per_try"] - 2, p["per_try"] + 4)))
        else:
            out.append((200, rng.randint(1, 3)))
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sub = rng.choice(SUBTYPES)
    d, b, m, t = rng.choice(PARAMS)
    p = dict(deadline=d, base=b, max_attempts=m, per_try=t)
    n = p["max_attempts"] + 1
    code = HEAD + _func(sub)
    repro, clean = None, []
    for _ in range(20000):
        sc = _rand_sc(rng, n, p)
        good, bad = _model("good", sc, p), _model(sub, sc, p)
        if not good.startswith("calls=1 ") and _desc(sc) not in [_desc(c) for c in clean]:
            if good != bad and repro is None:
                repro = sc
            elif good == bad and len(clean) < 3:
                clean.append(sc)
        if repro and len(clean) == 3:
            break
    else:
        raise RuntimeError("не подобраны сценарии шага 1")
    opts1, key1 = make_options(rng, (_desc(repro), None), [(_desc(c), None) for c in clean], step=1)
    by_text = {_desc(repro): repro, **{_desc(c): c for c in clean}}
    pool = [k for k in SUBTYPES + ["check_after_sleep"] if k != sub]
    dk = rng.sample(pool, 3)
    battery: list[list[tuple[int, int]]] = []
    for _ in range(20000):
        sc = _rand_sc(rng, n, p)
        if any(_model(k, sc, p) != _model("good", sc, p) for k in dk
               if all(_model(k, b, p) == _model("good", b, p) for b in battery)):
            battery.append(sc)
        if all(any(_model(k, b, p) != _model("good", b, p) for b in battery) for k in dk):
            break
    else:
        raise RuntimeError("не подобран набор шага 2")
    opts2, key2 = make_options(rng, ("Заменить функцию на:", _func("good")),
                               [("Заменить функцию на:", _func(k)) for k in dk], step=2)
    by_code = {_func(k): k for k in VARIANT_LINES}
    checks = []
    for o in opts1:
        sc = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=_program(_func(sub), [sc], p),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=_model("good", sc, p)))
    exp2 = "\n".join(_model("good", b, p) for b in battery)
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python", embeds_display_code=False,
                            program=_program(_func(by_code[o.code]), battery, p),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=exp2))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    ctx = rng.choice(CTX)
    stem = (f"Функция `call_with_retry` ({ctx}) вызывает `op(timeout)` с повторами. Требования: "
            f"(1) не больше `max_attempts` вызовов; (2) повторяется только `TransientError`, "
            f"`PermanentError` пробрасывается сразу; (3) задержка перед k-м повтором — "
            f"base · 2^(k−1); (4) повтор не начинается, если ожидание закончится не раньше "
            f"дедлайна (start + deadline); (5) каждый вызов получает timeout = min(per_try, "
            f"остаток бюджета). Если повторять нельзя, пробрасывается последняя ошибка. Параметры: "
            f"deadline = {p['deadline']}, base = {p['base']}, max_attempts = {p['max_attempts']}, "
            f"per_try = {p['per_try']}; время — целые секунды, часы и sleep подменяются в "
            f"тестах. Запись ответов вызовов: «503/2с» — временная ошибка через 2 с, «400/1с» — "
            f"постоянная ошибка через 1 с, «200/3с» — успех через 3 с; если ответ дольше "
            f"timeout, через timeout секунд возникает TransientError.")
    steps = ob3_steps(
        "Шаг 1. При какой последовательности ответов (по одному на вызов) поведение функции "
        "нарушает требования — число вызовов, общее время или результат отличаются от "
        "требуемых?",
        "Шаг 2. Выберите исправленную функцию.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"off_by_one": "условие `attempt > max_attempts` допускает лишний вызов",
           "retries_permanent": "`except Exception` повторяет и PermanentError",
           "ignores_delay": "проверка дедлайна не учитывает предстоящую задержку — ожидание и "
                            "вызов выходят за дедлайн",
           "uncapped_timeout": "timeout не ограничен остатком бюджета — вызов может закончиться "
                               "после дедлайна",
           "check_after_sleep": "дедлайн проверяется после sleep — время ожидания уже потрачено"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Дефект: {why[sub]}. Дистракторы шага 2: "
                               + "; ".join(why[k] for k in dk) + ".")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="retry_policy",
                         params={"subtype": sub, **p, "distractors": dk, "condition": cond_name,
                                 "battery": battery})
