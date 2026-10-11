"""common.strategy.principal_sequence_cod_mcq — mcq_concept (Principal, короткое): порядок инициатив по цене задержки.

Одна команда делает пять инициатив по очереди. У каждой — длительность (недели) и цена задержки (тыс. ₽ в неделю,
пока инициатива не сделана); одна инициатива зависит от другой (начать можно только после неё). Вопрос — какой
порядок даёт минимальные суммарные потери от задержки Σ cᵢ · Tᵢ (Tᵢ — неделя завершения).

Верный ответ — оптимум среди всех допустимых порядков (перебор 120 перестановок с учётом зависимости). Ловушки —
три «правила большого пальца» с одинаковой починкой зависимости (предшественник ставится прямо перед зависимой):
«сначала самые дорогие», «сначала самые короткие» и WSJF по отдельности (cᵢ / dᵢ без учёта того, что зависимая
тянет за собой предшественника; верно — сравнивать пару по суммарному отношению Σc / Σd). Генератор подбирает числа
так, что все три ловушки допустимы, различны и хуже оптимума не меньше чем на 4 %.
Варианты ответа — перестановки одних и тех же названий (одна длина и один набор слов — форма ключ не выдаёт).
Ключ проверяется исполнением: программа проигрывает каждый показанный порядок по неделям, проверяет зависимость
и печатает букву минимума.
"""
from __future__ import annotations

from itertools import permutations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "common.strategy.principal_sequence_cod_mcq"

CONTEXTS = {
    "интернет-магазин": ["быстрая оплата", "новый каталог", "программа лояльности", "возвраты онлайн",
                         "рекомендации", "доставка в пункты выдачи", "единая корзина"],
    "банковское приложение": ["переводы по номеру", "кредитный конвейер", "новый вход", "кэшбэк",
                              "открытие вклада онлайн", "антифрод платежей", "выписки в один клик"],
    "логистическая платформа": ["маршрутизация курьеров", "трекинг посылок", "тарифный калькулятор",
                                "личный кабинет отправителя", "сканирование на складе", "биллинг", "уведомления"],
    "платформа онлайн-обучения": ["оплата курсов", "проверка домашних заданий", "видеоплеер", "сертификаты",
                                  "расписание вебинаров", "рекомендации курсов", "мобильный офлайн-режим"],
    "сервис записи к врачу": ["онлайн-запись", "напоминания пациентам", "электронная карта", "телемедицина",
                              "оплата приёма", "расписание врачей", "отзывы"],
    "маркетплейс услуг": ["безопасная сделка", "поиск исполнителей", "чат с заказчиком", "рейтинг исполнителей",
                          "календарь заказов", "выплаты исполнителям", "споры и арбитраж"],
}

PROGRAM = """opts = __OPTS__
jobs = {jobs!r}          # название -> (длительность, нед.; цена задержки, тыс. ₽ в неделю)
after = {after!r}        # зависимая -> предшественник
best, best_cost = None, None
for letter, text in sorted(opts.items()):
    order = text.split(" → ")
    week, cost, done = 0, 0, set()
    ok = sorted(order) == sorted(jobs)
    for name in order:
        if name in after and after[name] not in done:
            ok = False
        for _ in range(jobs[name][0]):          # неделя за неделей: пока не сделано — копится цена задержки
            week += 1
            cost += sum(jobs[n][1] for n in jobs if n not in done)
        done.add(name)
    if ok and (best_cost is None or cost < best_cost):
        best, best_cost = letter, cost
print(best)
"""


def _cost(order, jobs):
    t, s = 0, 0
    for n in order:
        t += jobs[n][0]
        s += jobs[n][1] * t
    return s


def _repair(order, dep, pre):
    """Предшественник ставится прямо перед зависимой, если стоит после неё."""
    o = list(order)
    if o.index(pre) > o.index(dep):
        o.remove(pre)
        o.insert(o.index(dep), pre)
    return tuple(o)


def _feasible(order, dep, pre):
    return order.index(pre) < order.index(dep)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CONTEXTS))
    for _ in range(20000):
        names = rng.sample(CONTEXTS[ctx], 5)
        jobs = {n: (rng.randint(1, 8), rng.choice([20, 30, 40, 50, 60, 80, 100, 120, 150, 200])) for n in names}
        dep, pre = rng.sample(names, 2)
        feas = [p for p in permutations(names) if _feasible(p, dep, pre)]
        costs = {p: _cost(p, jobs) for p in feas}
        ranked = sorted(costs, key=costs.get)
        opt = ranked[0]
        if costs[ranked[1]] < costs[opt] * 1.01:
            continue
        by_value = _repair(sorted(names, key=lambda n: (-jobs[n][1], n)), dep, pre)
        by_short = _repair(sorted(names, key=lambda n: (jobs[n][0], n)), dep, pre)
        by_ratio = _repair(sorted(names, key=lambda n: (-jobs[n][1] / jobs[n][0], n)), dep, pre)
        traps = [by_value, by_short, by_ratio]
        if len({opt, *traps}) != 4 or any(costs[t] < costs[opt] * 1.04 for t in traps):
            continue
        # зависимость должна мешать: без неё оптимум другой (иначе задача — обычный WSJF)
        free = min(permutations(names), key=lambda p: _cost(p, jobs))
        if _feasible(free, dep, pre):
            continue
        break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    rows = "\n".join(f"• «{n}» — {jobs[n][0]} {plural(jobs[n][0], 'неделя', 'недели', 'недель')}, цена задержки "
                     f"{jobs[n][1]} тыс. ₽ в неделю" for n in names)
    intro = rng.choice([
        f"Вы — главный инженер продукта «{ctx}». Одна платформенная команда может вести только одну инициативу за раз.",
        f"В продукте «{ctx}» на квартал пять инициатив, и все требуют одной и той же платформенной команды "
        f"(параллельно не получится). Порядок утверждаете вы как главный инженер.",
        f"Совет продукта «{ctx}» просит главного инженера предложить порядок пяти инициатив для одной команды, "
        f"которая делает их строго по очереди.",
    ])
    stem = (f"{intro} Цена задержки — сколько продукт теряет каждую неделю, пока инициатива не сделана (оценка "
            f"финансового отдела):\n{rows}\nИнициативу «{dep}» можно начать только после завершения инициативы «{pre}».\n\n"
            "Какой порядок даёт минимальные суммарные потери от задержки за всё время работ?")
    fmt = lambda p: " → ".join(p)
    expl = (f"Потери = Σ цена задержки × неделя завершения. Оптимум перебором допустимых порядков: {fmt(opt)} — "
            f"{fmt_num(costs[opt], 0)} тыс. ₽. Ловушки: «сначала дорогие» — {fmt_num(costs[by_value], 0)}, "
            f"«сначала короткие» — {fmt_num(costs[by_short], 0)}, WSJF по отдельности с починкой зависимости — "
            f"{fmt_num(costs[by_ratio], 0)} тыс. ₽. Пару «{pre}» → «{dep}» нужно сравнивать с остальными по суммарному "
            f"отношению Σc / Σd, а не по отношению одной зависимой.")
    program = PROGRAM.format(jobs=jobs, after={dep: pre})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=fmt(opt),
                       distractors=[fmt(t) for t in traps], program=program, explanation=expl,
                       params={"jobs": "; ".join(f"{n}:{d}/{c}" for n, (d, c) in jobs.items()), "dep": dep,
                               "pre": pre, "opt_cost": costs[opt]},
                       note="Ответ проверяется программой: понедельный проигрыш каждого показанного порядка.")
