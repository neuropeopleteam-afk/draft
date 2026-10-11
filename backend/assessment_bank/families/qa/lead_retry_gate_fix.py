"""qa.lead.retry_gate_fix — choose_fix (Lead): гейт слияния с перезапуском упавших тестов и карантином.

Кандидату показан модуль гейта (~35 строк) с дефектом «тесты без результата не учитываются»: решение строится по
полученным результатам, а не по ожидаемому набору, — упавший шард даёт зелёный конвейер. Варианты — четыре замены
``decide`` в другом стиле (цикл), чем показанный код: эвристика «минимальная правка» не работает. Каждый дистрактор
исправляет пропуск, но нарушает ровно одно правило политики (фиксированный состав):

* ``quarantine_missing`` — карантин освобождает изменённый в MR тест (правило «тест из карантина, который MR
  изменил, проверяется как обычный» потеряно; вместо него — «отсутствие результата блокирует всегда»);
* ``changed_flaky_tolerance`` — нестабильный изменённый тест блокирует, только если таких больше одного;
* ``rerun_before_block`` — проверка «прогон недостоверен» стоит раньше блокировки: настоящий отказ превращается
  в «перезапуск».

Ключ проверяется исполнением: все варианты исполняются в составе модуля на восьми сценариях; верный проходит
все, каждый дистрактор и показанный код падают хотя бы на одном.
"""
from __future__ import annotations

import math

from assessment_bank.families._lead_b_utils import module_choose_fix, pct
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.lead.retry_gate_fix"

CONTEXTS = ["маркетплейс", "мобильный банк", "сервис доставки", "платформа найма", "онлайн-кинотеатр",
            "система бронирования", "облачная бухгалтерия", "телемедицина"]
NAME_POOLS = {  # каждое имя выбирается независимо: варианты различаются видимым кодом, а не одним числом
    "E": ["expected", "planned", "collected", "suite", "required"],
    "R": ["results", "runs", "outcomes", "reports", "attempt_log"],
    "C": ["changed", "touched", "modified", "diff_tests", "mr_tests"],
    "Q": ["quarantine", "muted", "isolated", "parked", "on_hold"],
    "S": ["summary", "tally", "counts", "breakdown", "digest"],
    "V": ["verdict", "status", "outcome", "state", "kind"],
    "T": ["t", "name", "tid", "test", "case"],
    "B": ["blocking", "blockers", "stop", "reasons", "red"],
}
LABELS = [("block", "rerun", "pass"), ("deny", "retry", "allow"), ("stop", "restart", "merge"),
          ("reject", "rerun", "accept")]
MODULES = ["checkout", "cart", "auth", "search", "profile", "payment", "orders", "catalog", "delivery", "promo",
           "billing", "reviews", "notify", "geo"]

CLASSIFY = '''def classify(attempts):
    """Итог теста по попыткам: pass, flaky (красная, затем зелёная), fail, missing (нет результата)."""
    attempts = list(attempts)[:MAX_ATTEMPTS]
    if not attempts:
        return "missing"
    if attempts[0] == "pass":
        return "pass"
    return "flaky" if "pass" in attempts else "fail"'''

SUMMARY = '''def @S@(@E@, @R@):
    """Сводка для страницы MR: сколько тестов каждого итога."""
    counts = {}
    for @T@ in @E@:
        @V@ = classify(@R@.get(@T@, []))
        counts[@V@] = counts.get(@V@, 0) + 1
    return counts'''

BUGGY = '''def decide(@E@, @R@, @C@, @Q@):
    excused = set(@Q@) - set(@C@)
    verdicts = {@T@: classify(a) for @T@, a in @R@.items()}
    hard = [@T@ for @T@, v in verdicts.items() if v in ("fail", "missing") and @T@ not in excused]
    new_flaky = [@T@ for @T@, v in verdicts.items() if v == "flaky" and @T@ in @C@]
    if hard or new_flaky:
        return @KB@
    flaky = [@T@ for @T@, v in verdicts.items() if v == "flaky"]
    if len(flaky) > FLAKY_SHARE_LIMIT * len(verdicts):
        return @KR@
    return @KP@'''

CORRECT = '''def decide(@E@, @R@, @C@, @Q@):
    @B@, flaky = [], 0
    for @T@ in @E@:
        v = classify(@R@.get(@T@, []))
        if v in ("fail", "missing") and (@T@ not in @Q@ or @T@ in @C@):
            @B@.append(@T@)
        elif v == "flaky":
            flaky += 1
            if @T@ in @C@:
                @B@.append(@T@)
    if @B@:
        return @KB@
    if flaky > FLAKY_SHARE_LIMIT * len(@E@):
        return @KR@
    return @KP@'''

DISTRACTORS = {  # каждая замена обязана изменить CORRECT (проверяется ниже)
    "quarantine_missing": CORRECT.replace('(@T@ not in @Q@ or @T@ in @C@)', '(@T@ not in @Q@ or v == "missing")'),
    "changed_flaky_tolerance": CORRECT.replace("if @T@ in @C@:", "if @T@ in @C@ and flaky > 1:"),
    "rerun_before_block": CORRECT.replace(
        '''    if @B@:
        return @KB@
    if flaky > FLAKY_SHARE_LIMIT * len(@E@):
        return @KR@''',
        '''    if flaky > FLAKY_SHARE_LIMIT * len(@E@):
        return @KR@
    if @B@:
        return @KB@'''),
}

assert all(d != CORRECT for d in DISTRACTORS.values())

