"""backend.strategy.principal_data_freshness_mcq — mcq_concept (Principal, короткое): насколько свежими держать данные.

Решения сервиса (цены, остатки, антифрод) опираются на данные, которые обновляет конвейер. Событий E в сутки,
каждое теряет ℓ ₽ за каждый час, пока оно не попало в данные. Четыре варианта:
  * ночная пакетная загрузка — раз в 24 ч, обработка P_n ч; инфраструктура I_n;
  * ежечасные пакеты — раз в час, обработка P_h ч; I_h;
  * потоковая обработка — задержка ≈ s минут; I_s и дежурства O_s;
  * поток изменений (CDC) в хранилище — задержка ≈ c минут; I_c.
Задержка события = ожидание ближайшего запуска после события + обработка. Годовая цена = инфраструктура и
дежурства + E · 365 · ℓ · средняя задержка (ч).

Ловушки: «максимальная свежесть» (поток), «дешевле всего» (ночью) и расчёт без цены дежурств. Верный вариант
распределён поровну по четырём и отличается хотя бы от двух ловушек (если верна сама ловушка — хотя бы от одной).
Ключ проверяется исполнением: программа раскладывает события суток по минутам, для каждого варианта находит момент,
когда событие попадёт в данные, и печатает букву минимума цены.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.strategy.principal_data_freshness_mcq"

CONTEXTS = [("динамические цены", "изменение рыночной цены или спроса"), ("остатки на складах", "продажа или приход"),
            ("антифрод", "подозрительная операция"), ("рекомендации", "действие пользователя"),
            ("лимиты по картам", "операция по карте"), ("тарифы доставки", "изменение загрузки курьеров"),
            ("кредитный скоринг", "новая выписка клиента")]
NAMES = {"nightly": "ночная пакетная загрузка", "hourly": "ежечасные пакеты", "stream": "потоковая обработка",
         "cdc": "поток изменений (CDC) в хранилище"}
ORDER = ["nightly", "hourly", "stream", "cdc"]

PROGRAM = """opts = __OPTS__
E, l = {E}, {l}
plans = {plans!r}     # подпись -> (период запусков, мин; обработка, мин; цена в год, млн ₽)
cost = {{}}
for label, (period, proc, price) in plans.items():
    total = 0.0
    for minute in range(1440):                     # события равномерно по суткам, на середине минуты
        t = minute + 0.5
        start = (int(t // period) + 1) * period if period > 0 else t   # ближайший запуск после события
        total += start - t + proc
    avg_h = total / 1440 / 60
    cost[label] = price + E * 365 * l * avg_h / 1e6
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, ev = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(80000):
        E = rng.choice([1_000, 5_000, 20_000, 100_000, 500_000])
        l = rng.choice([0.1, 0.2, 0.5, 1, 2, 5])
        P_n, P_h = rng.choice([60, 120, 180]), rng.choice([10, 15, 20])
        s_min, c_min = rng.choice([1, 2]), rng.choice([5, 10, 15])
        I_n = rng.choice([1, 2, 3])
        I_h = I_n + rng.choice([1, 2, 4])
        I_c = I_h + rng.choice([1, 2, 4])
        I_s = I_h + rng.choice([2, 4, 8])
        O_s = rng.choice([2, 4, 8])
        plans = {"nightly": (1440, P_n, I_n), "hourly": (60, P_h, I_h), "stream": (0, s_min, I_s + O_s),
                 "cdc": (0, c_min, I_c)}
        delay = {k: (p / 2 if p else 0) + pr for k, (p, pr, _) in plans.items()}      # минуты
        full = {k: plans[k][2] + E * 365 * l * delay[k] / 60 / 1e6 for k in ORDER}
        good = _argmin(full)
        if good != target:
            continue
        no_ops = dict(full, stream=full["stream"] - O_s)
        no_ops_best = _argmin(no_ops)
        if no_ops_best is None:
            continue
        traps = ("stream", "nightly", no_ops_best)
        if sum(t != good for t in traps) >= (1 if good in ("stream", "nightly") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['nightly'])}: раз в сутки, обработка {P_n} мин; {I_n} млн ₽ в год.",
            f"• {cap(NAMES['hourly'])}: раз в час, обработка {P_h} мин; {I_h} млн ₽ в год.",
            f"• {cap(NAMES['stream'])}: событие попадает в данные через ≈ {s_min} мин; {I_s} млн ₽ в год и "
            f"круглосуточные дежурства {O_s} млн ₽ в год.",
            f"• {cap(NAMES['cdc'])}: событие попадает в данные через ≈ {c_min} мин; {I_c} млн ₽ в год, дежурства "
            f"не нужны."]
    intro = rng.choice([
        f"Вы — главный инженер. Данные сервиса «{ctx}» обновляются слишком редко, и нужно выбрать конвейер.",
        f"Для сервиса «{ctx}» архитектурный совет выбирает, как обновлять данные; решение — за вами как за главным "
        f"инженером.",
        f"Команда сервиса «{ctx}» просит более свежие данные; главному инженеру нужно выбрать конвейер на год.",
    ])
    stem = (f"{intro} Событий («{ev}») ≈ {fmt_num(E, 0)} в сутки, равномерно по времени. Пока событие не попало в "
            f"данные, решения по нему ошибаются: ≈ {fmt_num(l, 1)} ₽ за каждый час задержки на событие. Задержка = "
            f"ожидание ближайшего запуска после события + обработка. Варианты:\n" + "\n".join(rows) +
            "\n\nКакой вариант даёт минимальную годовую цену (инфраструктура, дежурства и потери от задержки)?")
    expl = ("Средняя задержка = половина периода запусков + обработка (у потоковых — только их задержка); цена = "
            "инфраструктура + дежурства + события × 365 × ℓ × задержка (ч). Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Без цены дежурств вышло бы: {NAMES[no_ops_best]}.")
    program = PROGRAM.format(E=E, l=l, plans={NAMES[k]: plans[k] for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"E": E, "l": l, "P_n": P_n, "P_h": P_h, "s": s_min, "c": c_min, "I_n": I_n, "I_h": I_h,
                               "I_s": I_s, "I_c": I_c, "O_s": O_s, "good": good, "no_ops": no_ops_best},
                       note="Ответ проверяется программой: события суток по минутам и момент попадания в данные.")
