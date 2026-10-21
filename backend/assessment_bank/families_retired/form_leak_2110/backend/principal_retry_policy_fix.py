"""backend.arch.principal_retry_policy_fix — choose_fix (Principal, короткое): общая обёртка повторов платформы.

Сервисы платформы вызывают друг друга через одну обёртку с повторами. Во время отказа нижнего сервиса повторы на
каждом уровне перемножаются (шторм повторов), попытки продолжаются после дедлайна клиента, а ошибки клиента
повторяются впустую. Архитектурный совет утвердил три принципа (без кода): повторы не усиливают отказ, ответ — не
позже дедлайна клиента, ошибки клиента не повторяются. Кандидат выбирает замену функции обёртки, которая
выполняет все три принципа; показанный код нарушает все три.

Правила (из пула выбираются два, варианты — по схеме 2×2: верный, нарушено первое, второе, оба):
* ``budget`` — повтор только при наличии жетона общего бюджета повторов (доля от запросов плюс запас);
* ``deadline`` — попытка получает оставшееся до дедлайна время, а не постоянный таймаут;
* ``retryable`` — повторяется только «сервис недоступен», ошибка клиента (неверный аргумент) — нет.
У каждого варианта свои локальные имена (форма не выдаёт ключ). Ключ проверяется исполнением: каждая замена
исполняется в составе модуля на четырёх сценариях с поддельными часами (полный отказ на 200 запросах — число
попыток в пределах бюджета; медленный сервис — ни одна попытка не заканчивается после дедлайна; ошибка клиента —
одна попытка; временный отказ — успех со второй попытки).
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import module_choose_fix
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.arch.principal_retry_policy_fix"

CONTEXTS = [("оформление заказа", "склад"), ("выдача кредита", "скоринг"), ("бронирование", "наличие мест"),
            ("лента новостей", "профили"), ("поиск поездки", "тарифы"), ("личный кабинет", "биллинг"),
            ("каталог", "цены"), ("платёжный шлюз", "антифрод")]
FN_NAMES = ["call_downstream", "guarded_call", "call_with_policy", "invoke", "rpc_call"]
LOCALS = {"att": ["attempt", "tries", "n", "retry_no"], "rem": ["remaining", "left_ms", "time_left", "rest_ms"],
          "exc": ["err", "exc", "e", "failure"]}

MODULE = '''"""Общая обёртка вызовов между сервисами платформы."""

MAX_RETRIES = @MAXR@
TIMEOUT_MS = @TO@
MIN_ATTEMPT_MS = @MIN@
BACKOFF_MS = @BO@


class Unavailable(Exception):
    """Нижний сервис недоступен или не ответил вовремя."""


class InvalidArgument(Exception):
    """Ошибка клиента: запрос неверен, повтор не поможет."""


class DeadlineExceeded(Exception):
    """До дедлайна клиента не осталось времени на попытку."""


class RetryBudget:
    """Общий бюджет повторов процесса: жетоны копятся долей от запросов, не больше запаса."""

    def __init__(self, ratio=@RATIO@, reserve=@RES@):
        self.ratio, self.cap, self.tokens = ratio, reserve, reserve

    def on_request(self):
        self.tokens = min(self.cap, self.tokens + self.ratio)

    def try_spend(self):
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


{FN}
'''

CORRECT = '''def @FN@(op, deadline_ms, clock, budget):
    """Вызов нижележащего сервиса с повторами."""
    @ATT@ = 0
    budget.on_request()
    while True:
        @REM@ = deadline_ms - clock.now()
        if @REM@ < MIN_ATTEMPT_MS:
            raise DeadlineExceeded(@REM@)
        try:
            return op(timeout_ms=@REM@)
        except Unavailable:
            @ATT@ += 1
            if @ATT@ > MAX_RETRIES or not budget.try_spend():
                raise
            clock.sleep(BACKOFF_MS * @ATT@)'''

RULES = {
    "budget": ("if @ATT@ > MAX_RETRIES or not budget.try_spend():", "if @ATT@ > MAX_RETRIES:"),
    "deadline": ("return op(timeout_ms=@REM@)", "return op(timeout_ms=TIMEOUT_MS)"),
    "retryable": ("except Unavailable:", "except (Unavailable, InvalidArgument):"),
}
RULE_TEXT = {"budget": "повторы не усиливают отказ", "deadline": "ответ — не позже дедлайна клиента",
             "retryable": "ошибки клиента не повторяются"}

TESTS = '''
class Clock:
    def __init__(self):
        self.t = 0
    def now(self):
        return self.t
    def sleep(self, ms):
        self.t += ms

# 1) полный отказ нижнего сервиса: попыток не больше, чем позволяет бюджет повторов
clock, budget, calls = Clock(), RetryBudget(), [0]
def down(timeout_ms):
    calls[0] += 1
    clock.sleep(1)
    raise Unavailable()
for i in range(200):
    try:
        @FN@(down, clock.now() + 10_000, clock, budget)
    except (Unavailable, DeadlineExceeded):
        pass
limit = 200 + 200 * @RATIO@ + @RES@
assert calls[0] <= limit, ("шторм повторов", calls[0], limit)

# 2) медленный сервис: ни одна попытка не заканчивается после дедлайна клиента
clock, budget, late = Clock(), RetryBudget(), []
DEADLINE = @DL@
def slow(timeout_ms):
    took = min(@LAT@, timeout_ms)
    clock.sleep(took)
    if clock.now() > DEADLINE:
        late.append(clock.now())
    if took < @LAT@:
        raise Unavailable()
    return "ok"
try:
    @FN@(slow, DEADLINE, clock, budget)
except (Unavailable, DeadlineExceeded):
    pass
assert not late, ("попытка после дедлайна", late)

# 3) ошибка клиента — ровно одна попытка
clock, budget, n = Clock(), RetryBudget(), [0]
def bad(timeout_ms):
    n[0] += 1
    raise InvalidArgument()
try:
    @FN@(bad, 10_000, clock, budget)
    raise AssertionError("ошибка клиента проглочена")
except InvalidArgument:
    pass
assert n[0] == 1, ("ошибка клиента повторена", n[0])

# 4) временный отказ — успех со второй попытки
clock, budget, k = Clock(), RetryBudget(), [0]
def flaky(timeout_ms):
    k[0] += 1
    clock.sleep(5)
    if k[0] == 1:
        raise Unavailable()
    return "ok"
assert @FN@(flaky, 10_000, clock, budget) == "ok" and k[0] == 2
'''


def _render(tpl: str, fn: str, names: dict[str, str]) -> str:
    return tpl.replace("@FN@", fn).replace("@ATT@", names["att"]).replace("@REM@", names["rem"])


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, down = rng.choice(CONTEXTS)
    fn = rng.choice(FN_NAMES)
    maxr = rng.choice([2, 3, 4])
    to = rng.choice([1000, 2000, 3000])
    mn = rng.choice([20, 30, 50])
    bo = rng.choice([5, 10, 20])
    ratio = rng.choice([0.1, 0.2])
    res = rng.choice([5, 10])
    lat = rng.choice([150, 200, 300])                 # медленный сервис отвечает за lat мс
    dl = lat - rng.choice([30, 50, 70])               # дедлайн клиента раньше, чем отвечает медленный сервис
    a, b = rng.sample(sorted(RULES), 2)

    def variant(broken):
        names = {k: rng.choice(v) for k, v in LOCALS.items()}
        tpl = CORRECT
        for r in broken:
            old, new = RULES[r]
            tpl = tpl.replace(old, new)
        return _render(tpl, fn, names)

    correct = variant([])
    distractors = [variant([a]), variant([b]), variant([a, b])]
    # показанный код нарушает все три принципа
    buggy_tpl = CORRECT
    for r in RULES:
        buggy_tpl = buggy_tpl.replace(*RULES[r])
    buggy = _render(buggy_tpl, fn, {k: v[0] for k, v in LOCALS.items()})
    module = (MODULE.replace("@MAXR@", str(maxr)).replace("@TO@", str(to)).replace("@MIN@", str(mn))
              .replace("@BO@", str(bo)).replace("@RATIO@", str(ratio)).replace("@RES@", str(res)))
    tests = (TESTS.replace("@FN@", fn).replace("@RATIO@", str(ratio)).replace("@RES@", str(res))
             .replace("@DL@", str(dl)).replace("@LAT@", str(lat)))
    intro = rng.choice([
        f"Вы — главный инженер платформы. Сервис «{ctx}» вызывает «{down}» через общую обёртку `{fn}` (модуль ниже), "
        f"её же используют все уровни цепочки.",
        f"На разборе последнего отказа «{down}» выяснилось: общая обёртка `{fn}` (модуль ниже), через которую "
        f"«{ctx}» и остальные сервисы вызывают друг друга, сама усилила аварию.",
        f"Платформа «{ctx}» ходит в «{down}» через общую обёртку `{fn}` (модуль ниже); её используют все уровни "
        f"цепочки вызовов, и вы как главный инженер утверждаете её исправление.",
    ])
    principles = "; ".join(RULE_TEXT[r] for r in sorted(RULES))
    stem = (f"{intro} Во время отказа нижнего сервиса повторы на каждом уровне перемножаются, попытки идут и после "
            f"дедлайна клиента, а ошибки клиента повторяются впустую. Архитектурный совет утвердил принципы: "
            f"{principles}.\n\nКакая замена функции `{fn}` выполняет все три принципа?")
    why = (f"Верная замена: повтор только при жетоне общего бюджета (доля {ratio} от запросов плюс запас {res} — "
           f"повторы не перемножаются), попытка получает оставшееся до дедлайна время и не начинается, если осталось "
           f"меньше MIN_ATTEMPT_MS, повторяется только Unavailable. Дистракторы нарушают: «{RULE_TEXT[a]}», "
           f"«{RULE_TEXT[b]}» или оба.")
    return module_choose_fix(FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct,
                             distractors=distractors, tests=tests, context=ctx, defect="retry_policy", why=why,
                             label="Заменить функцию на:",
                             params={"rules": f"{a}+{b}", "fn": fn, "maxr": maxr, "ratio": ratio, "res": res,
                                     "lat": lat, "dl": dl, "min": mn, "to": to, "bo": bo})
