"""devops.sre.burn_rate_mcq — mcq_concept: какие алерты по скорости расхода бюджета ошибок сработают.

Многооконные алерты по burn rate (подход книги Google «The Site Reliability Workbook», гл. 5): burn rate =
доля ошибок за окно / (1 − SLO). Быстрый алерт — длинное окно 1 ч и короткое 5 мин выше порога 14,4 (оба
условия, `and`); медленный — 6 ч и 30 мин выше 6. Подтип один: даны доли ошибок по четырём окнам и SLO,
нужно перевести их в burn rate и применить `and`. Ловушка — длинное окно выше порога, а короткое уже ниже
(инцидент закончился — алерт не срабатывает), SLO не 99,9 % (масштаб). Варианты — всегда четыре исхода
(только быстрый, только медленный, оба, ни один), целевой — равномерно. Ключ — исполнение модели над
показанными правилами и долями ошибок в песочнице Python.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import emit, program

FAMILY_ID = "devops.sre.burn_rate_mcq"

OUTCOMES = ["Только ErrorBudgetFastBurn", "Только ErrorBudgetSlowBurn", "Оба алерта", "Ни один"]
CTX = [("API платежей", "payments"), ("поиск по каталогу", "search"), ("сервис авторизации", "auth"),
       ("API доставки", "delivery"), ("сервис уведомлений", "notify")]
SLOS = [("99.9", Fraction(999, 1000)), ("99.5", Fraction(995, 1000)), ("99.95", Fraction(9995, 10000)),
        ("99.0", Fraction(99, 100))]

MODEL = '''
from fractions import Fraction
rules = parse_yaml(RULES)["groups"][0]["rules"]
slo = Fraction(SLO)
fired = []
for r in rules:
    ok = True
    for part in r["expr"].split(" and "):
        metric, thr = part.strip("() ").split(" > ")
        window = metric.split(":")[-1].replace("burn_rate", "")
        burn = Fraction(RATIOS[window]) / (1 - slo)
        ok = ok and burn > Fraction(thr)
    if ok:
        fired.append(r["alert"])
names = ["ErrorBudgetFastBurn", "ErrorBudgetSlowBurn"]
if len(fired) == 2:
    print("Оба алерта")
elif fired:
    print("Только " + fired[0])
else:
    print("Ни один")
'''


def _pct(x: Fraction) -> str:
    return f"{float(x * 100):.3f}".rstrip("0").rstrip(".").replace(".", ",") + " %"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    outcome = rng.choice(OUTCOMES)
    slo_txt, slo = rng.choice(SLOS)
    budget = 1 - slo
    for _ in range(2000):
        fast = outcome in (OUTCOMES[0], OUTCOMES[2])
        slow = outcome in (OUTCOMES[1], OUTCOMES[2])
        # burn rate по окнам (в долях порога), затем доля ошибок = burn × (1 − SLO)
        def pick(on, thr, trap_short):
            if on:
                return thr * Fraction(rng.choice([11, 12, 13, 15, 20]), 10), thr * Fraction(rng.choice([11, 13, 16, 25]), 10)
            if trap_short:  # длинное окно выше порога, короткое уже ниже
                return thr * Fraction(rng.choice([11, 13, 15]), 10), thr * Fraction(rng.choice([2, 4, 6, 8]), 10)
            return thr * Fraction(rng.choice([2, 4, 6, 8]), 10), thr * Fraction(rng.choice([3, 6, 9, 12]), 10)
        b1h, b5m = pick(fast, Fraction(144, 10), rng.random() < 0.6)
        b6h, b30m = pick(slow, Fraction(6), rng.random() < 0.6)
        if not fast and b1h > Fraction(144, 10) and b5m > Fraction(144, 10):
            continue
        if not slow and b6h > 6 and b30m > 6:
            continue
        ratios = {"1h": b1h * budget, "5m": b5m * budget, "6h": b6h * budget, "30m": b30m * budget}
        # доли ошибок — «круглые» до тысячных процента, иначе ответ не читается
        if all((r * 100000).denominator == 1 for r in ratios.values()) and len(set(ratios.values())) == 4:
            trap = (not fast and b1h > Fraction(144, 10)) or (not slow and b6h > 6)
            if trap or outcome == OUTCOMES[2]:
                break
    rule = {"groups": [{"name": f"{svc}-slo", "rules": [
        {"alert": "ErrorBudgetFastBurn",
         "expr": "(slo:burn_rate1h > 14.4) and (slo:burn_rate5m > 14.4)", "labels": {"severity": "page"}},
        {"alert": "ErrorBudgetSlowBurn",
         "expr": "(slo:burn_rate6h > 6) and (slo:burn_rate30m > 6)", "labels": {"severity": "ticket"}}]}]}
    code = emit(rule)
    opts, key = make_options(rng, (outcome, None), [(o, None) for o in OUTCOMES if o != outcome])
    table = ", ".join(f"{w} — {_pct(ratios[w])}" for w in ("5m", "30m", "1h", "6h"))
    stem = (f"SLO доступности сервиса «{ctx}» — {slo_txt.replace('.', ',')} %. Метрика `slo:burn_rateОКНО` — "
            "скорость расхода бюджета: доля ошибок за окно, делённая на (1 − SLO). Сейчас доля неуспешных запросов "
            f"по окнам: {table}. Какие алерты из правил ниже сработают?")
    br = {w: ratios[w] / budget for w in ratios}
    dec = lambda x: f"{float(x):.2f}".rstrip("0").rstrip(".").replace(".", ",")  # noqa: E731
    expl = (f"1 − SLO = {_pct(budget)}. Burn rate: 1h {dec(br['1h'])}, 5m {dec(br['5m'])} (порог 14,4); "
            f"6h {dec(br['6h'])}, 30m {dec(br['30m'])} (порог 6). Алерт срабатывает, только если выше порога оба окна. "
            f"Ответ: {outcome.lower()}.")
    ratio_txt = {k: str(v) for k, v in ratios.items()}
    prog = program(f"SLO = {str(slo)!r}\nRATIOS = {ratio_txt!r}\n" + MODEL, RULES=code)
    checks = [Check(name="burn_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=outcome)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Исполняется модель многооконных алертов над показанными правилами",
                         params={"outcome": outcome, "slo": slo_txt})
