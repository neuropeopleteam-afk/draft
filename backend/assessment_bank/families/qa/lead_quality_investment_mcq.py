"""qa.lead.quality_investment_mcq — mcq_concept (Lead): какое одно вложение в качество даст наименьшие затраты на релиз.

Дефекты релиза проходят этапы по порядку: модульные тесты, интеграционные (API), сквозные (e2e), бой. Этап ловит
дошедший до него дефект с вероятностью d; цена исправления растёт по этапам, в бою — с ущербом. Ожидаемые затраты на
релиз = N · Σ P(дошёл до этапа) · d · c + N · P(ушёл в бой) · c_бой + поддержка нового средства (часов на релиз).
Четыре вложения: контрактные тесты (d интеграционных ↑), расширенный e2e (d сквозных ↑, дорогая поддержка),
мутационное тестирование (d модульных ↑), канареечная выкатка (ущерб в бою × f). Ответ — минимум полных затрат.

Варианты ответа — всегда те же четыре вложения (форма вариантов ключ не выдаёт); верное по seed распределено поровну.
Ловушки, заложенные в числа: наибольшая экономия на исправлениях без учёта поддержки и наибольший прирост
вероятности обнаружения ведут к другим вложениям. Ключ проверяется исполнением: программа считает затраты.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import computed_mcq, ru_num
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.lead.quality_investment_mcq"

CONTEXTS = ["мобильный банк", "маркетплейс", "сервис доставки", "страховой кабинет", "онлайн-кинотеатр",
            "сервис бронирования", "платформа онлайн-обучения", "портал поставщиков"]
NAMES = {
    "contract": "контрактные тесты API между сервисами",
    "e2e": "расширенный набор сквозных (e2e) тестов",
    "mutation": "мутационное тестирование для усиления модульных тестов",
    "canary": "канареечная выкатка с автоматическим откатом",
}
ORDER = ["contract", "e2e", "mutation", "canary"]

PROGRAM = '''N = {n}
D = {d!r}        # вероятность поймать дефект, дошедший до этапа
C = {c!r}        # цена исправления на этапе, часов (в бою — с ущербом)
CHANGE = {change!r}   # вложение: (этап или "prod", новое значение, поддержка часов на релиз)
NAMES = {names!r}


def total(d, c):
    reach, cost = 1.0, 0.0
    for stage in ("unit", "api", "e2e"):
        cost += reach * d[stage] * c[stage]
        reach *= 1 - d[stage]
    return N * (cost + reach * c["prod"])


best = None
for name, (stage, value, upkeep) in CHANGE.items():
    d, c = dict(D), dict(C)
    if stage == "prod":
        c["prod"] = value
    else:
        d[stage] = value
    t = total(d, c) + upkeep
    if best is None or t < best[0]:
        best = (t, name)
print(NAMES[best[1]])
'''

STAGE = {"contract": "api", "e2e": "e2e", "mutation": "unit", "canary": "prod"}


def _total(n, d, c):
    reach, cost = 1.0, 0.0
    for st in ("unit", "api", "e2e"):
        cost += reach * d[st] * c[st]
        reach *= 1 - d[st]
    return n * (cost + reach * c["prod"])


def _apply(d, c, name, value):
    d2, c2 = dict(d), dict(c)
    if STAGE[name] == "prod":
        c2["prod"] = value
    else:
        d2[STAGE[name]] = value
    return d2, c2


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    want = ORDER[seed % 4]
    for _ in range(20000):
        n = rng.choice([30, 40, 60, 80])
        d = {"unit": rng.choice([0.3, 0.4, 0.5]), "api": rng.choice([0.3, 0.4, 0.5]),
             "e2e": rng.choice([0.3, 0.4, 0.5])}
        c = {"unit": 1, "api": rng.choice([3, 4]), "e2e": rng.choice([6, 8, 10]), "prod": rng.choice([30, 40, 60])}
        delta = {"contract": rng.choice([0.15, 0.2, 0.25]), "e2e": rng.choice([0.15, 0.2, 0.25]),
                 "mutation": rng.choice([0.1, 0.15, 0.2])}
        f = rng.choice([0.4, 0.5, 0.6])
        upkeep = {"contract": rng.choice([20, 30, 40, 50]), "e2e": rng.choice([40, 60, 80, 100]),
                  "mutation": rng.choice([10, 20, 30, 40]), "canary": rng.choice([30, 40, 60, 80])}
        value = {k: round(d[STAGE[k]] + delta[k], 2) for k in delta}
        value["canary"] = round(c["prod"] * f, 1)
        base = _total(n, d, c)
        fix = {k: _total(n, *_apply(d, c, k, value[k])) for k in ORDER}
        tot = {k: fix[k] + upkeep[k] for k in ORDER}
        srt = sorted(ORDER, key=lambda k: tot[k])
        if srt[0] != want or tot[srt[1]] - tot[srt[0]] < 3:
            continue
        gross = max(ORDER, key=lambda k: base - fix[k])
        if gross == want or base - fix[gross] - (base - fix[want]) < 3:
            continue
        if tot[want] >= base:   # вложение должно окупаться
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось построить вариант")
    ru = {"unit": "модульные тесты", "api": "интеграционные тесты API", "e2e": "сквозные (e2e) тесты"}
    rows = ["этап | ловит дефект, дошедший до этапа | цена исправления, ч"]
    rows += [f"{ru[s]} | {ru_num(round(100 * d[s]))} % | {c[s]}" for s in ("unit", "api", "e2e")]
    rows.append(f"бой (с ущербом и разбором) | — | {c['prod']}")
    rows.append("вложение | эффект | поддержка, ч на релиз")
    eff = {"contract": f"интеграционные ловят {ru_num(round(100 * value['contract']))} %",
           "e2e": f"сквозные ловят {ru_num(round(100 * value['e2e']))} %",
           "mutation": f"модульные ловят {ru_num(round(100 * value['mutation']))} %",
           "canary": f"цена дефекта в бою — {ru_num(value['canary'])} ч"}
    rows += [f"{NAMES[k]} | {eff[k]} | {upkeep[k]}" for k in ORDER]
    code = "\n".join(rows)
    teams = rng.choice([4, 6, 8, 12, 15])
    cadence = rng.choice(["раз в неделю", "раз в две недели", "дважды в неделю", "раз в месяц"])
    intro = rng.choice([
        f"{ctx.capitalize()}, {teams} команд, релиз {cadence}: в релиз в среднем попадает {n} дефектов.",
        f"{ctx.capitalize()} выпускает релиз {cadence} силами {teams} команд; по статистике прошлых кварталов в "
        f"каждом релизе около {n} дефектов.",
        f"Руководитель качества ({ctx}, {teams} команд) разбирает статистику: релиз {cadence}, в среднем {n} "
        f"дефектов на релиз.",
    ])
    ask = rng.choice([
        "Какое вложение даст наименьшие ожидаемые затраты на релиз — исправление дефектов вместе с поддержкой?",
        "Какое вложение выбрать, чтобы ожидаемые затраты на релиз (исправление дефектов плюс поддержка нового "
        "средства) были наименьшими?",
        "Какое одно вложение минимизирует полные ожидаемые затраты на релиз с учётом поддержки?",
    ])
    stem = (f"{intro} Каждый дефект проходит этапы по порядку, этап ловит дошедший до него дефект с указанной "
            f"вероятностью, не пойманный всеми — уходит в бой. На квартал есть ресурс на одно вложение в качество "
            f"(таблица: эффект и поддержка в часах на релиз). {ask}")
    parts = "; ".join(f"{NAMES[k]} — {ru_num(round(fix[k], 1))} + {upkeep[k]} = {ru_num(round(tot[k], 1))} ч"
                      for k in ORDER)
    why = (f"Ожидаемые затраты: {n} · Σ (доля дошедших до этапа · вероятность поймать · цена) + доля ушедших в бой · "
           f"цена в бою. Сейчас — {ru_num(round(base, 1))} ч на релиз. С вложением (исправление + поддержка): {parts}. "
           f"Минимум — «{NAMES[want]}». Наибольшая экономия на исправлениях без учёта поддержки — у «{NAMES[gross]}», "
           f"но поддержка съедает выигрыш. Для Lead: вложения в качество сравниваются по полным затратам на релиз, "
           f"а не по росту доли пойманных дефектов на одном этапе.")
    change = {k: (STAGE[k], value[k], upkeep[k]) for k in ORDER}
    program = PROGRAM.format(n=n, d=d, c=c, change=change, names=NAMES)
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=NAMES[want],
                        distractors=[NAMES[k] for k in ORDER if k != want], program=program, why=why, context=ctx,
                        code=code, language="text", max_ratio=1.6,
                        note="Программа считает ожидаемые затраты на релиз для каждого вложения по тем же числам.",
                        params={"n": n, "good": want})
