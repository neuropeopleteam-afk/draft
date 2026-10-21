"""data_eng.etl.t21_batch_buffer_alias_output — predict_output (набор t21, порог Middle): нарезка строк на батчи
для массовой вставки — псевдоним буфера (`out.append(buf)` + `buf.clear()`) против нового списка или копии.

Функция копит строки в буфере и, когда он заполнится, кладёт его в список батчей. Вариант кода: (a) `out.append(buf)`
и `buf.clear()` — в out попадает ОДИН И ТОТ ЖЕ список, который потом очищается и заполняется остатком; (b)
`out.append(buf)` и `buf = []` — новый список, всё корректно; (c) `out.append(buf[:])` и `buf.clear()` — копия,
тоже корректно. Ловушка: в (a) все элементы out — псевдонимы, их длины равны длине остатка (или 0), а финальный
`if buf` добавляет тот же список ещё раз. Ключ — независимая модель в генераторе; проверка — исполнение в песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.etl.t21_batch_buffer_alias_output"

CTX = ["массовая вставка заказов в хранилище", "отправка событий пачками в приёмник",
       "загрузка строк CSV-файла частями", "перенос клиентов из старой базы", "запись логов в архив пачками"]
FN = ["chunks", "batches", "split_rows", "make_batches"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn = rng.choice(FN)
    mode = rng.choice(["alias", "alias", "alias", "new_list", "copy"])
    size = rng.randint(2, 4)
    n = rng.randint(size + 2, 3 * size + 2)
    if mode == "alias" and n % size == 0:
        n += 1                                # с остатком: в общем буфере после цикла остаются строки
    start = rng.randrange(100, 900, 10)
    rows = list(range(start, start + n))
    if mode == "alias":
        push, reset = "out.append(buf)", "buf.clear()"
    elif mode == "new_list":
        push, reset = "out.append(buf)", "buf = []"
    else:
        push, reset = "out.append(buf[:])", "buf.clear()"
    code = (f"def {fn}(rows, size):\n"
            "    out, buf = [], []\n"
            "    for r in rows:\n"
            "        buf.append(r)\n"
            "        if len(buf) == size:\n"
            f"            {push}\n"
            f"            {reset}\n"
            "    if buf:\n"
            "        out.append(buf)\n"
            "    return out\n"
            f"res = {fn}(list(range({start}, {start + n})), {size})\n"
            "print(len(res))\n"
            "print(*[len(b) for b in res])\n"
            "print(*res[0])")
    full, rem = divmod(n, size)
    if mode == "alias":
        cnt = full + (1 if rem else 0)
        lens = [rem] * cnt
    else:
        cnt = full + (1 if rem else 0)
        lens = [size] * full + ([rem] if rem else [])
    first = rows[full * size:] if mode == "alias" else rows[:size] if full else rows
    out = f"{cnt}\n" + " ".join(str(x) for x in lens) + "\n" + " ".join(str(x) for x in first)
    if mode == "alias":
        why = (f"out.append(buf) кладёт ссылку на тот же список, а buf.clear() очищает его на месте — все {full} "
               f"{plural(full, 'полный батч указывает', 'полных батча указывают', 'полных батчей указывают')} на "
               f"один объект. После цикла в нём остаток из {rem} {plural(rem, 'строки', 'строк', 'строк')} "
               f"({' '.join(str(x) for x in first)}), и if buf добавляет этот же список ещё раз. Итого {cnt} "
               f"{plural(cnt, 'элемент', 'элемента', 'элементов')}, у каждого длина {rem}, и res[0] — тот же остаток")
    elif mode == "new_list":
        why = ("buf = [] создаёт новый список, а сохранённый в out остаётся нетронутым — батчи корректны, res[0] — "
               "первые строки")
    else:
        why = ("out.append(buf[:]) сохраняет копию, поэтому buf.clear() её не задевает — батчи корректны, res[0] — "
               "первые строки")
    expl = (f"{len(rows)} строк по {size}: полных батчей {full}, остаток {rem}. {why}. Вывод: "
            f"«{out.replace(chr(10), ' / ')}».")
    stem = (f"Задача «{ctx}» режет строки на батчи для массовой вставки; программа печатает число батчей, их размеры "
            "и первый батч.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"mode": mode, "n": n, "size": size}, language="python")
