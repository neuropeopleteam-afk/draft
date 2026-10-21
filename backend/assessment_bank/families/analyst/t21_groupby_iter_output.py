"""analyst.python.t21_groupby_iter_output — predict_output (набор t21, порог Senior): itertools.groupby на
несортированном логе и отложенное чтение групп.

Лог событий в порядке поступления (каналы / дни / платформы идут «кусками» и повторяются). Цикл по
`groupby(log, key=…)` сохраняет первое значение каждой группы (`next(items)`) и сам итератор группы, а после цикла
печатает для каждого ключа первое значение и сумму «остатка» группы. Ловушки: groupby объединяет только СОСЕДНИЕ
строки — повторный кусок с тем же ключом даёт новую группу, и словарь перезаписывает значение, сохраняя место ключа;
итераторы групп разделяют общий источник — когда groupby переходит к следующей группе (и когда цикл заканчивается),
недочитанный остаток прежней группы пропадает, поэтому сохранённые итераторы пусты и суммы равны 0. Ключ —
независимая модель в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.python.t21_groupby_iter_output"

# (сюжет, имя лога, ключи, имя ключа, имя значения, диапазон значений)
CTX = [
    ("заказы по каналам привлечения", "log", ["ads", "seo", "email"], "channel", "amount", (100, 900, 50)),
    ("сессии по платформам", "sessions", ["ios", "android", "web"], "platform", "minutes", (1, 30, 1)),
    ("обращения по линиям поддержки", "tickets", ["sales", "billing", "tech"], "line", "wait", (1, 20, 1)),
    ("покупки по городам", "purchases", ["kzn", "msk", "spb"], "city", "total", (200, 2000, 100)),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, var, keys, kname, vname, (lo, hi, st) = rng.choice(CTX)
    agg = rng.choice(["sum", "len"])
    for _ in range(1000):
        n_runs = rng.randint(4, 5)
        runs = []
        for _r in range(n_runs):
            k = rng.choice(keys)
            if runs and runs[-1][0] == k:
                continue
            runs.append((k, [rng.randrange(lo, hi + 1, st) for _ in range(rng.randint(1, 3))]))
        if len(runs) < 4:
            continue
        rk = [k for k, _v in runs]
        if len(set(rk)) == len(rk):        # нужен повтор ключа в разных кусках
            continue
        if not any(len(v) > 1 for _k, v in runs):
            continue
        if sum(len(v) for _k, v in runs) > 9:
            continue
        break
    else:
        raise RuntimeError("t21_groupby_iter: не собрались данные")
    log = [(k, v) for k, vs in runs for v in vs]
    first, order = {}, []
    for k, vs in runs:
        if k not in first:
            order.append(k)
        first[k] = vs[0]
    lst = "[" + ", ".join(f'("{k}", {v})' for k, v in log) + "]"
    tail = "sum(v for _, v in rest[k])" if agg == "sum" else "len(list(rest[k]))"
    code = (f"from itertools import groupby\n\n"
            f"{var} = {lst}\n"
            f"first = {{}}\n"
            f"rest = {{}}\n"
            f"for {kname}, items in groupby({var}, key=lambda e: e[0]):\n"
            f"    first[{kname}] = next(items)[1]\n"
            f"    rest[{kname}] = items\n"
            f"for k in first:\n"
            f"    print(k, first[k], {tail})")
    lines = [f"{k} {first[k]} 0" for k in order]
    out = "\n".join(lines)
    stem = (f"Аналитик сворачивает лог ({plot}) в порядке поступления записей: для каждого {kname} — первое "
            f"значение {vname} и {'сумма' if agg == 'sum' else 'число'} остальных.")
    runs_txt = "; ".join(f"{k}: {', '.join(str(v) for v in vs)}" for k, vs in runs)
    rep = sorted({k for k in rk if rk.count(k) > 1})
    expl = (f"groupby объединяет только соседние строки — группы: {runs_txt}. Ключ {', '.join(rep)} встречается в "
            f"нескольких кусках: first перезаписывается первым значением последнего куска, а место ключа в словаре "
            f"остаётся по первому появлению. Итераторы групп разделяют общий источник: когда groupby переходит к "
            f"следующей группе (и когда цикл заканчивается), остаток прежней группы пропадает, поэтому все "
            f"сохранённые rest[k] уже пусты — {'сумма' if agg == 'sum' else 'длина'} 0. Вывод: "
            + "; ".join(f"«{ln}»" for ln in lines) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"log": log, "agg": agg}, language="python")