WHY = {
    "quarantine_missing": "карантин по-прежнему освобождает тест, который MR изменил, — автор «чинит» тест из "
                          "карантина, и его красный результат никто не видит",
    "changed_flaky_tolerance": "один нестабильный новый или изменённый тест проходит в main — правило требует "
                               "блокировать уже первый",
    "rerun_before_block": "при большой доле нестабильных тестов настоящий отказ превращается в перезапуск, а "
                          "повторный прогон может оказаться зелёным",
}


def _rename(code: str, names: dict[str, str]) -> str:
    for k, v in names.items():
        code = code.replace(f"@{k}@", v)
    if "@" in code:
        raise ValueError("не заменена метка имени")
    return code


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    names = {k: rng.choice(v) for k, v in NAME_POOLS.items()}
    kb, kr, kp = rng.choice(LABELS)
    names.update(KB=repr(kb), KR=repr(kr), KP=repr(kp))
    attempts_max = rng.choice([2, 3])
    for _ in range(100):
        limit = rng.choice([0.1, 0.15, 0.2, 0.25])
        n = rng.randint(10, 20)
        frac = limit * n - math.floor(limit * n)
        if 0.2 <= frac <= 0.8 and limit * n >= 1.2:
            break
    k_hi = math.floor(limit * n) + 1
    k_lo = max(1, math.floor(limit * n))
    mods = rng.sample(MODULES, 4)
    tests = [f"test_{mods[i % 4]}_{i // 4 + 1}" for i in range(n)]
    rng.shuffle(tests)
    shard = rng.randint(2, 4)
    flaky_run = ["fail"] * (attempts_max - 1) + ["pass"]
    fail_run = ["fail"] * attempts_max

    def res(over: dict[str, list[str]], drop: tuple[str, ...] = ()) -> dict[str, list[str]]:
        return {t: over.get(t, ["pass"]) for t in tests if t not in drop}

    t0, t1, t2 = tests[0], tests[1], tests[2]
    many = tests[3:3 + k_hi]
    few = tests[3:3 + k_lo]
    scen = [  # (имя, results, changed, quarantine, ожидаемое)
        ("missing_shard", res({}, drop=tuple(tests[-shard:])), set(), set(), kb),
        ("changed_flaky", res({t0: flaky_run}), {t0}, set(), kb),
        ("fail_among_flaky", res({t1: fail_run, **{t: flaky_run for t in many}}), set(), set(), kb),
        ("quarantined_changed", res({t2: fail_run}), {t2}, {t2}, kb),
        ("quarantined_unchanged", res({t2: fail_run}), set(), {t2}, kp),
        ("quarantined_missing", res({}, drop=(t2,)), set(), {t2}, kp),
        ("many_flaky", res({t: flaky_run for t in many}), set(), set(), kr),
        ("few_flaky", res({t: flaky_run for t in few}), set(), set(), kp),
    ]
    rng.shuffle(scen)
    lines = [f"E = {tests!r}"]
    for name, r, c, q, exp in scen:
        lines.append(f"assert decide(E, {r!r}, {sorted(c)!r}, {sorted(q)!r}) == {exp!r}, {name!r}")
    test_body = "\n".join(lines)

    blocks = [CLASSIFY, "{FN}", SUMMARY]
    if rng.random() < 0.5:
        blocks = ["{FN}", CLASSIFY, SUMMARY]
    module = (f"MAX_ATTEMPTS = {attempts_max}\nFLAKY_SHARE_LIMIT = {limit}\n\n\n" + "\n\n\n".join(blocks))
    module = _rename(module, names)
    buggy, correct = _rename(BUGGY, names), _rename(CORRECT, names)
    kinds = sorted(DISTRACTORS)
    dis = [_rename(DISTRACTORS[k], names) for k in kinds]
    E, R, C, Q = names["E"], names["R"], names["C"], names["Q"]
    policy = [
        f"набор тестов задаёт `{E}`; тест без результата (не дошёл отчёт, упал шард) считается красным",
        "тест, красный во всех попытках, блокирует слияние",
        f"нестабильный тест (красный, затем зелёный) слияние не блокирует, если только MR не добавил или не "
        f"изменил его (`{C}`) — новый нестабильный тест в main не пускаем",
        f"карантин (`{Q}`) освобождает от блокировки красные и отсутствующие результаты тестов, которых MR не "
        f"касался; тест из карантина, изменённый в MR, проверяется как обычный",
        f"если нестабильных больше {pct(limit, 0)} от набора — прогон недостоверен, итог «{kr}», но "
        f"блокировка важнее перезапуска",
    ]
    stem = (f"Конвейер MR ({ctx}) перезапускает упавшие тесты (всего до {attempts_max} попыток) и решает, можно "
            f"ли сливать изменения: `decide` возвращает «{kb}» (блокировать), «{kr}» (перезапустить конвейер) или "
            f"«{kp}» (можно сливать). Политика команды: "
            + "; ".join(f"({i}) {p}" for i, p in enumerate(policy, 1)) +
            f". Инцидент: шард из {shard} тестов упал по нехватке памяти, его результатов в отчёте нет, "
            f"конвейер дал «{kp}», и регрессия попала в main. Какая замена `decide` выполняет политику целиком?")
    why = ("Верная замена проходит по ожидаемому набору (отсутствующий результат — красный), освобождает "
           "карантином только тесты, которых MR не касался, блокирует первый же нестабильный изменённый тест и "
           f"проверяет блокировку раньше «{kr}». Остальные варианты исправляют пропуск, но: "
           + "; ".join(WHY[k] for k in kinds) + ".")
    return module_choose_fix(
        FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct, distractors=dis,
        tests=test_body, context=ctx, defect="missing_results_ignored", why=why,
        label="Заменить decide на:",
        params={"limit": limit, "n": n, "attempts": attempts_max, "labels": [kb, kr, kp], "distractors": kinds})
