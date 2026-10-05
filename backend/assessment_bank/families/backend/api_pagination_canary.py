"""backend.api.pagination_canary — predict_output (канарейка): страница выдачи по page/size.

Канареечное семейство: seed 1..30 намеренно опубликованы. Нужны детектору предзнания
(время + правильность ответа), в грейд не входят.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.api.pagination_canary"

DATA = [("ord", "заказы", "orders"), ("usr", "пользователей", "users"),
        ("doc", "документы", "documents"), ("evt", "события", "events"), ("inv", "счета", "invoices")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    prefix, what, res = rng.choice(DATA)
    ctx = res
    n = rng.randint(5, 23)
    size = rng.randint(2, 6)
    pages = (n + size - 1) // size
    page = rng.choice(list(range(1, pages + 1)) + [pages + 1])
    first = rng.choice([1, 101, 501])
    lines = [f'items = [f"{prefix}-{{i}}" for i in range({first}, {first + n})]',
             f"page, size = {page}, {size}",
             "pages = (len(items) + size - 1) // size",
             "start = (page - 1) * size",
             "chunk = items[start:start + size]",
             "print(pages, chunk, page < pages)"]
    code = "\n".join(lines)
    items = [f"{prefix}-{i}" for i in range(first, first + n)]
    start = (page - 1) * size
    out = f"{pages} {items[start:start + size]!r} {page < pages}"
    stem = (f"Эндпоинт `GET /api/{res}` отдаёт {what} постранично. Что напечатает программа? "
            f"Запишите вывод точно в том виде, в каком его печатает Python.")
    ak = AnswerKey(kind="output", value=out,
                   explanation="Число страниц — деление с округлением вверх; срез за концом "
                               "списка даёт пустой список; есть следующая страница, если page < pages.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"n": n, "size": size, "page": page})
