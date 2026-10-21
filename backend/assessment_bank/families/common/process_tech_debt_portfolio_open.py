"""common.process.tech_debt_portfolio_open — open_answer (Principal): портфель технического долга на квартал.

Дано пять пунктов техдолга с числами: инцидентов в квартал и потерянных часов на инцидент (или замедление
команд), оценка работ в инженерных неделях, у одного — внешний срок (требование регулятора или окончание
поддержки версии), у одного — зависимость от другого. Ёмкость на долг — N инженерных недель за квартал.
Кандидат выбирает, что делать в этом квартале и что явно не делать, обосновывает ценой задержки на неделю
работы (генератор считает опорный порядок: обязательный по сроку пункт, затем по «цене задержки ÷
длительность» с учётом зависимости и ёмкости), объясняет бизнесу и называет метрики. Рубрика 0–4.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, scenario_variant
from assessment_bank.gen_utils import plural

FAMILY_ID = "common.process.tech_debt_portfolio_open"

CONTEXTS = ["платёжный сервис", "маркетплейс", "платформа найма", "онлайн-кинотеатр", "сервис доставки",
            "система учёта для клиник"]

ITEMS = [
    ("flaky", "нестабильные интеграционные тесты: сборка падает без причины"),
    ("deploy", "ручная выкладка по инструкции на 40 шагов"),
    ("schema", "общая таблица заказов, в которую пишут шесть сервисов"),
    ("alerts", "шумные алерты: дежурный получает сотни уведомлений в неделю"),
    ("orm", "устаревшая версия ORM без поддержки, обход утечек памяти перезапусками"),
    ("config", "конфигурация в коде, изменение настройки требует выкладки"),
    ("cache", "самописный кэш без инвалидации, ручная очистка после правок данных"),
    ("logs", "логи без идентификатора запроса, разбор инцидента — по времени"),
]
DEADLINES = [
    ("audit_log", "журнал доступа к персональным данным хранится 30 дней вместо 12 месяцев",
     "требование регулятора о хранении журнала доступа"),
    ("db_eol", "основная СУБД — версия, поддержка которой заканчивается", "окончание поддержки версии СУБД"),
    ("tls_old", "интеграция с платёжным шлюзом по устаревшему протоколу шифрования",
     "платёжная система отключает старый протокол"),
]


def _build(rng, ctx):
    picked = rng.sample(ITEMS, 4)
    rate = rng.choice([3, 4, 5])                      # тыс. ₽ за инженерный час (с налогами), оценка
    cap = rng.choice([8, 10, 12, 14])                 # инженерных недель на долг в квартал
    rows = []
    for key, text in picked:
        inc = rng.choice([2, 4, 6, 9, 12])
        hours = rng.choice([4, 8, 16, 24])
        effort = rng.choice([2, 3, 4, 6, 8])
        rows.append(dict(key=key, text=text, inc=inc, hours=hours, effort=effort))
    dl = rng.randrange(5)
    dkey, dtext, deadline_txt = rng.choice(DEADLINES)
    rows.insert(dl, dict(key=dkey, text=dtext, inc=0, hours=0, effort=0))
    dep_from, dep_to = rng.sample([i for i in range(5) if i != dl], 2)   # dep_from требует dep_to
    weeks_left = rng.choice([8, 10, 12])
    rows[dl]["inc"], rows[dl]["hours"] = rng.choice([1, 2]), rng.choice([2, 4])
    rows[dl]["effort"] = rng.choice([2, 3, 4])
    for r in rows:
        r["cod"] = r["inc"] * r["hours"] * rate / 13            # тыс. ₽ в неделю задержки
        r["cd3"] = r["cod"] / r["effort"]
    # опорный порядок: срок -> по CD3 (зависимость: dep_from только после dep_to) -> пока помещается
    order = [dl] + sorted([i for i in range(5) if i != dl], key=lambda i: -rows[i]["cd3"])
    plan, used = [], 0
    for i in order:
        need = [i]
        if i == dep_from and dep_to not in plan:
            need = [dep_to, i]
        cost = sum(rows[j]["effort"] for j in need if j not in plan)
        if used + cost <= cap:
            for j in need:
                if j not in plan:
                    plan.append(j)
            used += cost
    if dl not in plan:          # срок обязателен — урезаем остальное
        plan, used = [dl], rows[dl]["effort"]
    skip = [i for i in range(5) if i not in plan]
    letters = "АБВГД"
    table = "\n".join(
        f"{letters[i]}. {r['text'][:1].upper() + r['text'][1:]} — {r['inc']} {plural(r['inc'], 'инцидент', 'инцидента', 'инцидентов')} "
        f"в квартал × ≈ {r['hours']} ч потерь; работа ≈ {r['effort']} инж. нед."
        + (f" Внешний срок: {deadline_txt} — через {weeks_left} недель." if i == dl else "")
        + (f" Делать можно только после пункта {letters[dep_to]}." if i == dep_from else "")
        for i, r in enumerate(rows))
    stem = (f"Вы — главный инженер направления «{ctx}». На технический долг в этом квартале выделено "
            f"{cap} инженерных недель (13 недель в квартале, час инженера ≈ {rate} тыс. ₽). Список долга:\n{table}\n\n"
            "Составьте план на квартал: что делаете, в каком порядке и что сознательно откладываете. Обоснуйте "
            "числами (цена задержки, длительность, срок, зависимость), объясните решение руководителю продукта "
            "одним абзацем и назовите, по каким метрикам через квартал поймёте, что вложение окупилось. Ответ — "
            "12–18 предложений.")
    plan_txt = ", ".join(letters[i] for i in plan)
    skip_txt = ", ".join(letters[i] for i in skip) or "—"
    top = max((i for i in range(5) if i != dl), key=lambda i: rows[i]["cd3"])
    criteria = [
        ("deadline", (f"Пункт {letters[dl]} с внешним сроком ({deadline_txt}, {weeks_left} недель) — в плане первым или "
                      f"с датой завершения до срока, независимо от его малой цены задержки; названо, что будет при "
                      f"срыве срока"), 0.2),
        ("economics", (f"Ранжирование числами: цена задержки в неделю = инциденты × часы × ставка ÷ 13 и деление на "
                       f"длительность; наибольшее отношение у пункта {letters[top]} "
                       f"(≈ {fmt_num(rows[top]['cod'], 1)} тыс. ₽ в неделю при {rows[top]['effort']} инж. нед.); "
                       f"расчёт может быть приближённым, но порядок — из него"), 0.25),
        ("constraints", (f"Учтены ёмкость {cap} инж. нед. и зависимость {letters[dep_from]} → после {letters[dep_to]}; "
                         f"опорный план — {plan_txt} ({used} инж. нед.), отложено — {skip_txt}; иной план засчитывается, "
                         f"если он укладывается в ёмкость, соблюдает срок и зависимость и обоснован числами"), 0.2),
        ("communication", ("Объяснение руководителю продукта — в деньгах и сроках (часы дежурств, скорость выкладок, "
                           "риск срыва срока), с явным списком того, что откладывается и почему, без жаргона"), 0.15),
        ("metrics", ("Метрики окупаемости до/после: число инцидентов и часы потерь по каждому пункту, частота и "
                     "длительность выкладок, доля красных сборок, шум алертов; когда пересматривается план"), 0.2),
    ]
    strong = (f"Сначала {letters[dl]}: срок через {weeks_left} недель не переносится, а {rows[dl]['effort']} инж. нед. "
              f"дешевле штрафа и остановки. Дальше считаю цену задержки: инциденты × часы × {rate} тыс. ₽ ÷ 13 — "
              f"например, у {letters[top]} ≈ {fmt_num(rows[top]['cod'], 1)} тыс. ₽ в неделю при {rows[top]['effort']} "
              f"инж. нед., это лучшее отношение. С учётом ёмкости {cap} инж. нед. и того, что {letters[dep_from]} "
              f"делается только после {letters[dep_to]}, план — {plan_txt} ({used} инж. нед.); {skip_txt} "
              f"откладываю на следующий квартал и пишу почему. Руководителю продукта: «мы снимаем ≈ N часов "
              f"дежурств в месяц и риск срыва срока, взамен две фичи уходят на месяц». Через квартал сравниваю "
              f"инциденты и часы потерь по каждому пункту, частоту выкладок и долю красных сборок; если пункт не "
              f"дал эффекта — пересматриваю оценку его цены.")
    medium = (f"Нужно сначала закрыть срочное ({letters[dl]}), потом то, что вызывает больше инцидентов; часть "
              "долга отложить; следить за числом инцидентов.")
    weak = "Технический долг нужно гасить постоянно; выделим 20 % времени и будем делать всё по очереди."
    return dict(stem=stem, criteria=criteria, strong=strong, medium=medium, weak=weak,
                notes=f"Опорный план: {plan_txt}; отложено: {skip_txt}; срок — {letters[dl]}; зависимость {letters[dep_from]}→{letters[dep_to]}.",
                explanation=f"Опорный план {plan_txt} ({used} из {cap} инж. нед.), отложено {skip_txt}.",
                params=dict(items=[r["key"] for r in rows], cap=cap, rate=rate, deadline=dl, dep=[dep_from, dep_to],
                            plan=plan, efforts=[r["effort"] for r in rows], inc=[r["inc"] for r in rows]))


def generate(seed: int):
    return scenario_variant(FAMILY_ID, seed, contexts=CONTEXTS, build=_build)
