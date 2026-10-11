"""common.arch.availability_chain_mcq — mcq_concept (Lead): доступность цепочки зависимостей.

Запрос проходит через сам сервис и две синхронные обязательные зависимости (последовательно), пару реплик
базы с автоматическим переключением (параллельно: достаточно одной живой) и одну необязательную
зависимость с запасным ответом (её отказ запрос не роняет). Нужно оценить ожидаемую недоступность за
30 дней. Ключ: A = s·a·b·(1 − (1 − r)²), недоступность — (1 − A)·43 200 мин.

Дистракторы — типичные ошибки одной числовой формы, три из пяти (версия 2: число ловушек с меньшей
недоступностью, чем у ключа, равновероятно 0, 1 или 2 — ключ не всегда наименьший):
  больше недоступности —
  * optional_in_series — необязательная зависимость учтена последовательно;
  * replicas_in_series — реплики перемножены как последовательные (r²);
  * single_replica — резервирование не учтено (одна реплика r);
  меньше недоступности —
  * weakest_link — доступность цепочки принята равной доступности самого слабого обязательного звена;
  * no_service — забыт сам сервис: перемножены только зависимости и база.
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
    n_below = rng.choice([0, 1, 2])          # сколько ловушек с меньшей недоступностью — до подбора чисел
    for _ in range(400):
        s, a, b = rng.choice(["99,95", "99,9"]), rng.choice(["99,9", "99,8", "99,95"]), rng.choice(["99,9", "99,5", "99,8"])
        r, c = rng.choice(["99", "99,5", "98", "99,9"]), rng.choice(["99", "98", "97", "99,5"])
        S, A, B, R, C = map(_p, (s, a, b, r, c))
        pair = 1 - (1 - R) ** 2
        good = S * A * B * pair
        worse = {"optional_in_series": good * C, "replicas_in_series": S * A * B * R * R,
                 "single_replica": S * A * B * R}
        better = {"weakest_link": min(S, A, B, pair), "no_service": A * B * pair}
        traps = rng.sample(sorted(better), n_below) + rng.sample(sorted(worse), 3 - n_below)
        alld = {k: float((1 - v) * MONTH_MIN) for k, v in ({"good": good} | worse | better).items()}
        down = {k: alld[k] for k in ["good", *traps]}
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
    why = {"optional_in_series": f"зависимость «{opt}» учтена последовательно — {fmt_num(alld['optional_in_series'], 0)} мин",
           "replicas_in_series": (f"реплики перемножены как последовательные — "
                                  f"{fmt_num(alld['replicas_in_series'], 0)} мин"),
           "single_replica": f"резерв базы не учтён — {fmt_num(alld['single_replica'], 0)} мин",
           "weakest_link": (f"доступность цепочки принята равной самому слабому звену — "
                            f"{fmt_num(alld['weakest_link'], 0)} мин: недоступности звеньев складываются"),
           "no_service": f"забыт сам сервис ({s} %) — {fmt_num(alld['no_service'], 0)} мин"}
    expl = (f"Последовательно перемножаются сервис, «{dep1}», «{dep2}» и база; база из двух реплик недоступна, "
            f"только если упали обе: 1 − (1 − {r} %)². Зависимость «{opt}» с запасным ответом в произведение не "
            f"входит. Итог ≈ {fmt_num(down['good'], 0)} мин. Ловушки: " + "; ".join(why[k] for k in sorted(traps)) + ".")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=flow, stem=stem, good=text["good"],
                       distractors=[text[k] for k in traps],
                       program=program, explanation=expl,
                       params={"s": s, "a": a, "b": b, "r": r, "c": c, "down_min": round(down["good"], 2),
                               "traps": traps},
                       note="Ответ проверяется программой-моделью: перебор всех состояний компонентов (жив/упал) "
                            "с вероятностями.")
