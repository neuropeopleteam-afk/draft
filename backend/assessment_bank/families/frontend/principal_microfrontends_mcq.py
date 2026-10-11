"""frontend.strategy.principal_microfrontends_mcq — mcq_concept (Principal, короткое): как делить фронтенд между командами.

Несколько команд меняют один фронтенд. Четыре варианта организации:
  * единое приложение и общий релизный поезд раз в R дней (изменение ждёт в среднем R / 2 дня; без доплаты);
  * монорепозиторий с независимой сборкой пакетов и ежедневным общим выпуском (ожидание ½ дня; доплата P_m);
  * микрофронтенды, подключаемые во время выполнения (независимые выкладки, ожидание ≈ 0,1 дня; доплата P_f;
    дублирующиеся зависимости добавляют Δ_f мс к LCP всех страниц);
  * отдельные приложения по разделам (ожидание ≈ 0; доплата P_a; переход между разделами — полная перезагрузка:
    доля f сессий получает +Δ_a мс, то есть в среднем f · Δ_a мс).
Цена ожидания — d тыс. ₽ за день задержки одного изменения (C изменений в год); каждые 100 мс LCP стоят x % выручки W.
Годовая цена = C · ожидание · d + доплата + потеря выручки от LCP.

Ловушки: «максимальная независимость команд» (отдельные приложения), «без доплаты», расчёт без цены LCP.
Верный вариант распределён поровну по четырём и отличается хотя бы от двух ловушек (если верна сама ловушка —
хотя бы от одной). Ключ проверяется исполнением: программа проигрывает год по дням (изменения поступают
равномерно, выпуск — по расписанию варианта), считает суммарное ожидание и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "frontend.strategy.principal_microfrontends_mcq"

CONTEXTS = ["маркетплейс", "интернет-банк", "сервис путешествий", "онлайн-кинотеатр", "платформа объявлений",
            "сервис доставки", "личный кабинет оператора связи"]
NAMES = {"mono": "единое приложение и общий релизный поезд",
         "monorepo": "монорепозиторий, независимая сборка, ежедневный выпуск",
         "federation": "микрофронтенды, подключаемые во время выполнения",
         "apps": "отдельные приложения по разделам"}
ORDER = ["mono", "monorepo", "federation", "apps"]

PROGRAM = """opts = __OPTS__
C, d, W, x = {C}, {d}, {W}, {x}
plans = {plans!r}     # подпись -> (интервал выпуска в днях или 0, доплата млн ₽, добавка к LCP мс)
cost = {{}}
for label, (period, extra, add_ms) in plans.items():
    wait_days = 0.0
    steps = 1000                                  # изменения поступают равномерно внутри интервала выпуска
    if period:
        for i in range(steps):
            arrived = (i + 0.5) / steps * period
            wait_days += period - arrived         # ждёт ближайшего выпуска в конце интервала
        wait_days /= steps
    else:
        wait_days = {fast!r}[label]
    cost[label] = C * wait_days * d / 1000 + extra + W * x / 100 * add_ms / 100
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(dct, rel=0.04):
    v = sorted(dct.values())
    return min(dct, key=dct.get) if v[1] - v[0] >= rel * v[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        teams = rng.choice([4, 6, 8, 12])
        C = teams * rng.choice([150, 250, 400])              # изменений в год
        d = rng.choice([5, 10, 20, 40])                      # тыс. ₽ за день задержки изменения
        W = rng.choice([1000, 3000, 6000, 12000])            # млн ₽ выручки в год
        x = rng.choice([0.5, 1.0])                           # % выручки за 100 мс LCP
        R = rng.choice([7, 14])
        P = {"mono": 0, "monorepo": rng.choice([8, 12, 20]), "federation": rng.choice([15, 25, 40]),
             "apps": rng.choice([10, 20, 30])}
        dfed = rng.choice([80, 150, 250])                    # мс к LCP от дублирующихся зависимостей
        f, dnav = rng.choice([0.2, 0.3, 0.5]), rng.choice([600, 900, 1200])
        add = {"mono": 0, "monorepo": 0, "federation": dfed, "apps": round(f * dnav)}
        wait = {"mono": R / 2, "monorepo": 0.5, "federation": 0.1, "apps": 0.0}
        full = {k: C * wait[k] * d / 1000 + P[k] + W * x / 100 * add[k] / 100 for k in ORDER}
        good = _argmin(full)
        if good != target:
            continue
        no_lcp = _argmin({k: C * wait[k] * d / 1000 + P[k] for k in ORDER})
        if no_lcp is None:
            continue
        traps = ("apps", "mono", no_lcp)
        if sum(t != good for t in traps) >= (1 if good in ("apps", "mono") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    rd = plural(R, "день", "дня", "дней")
    tw = plural(teams, "команда", "команды", "команд")
    rows = [
        f"• {NAMES['mono'][0].upper() + NAMES['mono'][1:]}: выпуск раз в {R} {rd}; без доплаты.",
        f"• {NAMES['monorepo'][0].upper() + NAMES['monorepo'][1:]}: изменение ждёт в среднем полдня; доплата "
        f"{P['monorepo']} млн ₽ в год (сборочная инфраструктура).",
        f"• {NAMES['federation'][0].upper() + NAMES['federation'][1:]}: независимые выкладки, ожидание ≈ 0,1 дня; "
        f"доплата {P['federation']} млн ₽ в год; дублирующиеся зависимости добавляют {dfed} мс к LCP всех страниц.",
        f"• {NAMES['apps'][0].upper() + NAMES['apps'][1:]}: выкладка без ожидания; доплата {P['apps']} млн ₽ в год; "
        f"переход между разделами — полная перезагрузка, она добавляет {dnav} мс в {fmt_num(100 * f, 0)} % сессий.",
    ]
    intro = rng.choice([
        f"Вы — главный инженер фронтенда; продукт — {ctx}. Над одним фронтендом работают {teams} {tw}, и "
        f"изменения ждут общего выпуска.",
        f"В продукте «{ctx}» фронтенд делят {teams} {tw}; очередь изменений к выпуску растёт, и решение об "
        f"организации — за вами как за главным инженером фронтенда.",
        f"Руководство продукта «{ctx}» ({teams} {tw} на одном фронтенде) просит главного инженера фронтенда "
        f"выбрать, как разделить приложение.",
    ])
    stem = (f"{intro} Изменений ≈ {fmt_num(C, 0)} в год, день задержки одного изменения стоит ≈ {d} тыс. ₽ (оценка "
            f"продукта). Выручка ≈ {fmt_num(W, 0)} млн ₽ в год, каждые 100 мс LCP стоят {fmt_num(x, 1)} % выручки. "
            f"Изменения поступают равномерно. Варианты:\n" + "\n".join(rows) +
            "\n\nКакой вариант даёт минимальную годовую цену (ожидание изменений, доплата и потеря выручки от LCP)?")
    expl = (f"Цена = изменения × среднее ожидание × цена дня + доплата + выручка × {fmt_num(x, 1)} % × добавка LCP / 100 мс; "
            f"у поезда раз в {R} {rd} среднее ожидание {fmt_num(R / 2, 1)} дня. Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Без цены LCP вышло бы: {NAMES[no_lcp]}.")
    program = PROGRAM.format(C=C, d=d, W=W, x=x,
                             plans={NAMES[k]: (R if k == "mono" else 0, P[k], add[k]) for k in ORDER},
                             fast={NAMES[k]: wait[k] for k in ORDER if k != "mono"})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"teams": teams, "C": C, "d": d, "W": W, "x": x, "R": R, "good": good, "no_lcp": no_lcp,
                               "dfed": dfed, "f": f, "dnav": dnav, **{f"P_{k}": P[k] for k in ORDER}},
                       note="Ответ проверяется программой: равномерное поступление изменений и расписание выпусков.")
