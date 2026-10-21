"""frontend.lists.t21_page_slice_output — predict_output (набор t21, порог Стажёра): срез массива для страницы
списка.

Список разбит на страницы фиксированного размера; программа берёт `slice(start, end)` для текущей страницы и
печатает элементы через запятую и их число. Ловушки чтения: индексы с нуля, конец среза не включается, последняя
страница бывает неполной (срез за концом массива просто короче). Номер страницы — с единицы (`(page - 1) * size`)
или индекс страницы с нуля (`pageIndex * size`). Ключ — независимый срез в генераторе; проверка — исполнение
показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.lists.t21_page_slice_output"

CTX = [("каталог техники", "products", ["Чайник", "Тостер", "Миксер", "Блендер", "Утюг", "Фен", "Пылесос",
                                         "Гриль", "Кофеварка", "Мультиварка"]),
       ("лента уведомлений", "notices", ["Оплата", "Доставка", "Возврат", "Скидка", "Отзыв", "Бонус", "Подписка",
                                         "Акция", "Чек", "Заказ"]),
       ("список задач", "tasks", ["Вёрстка", "Тесты", "Ревью", "Деплой", "Макет", "Баг", "Рефакторинг", "Релиз",
                                  "Демо", "Аудит"]),
       ("плейлист", "tracks", ["Intro", "Sunrise", "Ocean", "Neon", "Echo", "Drift", "Pulse", "Orbit", "Haze",
                               "Glow"]),
       ("города доставки", "cities", ["Москва", "Казань", "Пермь", "Омск", "Тула", "Сочи", "Самара", "Уфа", "Курск",
                                      "Тверь"])]
SIZE_NAMES = ["size", "perPage", "pageSize"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr, pool = rng.choice(CTX)
    n = rng.randint(6, 9)
    items = rng.sample(pool, n)
    size = rng.randint(2, 4)
    pages = -(-n // size)
    if n % size and rng.random() < 0.5:
        page = pages  # неполная последняя страница
    else:
        page = rng.randint(2, pages)
    start, end = (page - 1) * size, page * size
    shown = items[start:end]
    s_name = rng.choice(SIZE_NAMES)
    lit = ", ".join(f"\"{x}\"" for x in items)
    if rng.random() < 0.5:
        p_name = "page"
        head = [f"const {p_name} = {page};", f"const {s_name} = {size};"]
        slice_line = f"const shown = {arr}.slice(({p_name} - 1) * {s_name}, {p_name} * {s_name});"
        idx_note = f"страница {page} (с единицы): начало ({page} − 1) * {size} = {start}, конец {page} * {size} = {end}"
        pval = page
    else:
        p_name = "pageIndex"
        head = [f"const {p_name} = {page - 1};", f"const {s_name} = {size};"]
        slice_line = f"const shown = {arr}.slice({p_name} * {s_name}, ({p_name} + 1) * {s_name});"
        idx_note = (f"индекс страницы {page - 1} (с нуля): начало {page - 1} * {size} = {start}, "
                    f"конец {page} * {size} = {end}")
        pval = page - 1
    rng.shuffle(head)
    code = "\n".join([f"const {arr} = [{lit}];"] + head +
                     [slice_line, "console.log(shown.join(\", \"));", "console.log(shown.length);"])
    out = ", ".join(shown) + "\n" + str(len(shown))
    tail = (f"; в массиве {n} элементов, поэтому срез обрывается на конце и короче размера страницы"
            if end > n else "; элемент с индексом конца в срез не входит")
    last = min(end, n) - 1
    taken = f"берётся элемент с индексом {start}" if last == start else f"берутся элементы с индексами {start}…{last}"
    expl = (f"Индексы с нуля, конец среза не включается: {idx_note}, {taken}{tail}. "
            f"Вывод: «{', '.join(shown)}», затем длина {len(shown)}.")
    stem = f"Интерфейс ({ctx}): список разбит на страницы, программа берёт элементы текущей страницы."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "size": size, "page": pval, "one_based": p_name == "page"},
                          language="javascript")
