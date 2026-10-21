"""frontend.perf.lp3_defer_modules_tbt_output — predict_output: минимум модулей, которые надо отложить ради TBT.

Трасса загрузки: длинные задачи главного потока между первой отрисовкой и готовностью к вводу, каждая — сумма
исполнения модулей. Блокирующее время (TBT) = Σ max(0, длительность задачи − 50 мс). Отложенный модуль (динамический
импорт после готовности) убирает своё время из задачи. Модули первого экрана откладывать нельзя. Вопрос — наименьшее
число модулей, чтобы TBT уложился в бюджет. Решение — перебор: жадный выбор «самый тяжёлый модуль» не всегда
минимален, потому что задачу короче 50 мс укорачивать бесполезно. Ловушки: суммировать длительности задач вместо
превышения над 50 мс; откладывать модули, не входящие в окно; жадный выбор.
"""
from __future__ import annotations

from itertools import combinations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.perf.lp3_defer_modules_tbt_output"
PAGES = ["Карточка товара", "Лента новостей", "Поиск", "Личный кабинет", "Оформление заказа", "Вакансия",
         "Дашборд аналитики"]
MODS = ["чат поддержки", "карусель отзывов", "аналитика событий", "редактор комментариев", "карта пунктов выдачи",
        "календарь доставки", "рекомендации", "A/B-платформа", "видеоплеер", "форма подписки", "графики",
        "переводчик интерфейса", "сборщик ошибок", "виджет опроса"]
CRIT = ["роутер", "рендер первого экрана", "состояние корзины", "шрифты и стили", "авторизация"]

CALC = r'''
from itertools import combinations
tasks, budget = {}, None
for l in DATA.splitlines():
    if l.startswith("бюджет TBT"):
        budget = int(l.split(":")[1].split()[0])
    elif l.count("|") == 3 and "модуль" not in l:
        t, m, ms, crit = [x.strip() for x in l.split("|")]
        tasks.setdefault(t, []).append((m, int(ms), crit == "да"))
mods = [(t, m, ms) for t, lst in tasks.items() for m, ms, c in lst if not c]
def tbt(removed):
    return sum(max(0, sum(ms for m, ms, c in lst if (t, m) not in removed) - 50) for t, lst in tasks.items())
for k in range(len(mods) + 1):
    if any(tbt({(t, m) for t, m, _ in comb}) <= budget for comb in combinations(mods, k)):
        print(k)
        break
'''


def _tbt(tasks, removed):
    return sum(max(0, sum(ms for m, ms, c in lst if (t, m) not in removed) - 50) for t, lst in tasks.items())


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    page = rng.choice(PAGES)
    for _ in range(3000):
        nt = rng.randint(3, 5)
        names = rng.sample(MODS, len(MODS))
        crit = rng.sample(CRIT, nt)
        tasks = {}
        for i in range(nt):
            tname = f"задача {i + 1}"
            lst = [(crit[i], rng.choice([10, 15, 20, 25, 30, 35, 40]), True)]
            for _ in range(rng.randint(1, 3)):
                if names:
                    lst.append((names.pop(), rng.choice([8, 12, 18, 25, 30, 40, 55, 70, 90, 120]), False))
            tasks[tname] = lst
        base = _tbt(tasks, set())
        if base < 150:
            continue
        budget = rng.choice([50, 80, 100, 150, 200])
        if budget >= base:
            continue
        mods = [(t, m, ms) for t, lst in tasks.items() for m, ms, c in lst if not c]
        good = None
        for k in range(len(mods) + 1):
            if any(_tbt(tasks, {(t, m) for t, m, _ in comb}) <= budget for comb in combinations(mods, k)):
                good = k
                break
        if good is None or good < 2:
            continue
        # жадно: самый тяжёлый модуль каждый раз
        removed, greedy = set(), 0
        for t, m, ms in sorted(mods, key=lambda x: -x[2]):
            if _tbt(tasks, removed) <= budget:
                break
            removed.add((t, m))
            greedy += 1
        if greedy == good and rng.random() < 0.5:
            continue  # в части вариантов жадный выбор ошибается — это и проверяем
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"бюджет TBT: {budget} мс", "", "задача | модуль | мс | первый экран"]
    for t, lst in tasks.items():
        for m, ms, c in lst:
            lines.append(f"{t} | {m} | {ms} | {'да' if c else 'нет'}")
    block = "\n".join(lines)
    stem = (f"Страница «{page}» на среднем телефоне: в трассе между первой отрисовкой и готовностью к вводу — длинные "
            "задачи главного потока (таблица: из каких модулей состоит каждая задача и сколько исполняется модуль). "
            "Любой модуль, кроме модулей первого экрана, можно отложить — загрузить динамически после готовности, "
            "тогда его время уходит из задачи. Какое наименьшее число модулей нужно отложить, чтобы суммарное "
            "блокирующее время (TBT) уложилось в бюджет? Ответ — целое число.")
    gtxt = (f"Жадный выбор «самый тяжёлый модуль» даёт {greedy}: укорачивать задачу ниже 50 мс бесполезно, "
            "выгоднее снимать превышение там, где оно есть." if greedy != good else
            "Здесь жадный выбор «самый тяжёлый модуль» совпал с перебором, но в общем случае он не минимален: "
            "укорачивать задачу ниже 50 мс бесполезно.")
    expl = (f"TBT = Σ max(0, задача − 50 мс); сейчас {base} мс. Перебор наборов модулей: впервые бюджет {budget} мс "
            f"достигается при {good}. {gtxt} Ошибка «сумма длительностей задач вместо превышений» даёт другой ответ.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=page,
                         accept=num_accept(good, ("модуля", "модулей")),
                         params={"budget": budget, "base": base, "greedy": greedy,
                                 "tasks": {t: [list(x) for x in v] for t, v in tasks.items()}})
