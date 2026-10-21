"""data_eng.etl.t21_batch_offset_loop_output — predict_output (набор t21, порог Стажёра): цикл while со счётчиком
запросов и смещением при постраничной выгрузке.

Загрузчик забирает строки из источника страницами по `batch` строк: пока смещение меньше (или не больше) общего числа
строк, делает запрос и сдвигает смещение. Ловушки чтения: последнее смещение «перелетает» общее число строк; при
`<=` и делении без остатка цикл делает лишний запрос. Ключ — независимая формула в генераторе (без исполнения кода);
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.etl.t21_batch_offset_loop_output"

CTX = ["выгрузка заказов из учётной системы", "загрузка событий из API приложения", "перенос справочника клиентов",
       "забор логов с серверов приложений", "загрузка остатков из складской системы"]
NAMES = [("total_rows", "page_size", "offset", "requests"), ("rows", "batch", "offset", "calls"),
         ("count", "limit", "start", "pages"), ("n_rows", "chunk", "pos", "fetches")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    tot, bat, off, cnt = rng.choice(NAMES)
    batch = rng.choice([100, 120, 150, 200, 250, 300, 400, 500])
    if rng.random() < 0.35:
        total = batch * rng.randint(2, 7)
    else:
        total = rng.randrange(batch * 2 + 10, batch * 6, 10)
        if total % batch == 0:
            total += 10
    op = rng.choice(["<", "<", "<="])
    code = (f"{tot} = {total}\n"
            f"{bat} = {batch}\n"
            f"{off} = 0\n"
            f"{cnt} = 0\n"
            f"while {off} {op} {tot}:\n"
            f"    {off} += {bat}\n"
            f"    {cnt} += 1\n"
            f"print({cnt}, {off})")
    if op == "<":
        calls = -(-total // batch)
    else:
        calls = total // batch + 1
    final = calls * batch
    out = f"{calls} {final}"
    exact = total % batch == 0
    if op == "<=" and exact:
        trap = (f"{total} делится на {batch} без остатка, а условие `<=` пускает цикл и при {off} = {total} — "
                "получается лишний запрос")
    elif exact:
        trap = f"{total} делится на {batch} без остатка, и при {off} = {total} условие `<` уже ложно"
    else:
        trap = f"последнее смещение {final} больше {total}: цикл останавливается, только «перелетев» общее число строк"
    expl = (f"Смещение растёт на {batch}: 0, {batch}, {2 * batch}, … Цикл выполняется, пока {off} {op} {total}, — это "
            f"{calls} итераций, после них {off} = {final}. Ловушка: {trap}. Вывод: «{out}».")
    stem = f"Задача «{ctx}» забирает строки страницами; программа считает запросы и итоговое смещение."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"total": total, "batch": batch, "op": op}, language="python")
