"""frontend.chat.t21_last_message_output — predict_output (набор t21, порог Стажёра): длина массива и обращение
по индексу.

Массив строк интерфейса (сообщения чата, история переходов, шаги мастера); программа печатает длину, последний
элемент через `length - 1`, элемент по номеру и обращение за пределы массива — по индексу `length` или `-1`
(в JavaScript отрицательный индекс не считается с конца). Ловушки: индексы с нуля, `arr[arr.length]` и `arr[-1]`
дают undefined. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.chat.t21_last_message_output"

CTX = [("чат поддержки", "messages", ["Здравствуйте", "Заказ не пришёл", "Номер заказа?", "Секунду", "Проверяем",
                                       "Спасибо", "Готово"]),
       ("история переходов", "history", ["/home", "/catalog", "/cart", "/checkout", "/profile", "/orders",
                                         "/help"]),
       ("мастер оформления", "steps", ["Контакты", "Адрес", "Доставка", "Оплата", "Подтверждение", "Отзыв",
                                       "Бонусы"]),
       ("хлебные крошки", "crumbs", ["Главная", "Каталог", "Ноутбуки", "Игровые", "Модель X", "Отзывы",
                                     "Фото"]),
       ("стек отмены", "undo", ["вставка", "удаление", "жирный", "курсив", "отступ", "заголовок", "список"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr, pool = rng.choice(CTX)
    n = rng.randint(3, 6)
    items = rng.sample(pool, n)
    k = rng.randint(0, n - 2)
    outside = rng.choice(["len", "neg"])
    prints = [
        ("len", f"console.log({arr}.length);", str(n), f"{arr}.length = {n}"),
        ("last", f"console.log({arr}[{arr}.length - 1]);", items[-1],
         f"{arr}[{arr}.length - 1] = {arr}[{n - 1}] — последний элемент «{items[-1]}»"),
        ("idx", f"console.log({arr}[{k}]);", items[k],
         f"{arr}[{k}] — {k + 1}-й по счёту элемент (индексы с нуля): «{items[k]}»"),
    ]
    if outside == "len":
        prints.append(("out", f"console.log({arr}[{arr}.length]);", "undefined",
                       f"{arr}[{arr}.length] = {arr}[{n}] — за концом массива, undefined"))
    else:
        prints.append(("out", f"console.log({arr}[-1]);", "undefined",
                       f"{arr}[-1] — отрицательный индекс не отсчитывается с конца, такого элемента нет: undefined"))
    head, rest = prints[0], prints[1:]
    rng.shuffle(rest)
    prints = [head] + rest if rng.random() < 0.5 else rest + [head]
    lit = ", ".join(f"\"{x}\"" for x in items)
    code = "\n".join([f"const {arr} = [{lit}];"] + [p[1] for p in prints])
    out = "\n".join(p[2] for p in prints)
    expl = "Индексы массива — с нуля, последний — length − 1. " + "; ".join(p[3] for p in prints) + "."
    stem = f"Интерфейс ({ctx}): программа печатает число элементов списка и несколько элементов по индексу."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "k": k, "outside": outside, "order": [p[0] for p in prints]},
                          language="javascript")
