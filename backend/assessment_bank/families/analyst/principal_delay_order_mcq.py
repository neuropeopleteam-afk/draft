"""analyst.principal.delay_order_mcq — mcq_concept (Principal, короткое): в каком порядке одна команда должна делать
четыре инициативы, чтобы суммарная стоимость задержки была наименьшей.

У инициативы — стоимость задержки c (млн ₽ за неделю, пока она не сделана) и длительность d (недель); команда делает
их по очереди. Суммарная стоимость задержки порядка — Σ c_i · (неделя завершения i). Ключ — порядок по убыванию
c / d (у всех отношений разные значения — оптимум единственный).

Дистракторы — порядки трёх типичных правил: ``by_cod`` (самая дорогая задержка первой), ``shortest`` (короткие
первыми — «быстрые победы»), ``proposed`` (по приоритету заказчиков — столбец в таблице; случайная перестановка,
не совпадающая с оптимумом). Подписи — перестановки одних букв: форма не выдаёт ключ; место верного — по seed
поровну. Ключ проверяется исполнением: программа перебирает все 24 порядка.
"""
from __future__ import annotations

from itertools import permutations

from assessment_bank.families._principal_c_utils import choice_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "analyst.principal.delay_order_mcq"

CONTEXTS = [("банк", ["онлайн-заявка на кредит", "новый скоринг", "перевод по номеру телефона", "отчётность для регулятора",
                      "кешбэк-программа", "чат-бот поддержки"]),
            ("страховая компания", ["онлайн-урегулирование убытков", "калькулятор ОСАГО", "кабинет агента",
                                    "интеграция с автосервисами", "антифрод заявлений", "продление полиса в один клик"]),
            ("ритейлер", ["самовывоз из магазина", "персональные предложения", "новая касса", "учёт остатков в реальном времени",
                          "программа лояльности", "доставка за час"]),
            ("логистическая компания", ["трекинг для получателя", "оптимизация маршрутов", "электронные накладные",
                                        "кабинет отправителя", "интеграция с маркетплейсами", "учёт возвратов"])]
LETTERS = ["А", "Б", "В", "Г"]

PROGRAM = """from itertools import permutations

ITEMS = {items!r}     # буква -> (стоимость задержки, млн ₽ в неделю; длительность, недель)
def cost(order):
    t, total = 0, 0
    for x in order:
        t += ITEMS[x][1]
        total += ITEMS[x][0] * t
    return total
best = min(permutations(sorted(ITEMS)), key=cost)
print(" → ".join(best))
"""


def _cost(order, items):
    t = total = 0
    for x in order:
        t += items[x][1]
        total += items[x][0] * t
    return total


def _txt(order):
    return " → ".join(order)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    org, names = rng.choice(CONTEXTS)
    picked = rng.sample(names, 4)
    for _ in range(5000):
        items = {L: (rng.choice([1, 2, 3, 4, 5, 6, 8, 10]), rng.choice([1, 2, 3, 4, 5, 6, 8])) for L in LETTERS}
        ratios = [c / d for c, d in items.values()]
        if len(set(ratios)) != 4 or len({c for c, _ in items.values()}) != 4 or len({d for _, d in items.values()}) != 4:
            continue
        best = tuple(sorted(LETTERS, key=lambda x: -items[x][0] / items[x][1]))
        by_cod = tuple(sorted(LETTERS, key=lambda x: -items[x][0]))
        shortest = tuple(sorted(LETTERS, key=lambda x: items[x][1]))
        proposed = tuple(rng.sample(LETTERS, 4))
        orders = [best, by_cod, shortest, proposed]
        if len(set(orders)) != 4:
            continue
        costs = sorted(_cost(o, items) for o in permutations(LETTERS))
        if costs[0] == costs[1]:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    rank = {L: proposed.index(L) + 1 for L in LETTERS}
    rows = [f"  {L}. «{picked[i]}»: задержка стоит {items[L][0]} млн ₽ в неделю, работа — {items[L][1]} "
            f"{plural(items[L][1], 'неделя', 'недели', 'недель')}, приоритет заказчика — {rank[L]}"
            for i, L in enumerate(LETTERS)]
    code = "\n".join(["Инициативы (одна команда, по одной за раз, без переключений):", *rows])
    stem = (f"{org.capitalize()}: у платформенной команды четыре инициативы; пока инициатива не сделана, компания теряет "
            f"указанную сумму в неделю (стоимость задержки). Команда делает их по очереди. В каком порядке их делать, "
            f"чтобы суммарная стоимость задержки была наименьшей?")
    c = {o: _cost(o, items) for o in orders}
    why = (f"Суммарная стоимость задержки — Σ c × (неделя завершения). Обмен соседних инициатив выгоден, если у "
           f"второй больше отношение c / d, поэтому оптимум — по убыванию c / d: {_txt(best)} ({c[best]} млн ₽). "
           f"Самая дорогая задержка первой — {_txt(by_cod)} ({c[by_cod]} млн ₽); короткие первыми — "
           f"{_txt(shortest)} ({c[shortest]} млн ₽); по приоритету заказчиков — {_txt(proposed)} ({c[proposed]} млн ₽). "
           f"Вывод: очередь портфеля задаётся стоимостью задержки на единицу длительности, а не одной ценностью "
           f"или одной длительностью.")
    program = PROGRAM.format(items=items)
    return choice_mcq(FAMILY_ID, seed, rng, ctx=org, stem=stem, correct=_txt(best),
                      distractors=[_txt(by_cod), _txt(shortest), _txt(proposed)], program=program, why=why, code=code,
                      params={"items": items, "best": list(best)},
                      note="Программа перебирает все 24 порядка и печатает порядок с наименьшей стоимостью задержки.")
