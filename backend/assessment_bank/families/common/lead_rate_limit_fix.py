"""common.arch.lead_rate_limit_fix — choose_fix (Lead у границы Lead/Principal, короткое): ограничитель частоты.

Ограничитель частоты запросов на шлюзе — «ведро жетонов». Принципы платформы даны без кода: лимит — на ключ клиента,
а не на адрес (за одним адресом бывает много клиентов); после простоя всплеск не больше ёмкости ведра; отклонённый
запрос не отнимает будущих жетонов. Показанный код нарушает все три; кандидат выбирает замену функции, выполняющую
все.

Правила (из пула выбираются два, варианты — схема 2×2: верный, нарушено первое, второе, оба):
* ``per_client`` — ведро по ключу клиента, а не по адресу;
* ``burst`` — накопление жетонов ограничено ёмкостью BURST;
* ``reject`` — отказ не уводит счёт жетонов в минус.
У вариантов свои локальные имена. Ключ проверяется исполнением: каждая замена исполняется в составе модуля на
четырёх сценариях с явным временем (два клиента за одним адресом; всплеск после простоя; запрос через 1/RATE с
после отказов; равномерный поток в пределах лимита).
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import module_choose_fix
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.arch.lead_rate_limit_fix"

CONTEXTS = ["публичный API платежей", "API поиска товаров", "шлюз мобильного приложения", "API выгрузки отчётов",
            "API отправки сообщений", "API геокодирования", "партнёрский API бронирования"]
FN_NAMES = ["allow", "try_acquire", "admit", "take_token", "check_limit"]
LOCALS = {"KEY": ["key", "k", "bucket_id", "owner"], "TOK": ["tokens", "left", "avail", "balance"],
          "LAST": ["last", "ts", "prev", "seen_at"]}

MODULE = '''"""Ограничитель частоты на шлюзе: ведро жетонов на клиента."""

RATE = @RATE@        # жетонов в секунду
BURST = @BURST@      # ёмкость ведра


{FN}
'''

CORRECT = '''def @FN@(buckets, api_key, ip, now):
    """True — пропустить запрос; buckets хранит (жетоны, время) по ключу."""
    @KEY@ = api_key
    @TOK@, @LAST@ = buckets.get(@KEY@, (BURST, now))
    @TOK@ = min(BURST, @TOK@ + (now - @LAST@) * RATE)
    if @TOK@ >= 1:
        buckets[@KEY@] = (@TOK@ - 1, now)
        return True
    buckets[@KEY@] = (@TOK@, now)
    return False'''

RULES = {
    "per_client": ("    @KEY@ = api_key", "    @KEY@ = ip"),
    "burst": ("@TOK@ = min(BURST, @TOK@ + (now - @LAST@) * RATE)", "@TOK@ = @TOK@ + (now - @LAST@) * RATE"),
    "reject": ("    buckets[@KEY@] = (@TOK@, now)\n    return False", "    buckets[@KEY@] = (@TOK@ - 1, now)\n    return False"),
}
RULE_TEXT = {"per_client": "лимит — на ключ клиента, а не на адрес (за одним адресом бывает много клиентов)",
             "burst": "после простоя всплеск не больше ёмкости ведра",
             "reject": "отклонённый запрос не отнимает будущих жетонов"}

TESTS = '''
# 1) два клиента за одним адресом получают каждый своё ведро
b = {}
ok = sum(@FN@(b, key, "10.0.0.7", 0.0) for key in ("client-a", "client-b") for _ in range(BURST))
assert ok == 2 * BURST, ("клиенты за одним адресом делят лимит", ok)

# 2) всплеск после долгого простоя не больше ёмкости ведра
b = {}
@FN@(b, "c1", "10.0.0.1", 0.0)
burst = sum(@FN@(b, "c1", "10.0.0.1", 1000.0) for _ in range(3 * BURST))
assert burst <= BURST, ("всплеск больше ёмкости", burst)

# 3) после отказов через 1 / RATE секунды доступен ровно новый жетон
b = {}
for _ in range(BURST + @EXTRA@):
    @FN@(b, "c2", "10.0.0.2", 0.0)
assert @FN@(b, "c2", "10.0.0.2", 1.0 / RATE), "отказы отняли будущие жетоны"

# 4) равномерный поток в пределах лимита проходит целиком
b = {}
t, passed = 0.0, 0
for i in range(10 * RATE):
    t = i / RATE
    passed += @FN@(b, "c3", "10.0.0.3", t)
assert passed == 10 * RATE, ("поток в пределах лимита отклонён", passed)
'''


def _render(tpl: str, fn: str, names: dict[str, str]) -> str:
    out = tpl.replace("@FN@", fn)
    for k, v in names.items():
        out = out.replace(f"@{k}@", v)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    fn = rng.choice(FN_NAMES)
    rate = rng.choice([2, 4, 5, 10])
    burst = rng.choice([5, 10, 20, 50])
    extra = rng.choice([2, 3, 5, 8])
    a, b = rng.sample(sorted(RULES), 2)

    def variant(broken):
        names = {k: rng.choice(v) for k, v in LOCALS.items()}
        tpl = CORRECT
        for r in broken:
            old, new = RULES[r]
            assert tpl.count(old) == 1, r
            tpl = tpl.replace(old, new)
        return _render(tpl, fn, names)

    correct = variant([])
    distractors = [variant([a]), variant([b]), variant([a, b])]
    buggy_tpl = CORRECT
    for r in RULES:
        buggy_tpl = buggy_tpl.replace(*RULES[r])
    buggy = _render(buggy_tpl, fn, {k: v[0] for k, v in LOCALS.items()})
    module = MODULE.replace("@RATE@", str(rate)).replace("@BURST@", str(burst))
    tests = TESTS.replace("@FN@", fn).replace("@EXTRA@", str(extra))
    intro = rng.choice([
        f"Вы — ведущий инженер. Для продукта «{ctx}» на шлюзе стоит ограничитель частоты — функция `{fn}` (модуль "
        f"ниже), {rate} запросов в секунду и всплеск до {burst}.",
        f"Клиенты продукта «{ctx}» жалуются на ложные отказы и внезапные всплески нагрузки; вы как ведущий инженер "
        f"разбираете ограничитель частоты `{fn}` (модуль ниже; {rate} в секунду, всплеск до {burst}).",
        f"Ограничитель частоты `{fn}` (модуль ниже) защищает продукт «{ctx}»: {rate} запросов в секунду, всплеск до "
        f"{burst}; вы как ведущий инженер утверждаете его исправление.",
    ])
    principles = "; ".join(RULE_TEXT[r] for r in ("per_client", "burst", "reject"))
    stem = f"{intro} Принципы платформы: {principles}.\n\nКакая замена функции `{fn}` выполняет все три принципа?"
    why = ("Верная замена: ведро — по ключу клиента, накопление жетонов ограничено BURST, отказ не уводит счёт в "
           f"минус. Дистракторы нарушают: «{RULE_TEXT[a]}», «{RULE_TEXT[b]}» или оба.")
    return module_choose_fix(FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct,
                             distractors=distractors, tests=tests, context=ctx, defect="rate_limit", why=why,
                             label="Заменить функцию на:",
                             params={"rules": f"{a}+{b}", "fn": fn, "rate": rate, "burst": burst, "extra": extra})
