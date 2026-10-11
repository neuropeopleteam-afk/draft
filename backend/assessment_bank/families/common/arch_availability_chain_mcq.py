"""common.arch.availability_chain_mcq — mcq_concept (Lead): доступность цепочки зависимостей.

Запрос проходит через сам сервис и две синхронные обязательные зависимости (последовательно), пару реплик
базы с автоматическим переключением (параллельно: достаточно одной живой) и одну необязательную
зависимость с запасным ответом (её отказ запрос не роняет). Нужно оценить ожидаемую недоступность за
30 дней. Ключ: A = s·a·b·(1 − (1 − r)²), недоступность — (1 − A)·43 200 мин.

Дистракторы — типичные ошибки одной числовой формы:
  * optional_in_series — необязательная зависимость учтена последовательно;
  * replicas_in_series — реплики перемножены как последовательные (r²);
  * single_replica — резервирование не учтено (одна реплика r).
Ключ проверяется исполнением: программа-модель перебирает все 2⁶ состояний компонентов (жив/упал) с их
вероятностями, считает долю состояний, где запрос успешен, и печатает букву совпавшего варианта.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq, well_separated
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.arch.availability_chain_mcq"

CONTEXTS = [
    ("оформление заказа", "сервис цен", "сервис остатков", "рекомендации «с этим покупают»"),
    ("отклик на вакансию", "сервис профилей", "сервис антифрода", "подсказки похожих вакансий"),
    ("бронирование номера", "сервис тарифов", "платёжный шлюз", "отзывы об отеле"),
    ("перевод между счетами", "сервис лимитов", "сервис курсов валют", "персональные предложения"),
    ("запись к врачу", "расписание врачей", "сервис уведомлений", "карта клиник"),
]
MONTH_MIN = 30 * 24 * 60

PROGRAM = """from fractions import Fraction
from itertools import product
comp = {comp}
names = list(comp)
avail = Fraction(0)
for state in product((True, False), repeat=len(names)):
    up = dict(zip(names, state))
    pr = Fraction(1)
    for n in names:
        pr *= comp[n] if up[n] else 1 - comp[n]
    ok = up["svc"] and up["dep1"] and up["dep2"] and (up["db1"] or up["db2"])   # optional не обязателен
    if ok:
        avail += pr
down = float((1 - avail) * {month})
opts = __OPTS__
def val(t):
    return float(t.split("≈ ")[1].split(" мин")[0].replace(" ", "").replace(",", "."))
hit = [k for k, t in opts.items() if abs(val(t) - down) <= max(0.051 * down, 0.6)]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _p(s: str) -> Fraction:
    return Fraction(s.replace(",", ".")) / 100


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    flow, dep1, dep2, opt = rng.choice(CONTEXTS)
    for _ in range(400):
        s, a, b = rng.choice(["99,95", "99,9"]), rng.choice(["99,9", "99,8", "99,95"]), rng.choice(["99,9", "99,5", "99,8"])
        r, c = rng.choice(["99", "99,5", "98", "99,9"]), rng.choice(["99", "98", "97", "99,5"])
        S, A, B, R, C = map(_p, (s, a, b, r, c))
        good = S * A * B * (1 - (1 - R) ** 2)
        vals = {"good": good, "optional_in_series": good * C, "replicas_in_series": S * A * B * R * R,
                "single_replica": S * A * B * R}
        down = {k: float((1 - v) * MONTH_MIN) for k, v in vals.items()}
        if well_separated(list(down.values()), 0.15):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    text = {k: f"≈ {fmt_num(v, 0)} мин за 30 дней" for k, v in down.items()}
    stem = (f"Путь «{flow}»: запрос обрабатывает сам сервис (доступность {s} %), он синхронно и последовательно "
            f"вызывает «{dep1}» ({a} %) и «{dep2}» ({b} %) и читает из базы — две реплики по {r} % с автоматическим "
            f"мгновенным переключением (достаточно одной живой). Ещё он вызывает «{opt}» ({c} %), но при её отказе "
            f"отдаёт ответ без этого блока. Отказы компонентов независимы. Сколько в среднем за 30 дней путь будет "
            f"недоступен (доля неуспешных запросов, пересчитанная в минуты)?")
    comp = {"svc": S, "dep1": A, "dep2": B, "db1": R, "db2": R, "optional": C}
    program = PROGRAM.format(comp={k: f"Fraction({v.numerator}, {v.denominator})" for k, v in comp.items()},
                             month=MONTH_MIN).replace("'Fraction(", "Fraction(").replace(")'", ")")
    expl = (f"Последовательно перемножаются сервис, «{dep1}», «{dep2}» и база; база из двух реплик недоступна, только "
            f"если упали обе: 1 − (1 − {r} %)². Зависимость «{opt}» с запасным ответом в произведение не входит. Итог ≈ "
            f"{fmt_num(down['good'], 0)} мин. Если учесть «{opt}» последовательно — {fmt_num(down['optional_in_series'], 0)} "
            f"мин; если перемножить реплики как последовательные — {fmt_num(down['replicas_in_series'], 0)} мин; не учесть "
            f"резерв — {fmt_num(down['single_replica'], 0)} мин.")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=flow, stem=stem, good=text["good"],
                       distractors=[text["optional_in_series"], text["replicas_in_series"], text["single_replica"]],
                       program=program, explanation=expl,
                       params={"s": s, "a": a, "b": b, "r": r, "c": c, "down_min": round(down["good"], 2)},
                       note="Ответ проверяется программой-моделью: перебор всех состояний компонентов (жив/упал) "
                            "с вероятностями.")
