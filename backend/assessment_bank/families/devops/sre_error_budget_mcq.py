"""devops.sre.error_budget_mcq — mcq_concept: остаток бюджета ошибок SLO доступности после инцидентов.

SLO доступности по запросам за окно 28 или 30 дней, трафик равномерный, поэтому бюджет удобно мерить в
«минутах полного отказа»: (1 − SLO) × длительность окна. Инциденты: полный отказ (100 % ошибок), частичный
(p % запросов с ошибкой c минут → p·c/100 минут бюджета) и замедление без ошибок (в SLO доступности не
входит). Подтип один. Дистракторы — три из четырёх типовых ошибок: частичный инцидент не учтён; учтён целиком
без взвешивания; забыт полный отказ; замедление посчитано как отказ. Параметры подобраны так, что все
четыре варианта — «осталось», знак ответа не подсказывает. Ключ — точный расчёт
(Fraction) в песочнице Python, сверка с текстом верного варианта.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.sre.error_budget_mcq"

CTX = ["API мобильного банка", "витрина интернет-магазина", "сервис бронирования", "платёжный шлюз",
       "личный кабинет оператора связи", "сервис доставки"]
SLOS = [("99.9", Fraction(999, 1000)), ("99.95", Fraction(9995, 10000)), ("99.5", Fraction(995, 1000)),
        ("99.8", Fraction(998, 1000))]


def fmt(x: Fraction) -> str:
    v = round(float(x), 1)
    s = f"{abs(v):.1f}".replace(".", ",")
    return f"осталось ≈ {s} мин" if v >= 0 else f"перерасход ≈ {s} мин"


CHECK = '''from fractions import Fraction
slo, days = Fraction({slo_num}, {slo_den}), {days}
budget = (1 - slo) * days * 24 * 60
used = {full} + Fraction({p}, 100) * {c}   # замедление без ошибок в SLO доступности не входит
v = round(float(budget - used), 1)
s = f"{{abs(v):.1f}}".replace(".", ",")
print(f"осталось ≈ {{s}} мин" if v >= 0 else f"перерасход ≈ {{s}} мин")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    for _ in range(2000):
        slo_txt, slo = rng.choice(SLOS)
        days = rng.choice([28, 30])
        budget = (1 - slo) * days * 24 * 60
        full = rng.randint(2, max(3, int(budget / 6)))
        p, c = rng.choice([10, 20, 25, 40, 50]), rng.choice([10, 15, 20, 30, 40, 45, 60, 90])
        d = rng.choice([5, 10, 15, 25, 35, 50])
        used = full + Fraction(p, 100) * c
        variants = {"ignore_partial": budget - full, "forgot_full": budget - used + full,
                    "no_weight": budget - full - c, "latency": budget - used - d}
        # все варианты — «осталось»: знак не подсказывает ответ
        if min(variants.values()) < 1 or budget - used < 1:
            continue
        texts = {k: fmt(v) for k, v in variants.items()}
        correct = fmt(budget - used)
        kinds = rng.sample(sorted(variants), 3)
        if correct not in [texts[k] for k in kinds] and len({texts[k] for k in kinds}) == 3:
            break
    opts, key = make_options(rng, (correct, None), [(texts[k], None) for k in kinds])
    code = (f"SLO: доступность {slo_txt.replace('.', ',')} % успешных запросов за {days} {plural(days, 'день', 'дня', 'дней')}\n"
            f"Инцидент 1: полный отказ — {full} мин\n"
            f"Инцидент 2: {p} % запросов с ошибкой 5xx — {c} мин\n"
            f"Инцидент 3: ответы медленнее обычного, без ошибок — {d} мин")
    stem = (f"Сервис «{ctx}», трафик равномерный в течение суток. С начала окна SLO было три инцидента (ниже). "
            "Сколько бюджета ошибок осталось на окно, если мерить его в минутах полного отказа?")
    dec = lambda x: f"{float(x):.2f}".rstrip("0").rstrip(".").replace(".", ",")  # noqa: E731
    expl = (f"Бюджет = (1 − {slo_txt.replace('.', ',')} %) × {days} × 1440 мин = {dec(budget)} мин. "
            f"Израсходовано: {full} + {p} % × {c} = {dec(used)} мин; замедление без ошибок в SLO доступности "
            f"не входит. {correct.capitalize()}.")
    checks = [Check(name="budget", runner="python",
                    program=CHECK.format(slo_num=slo.numerator, slo_den=slo.denominator, days=days, full=full, p=p,
                                         c=c),
                    expect="stdout_equals", expected_stdout=correct, embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         params={"slo": slo_txt, "days": days, "distractors": kinds})
