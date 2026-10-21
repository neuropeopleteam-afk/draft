"""data_ml.features.t21_str_concat_output — predict_output (набор t21, порог Стажёра): значения признака, прочитанные
из CSV строками, — конкатенация строк против сложения чисел и имя признака через str().

Программа получает значения счётчика за несколько дней в виде строк (как из CSV), склеивает их «+», отдельно
складывает после int() и собирает имя нового признака конкатенацией со str(). Ловушка чтения: «+» для строк —
склейка ("17" + "25" = "1725"), а не сумма; print печатает строку без кавычек. Ключ — независимый расчёт
в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.features.t21_str_concat_output"

CTX = [("клики по баннеру", "clicks", (3, 60)), ("просмотры карточки товара", "views", (20, 400)),
       ("заказы в приложении", "orders", (1, 30)), ("звонки в поддержку", "calls", (2, 40)),
       ("поисковые запросы", "queries", (10, 200))]
DAY_NAMES = [("mon", "tue", "wed"), ("d1", "d2", "d3"), ("day1", "day2", "day3"), ("sat", "sun", "mon")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, feat, (lo, hi) = rng.choice(CTX)
    names = rng.choice(DAY_NAMES)
    k = rng.choice([2, 2, 3])
    vals = [rng.randint(lo, hi) for _ in range(k)]
    vs = names[:k]
    joined = "".join(str(v) for v in vals)
    total = sum(vals)
    suffix = f"_{k}d"
    name = feat + "_" + str(total) + suffix
    code = "".join(f'{n} = "{v}"\n' for n, v in zip(vs, vals))
    code += (f"raw = {' + '.join(vs)}\n"
             f"total = {' + '.join(f'int({n})' for n in vs)}\n"
             f'name = "{feat}_" + str(total) + "{suffix}"\n'
             "print(raw, total)\n"
             "print(name)")
    out = f"{joined} {total}\n{name}"
    expl = (f"Значения — строки (в кавычках), поэтому raw = {' + '.join(repr(str(v)) for v in vals)} = "
            f"'{joined}' — склейка, а не сумма. После int() числа складываются: total = {total}. "
            f"name = '{feat}_' + '{total}' + '{suffix}' = '{name}'; print печатает строки без кавычек. "
            f"Вывод: «{joined} {total}» и «{name}».")
    stem = (f"Признак «{ctx}» ({feat}): программа берёт значения за последние дни из CSV-выгрузки, объединяет их "
            f"и собирает имя нового признака.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"values": vals}, language="python")
