"""data_eng.etl.t21_partition_slice_output — predict_output (набор t21, порог Стажёра): срезы списка дневных
партиций — правая граница не входит, отрицательные индексы, срез за концом списка.

Список партиций по дням; программа берёт диапазон для дозагрузки `parts[i:j]` и последние k партиций `parts[-k:]`,
печатает первый и последний элемент и длину. Ловушки чтения: правая граница среза не включается; отрицательный
индекс считается с конца; срез за концом списка просто короче. Ключ — независимый расчёт индексов в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

import datetime as dt

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.etl.t21_partition_slice_output"

CTX = [("дозагрузка событий после сбоя", "backfill", "recent"), ("пересчёт дневных витрин", "rebuild", "last"),
       ("перенос партиций в холодное хранилище", "to_move", "keep"),
       ("проверка свежести данных", "window", "tail"), ("повторная выгрузка заказов", "rerun", "latest")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, a_name, b_name = rng.choice(CTX)
    n = rng.randint(6, 8)
    start = dt.date(2026, rng.randint(1, 12), rng.randint(1, 20))
    parts = [(start + dt.timedelta(days=d)).isoformat() for d in range(n)]
    i = rng.randint(1, 3)
    kind = rng.choice(["pos", "neg", "over"])
    if kind == "pos":
        j = rng.randint(i + 2, n - 1)
        j_txt = str(j)
        j_abs = j
    elif kind == "neg":
        jn = rng.randint(1, 3)
        while n - jn - i < 2:
            jn -= 1
        j_txt = str(-jn)
        j_abs = n - jn
    else:
        j = rng.randint(n + 1, n + 4)
        j_txt = str(j)
        j_abs = n
    k = rng.randint(2, 4)
    sl = parts[i:j_abs]
    tail = parts[n - k:]
    lst = "[" + ", ".join(f'"{p}"' for p in parts) + "]"
    code = (f"parts = {lst}\n"
            f"{a_name} = parts[{i}:{j_txt}]\n"
            f"{b_name} = parts[-{k}:]\n"
            f"print({a_name}[0], {a_name}[-1], len({a_name}))\n"
            f"print({b_name}[0], len({b_name}))")
    out = f"{sl[0]} {sl[-1]} {len(sl)}\n{tail[0]} {len(tail)}"
    if kind == "neg":
        jtxt = f"индекс {j_txt} — это позиция {j_abs} с начала (считаем с конца), и она не входит"
    elif kind == "over":
        jtxt = f"правая граница {j_txt} за концом списка из {n} элементов — срез просто заканчивается на последнем"
    else:
        jtxt = f"правая граница {j_txt} не входит в срез"
    expl = (f"Индексы с нуля: parts[{i}] = {parts[i]}; {jtxt}, поэтому {a_name} — с {sl[0]} по {sl[-1]}, "
            f"{len(sl)} шт. parts[-{k}:] — последние {k}: начинается с {tail[0]}.")
    stem = (f"Задача «{ctx}»: список дневных партиций хранится в порядке дат; программа выбирает срезы для "
            "обработки.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "i": i, "j": j_txt, "k": k, "kind": kind}, language="python")
