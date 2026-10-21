"""mobile.paging.t21_page_slice_output — predict_output (набор t21, порог Стажёра): страница ленты через slice
при нумерации страниц с единицы.

Программа на JavaScript (логика React Native-списка) вырезает из загруженного массива идентификаторов страницу с
номером page (нумерация с 1) размера PAGE_SIZE: start = (page − 1) · PAGE_SIZE, slice(start, start + PAGE_SIZE).
Ловушки чтения: сдвиг на единицу в номере страницы, правая граница slice не включается, последняя страница
бывает неполной (slice не выходит за конец массива). Ключ — независимое вычисление индексов в генераторе;
проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.paging.t21_page_slice_output"

CTX = [("лента новостей", "postIds"), ("история заказов", "orderIds"), ("список чатов", "chatIds"),
       ("каталог товаров", "productIds"), ("уведомления", "noticeIds")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr = rng.choice(CTX)
    size = rng.choice([3, 4, 5])
    for _ in range(200):
        n = rng.randint(2 * size + 1, 3 * size + 2)
        if n % size:
            break
    pages = -(-n // size)
    ids = sorted(rng.sample(range(100, 1000), n))
    # последняя (неполная) страница — в половине вариантов, иначе — одна из полных, кроме первой
    page = pages if rng.random() < 0.5 else rng.randint(2, pages - 1)
    start = (page - 1) * size
    visible = ids[start:start + size]
    const_name = rng.choice(["PAGE_SIZE", "PER_PAGE", "LIMIT"])
    page_name = rng.choice(["page", "pageNumber", "currentPage"])
    code = (f"const {arr} = [{', '.join(map(str, ids))}];\n"
            f"const {const_name} = {size};\n"
            f"const {page_name} = {page};\n"
            f"const start = ({page_name} - 1) * {const_name};\n"
            f"const visible = {arr}.slice(start, start + {const_name});\n"
            f"console.log(visible.length, visible.join(','));")
    out = f"{len(visible)} {','.join(map(str, visible))}"
    tail = (f"элементов в массиве {n}, поэтому slice возвращает только {len(visible)}"
            if len(visible) < size else f"правая граница {start + size} не включается")
    expl = (f"start = ({page} − 1)·{size} = {start}: страница {page} начинается с индекса {start} (это "
            f"{start + 1}-й элемент, индексы с нуля). slice({start}, {start + size}) берёт индексы "
            f"{start}…{min(start + size, n) - 1}: {tail}. Вывод: «{out}».")
    stem = (f"React Native-экран «{ctx.capitalize()}»: программа вырезает из загруженных идентификаторов одну "
            f"страницу для показа в списке (страницы нумеруются с 1).")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "size": size, "page": page}, language="javascript")
