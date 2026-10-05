"""data_ml.py.iterator_pipeline — predict_output: одноразовые итераторы в конвейере обработки данных.

Типичная ошибка в ETL на чистом Python: генератор, ``map``/``filter`` или ``zip`` по итератору
читаются второй раз, а данные уже исчерпаны (или частично прочитаны ``any``/``next``).
Шаблоны:
* ``sum_then_count`` — сумма по генератору, затем подсчёт по тому же генератору → 0;
* ``any_partial`` — ``any`` останавливается на первом совпадении, ``list`` получает остаток;
* ``zip_same_iter`` — ``zip(it, it)`` разбивает поток на пары соседних элементов;
* ``next_header`` — ``next`` съедает «заголовок», затем ``max``/``len`` по остатку.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.py.iterator_pipeline"

CONTEXTS = [
    ("latency_ms", "время ответа сервиса, мс", (20, 400)),
    ("basket", "сумма чека, ₽", (100, 3000)),
    ("temp", "температура датчика, °C", (-5, 40)),
    ("minutes", "длительность сессии, мин", (1, 90)),
    ("score", "скор модели × 100", (1, 99)),
]
TEMPLATES = ["sum_then_count", "any_partial", "zip_same_iter", "next_header"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, descr, (lo, hi) = rng.choice(CONTEXTS)
    t = rng.choice(TEMPLATES)
    n = rng.randint(6, 8)
    vals = [rng.randint(lo, hi) for _ in range(n)]
    if t == "sum_then_count":
        thr = sorted(vals)[n // 3]
        lines = [f"raw = {[str(v) for v in vals]!r}",
                 f"{name} = (int(x) for x in raw if int(x) >= {thr})",
                 f"total = sum({name})",
                 f"count = sum(1 for _ in {name})",
                 "print(total, count)",
                 "print(total / count if count else 'нет данных')"]
        sel = [v for v in vals if v >= thr]
        out = f"{sum(sel)} 0\nнет данных"
        why = "генератор исчерпан первой суммой: второй проход ничего не видит, count = 0"
    elif t == "any_partial":
        thr = sorted(vals)[-3]
        idx = next(i for i, v in enumerate(vals) if v >= thr)
        lines = [f"values = {vals!r}",
                 f"stream = iter(values)",
                 f"has_big = any(v >= {thr} for v in stream)",
                 "rest = list(stream)",
                 "print(has_big, len(rest))",
                 "print(rest[:2])"]
        rest = vals[idx + 1:]
        out = f"True {len(rest)}\n{rest[:2]!r}"
        why = (f"any остановился на первом значении ≥ {thr} (позиция {idx}); list получил только "
               "оставшиеся элементы")
    elif t == "zip_same_iter":
        if n % 2:
            vals = vals[:-1]
        lines = [f"values = {vals!r}",
                 "it = iter(values)",
                 "pairs = list(zip(it, it))",
                 "deltas = [b - a for a, b in pairs]",
                 "print(len(pairs), deltas)",
                 "print(list(it))"]
        pairs = list(zip(vals[0::2], vals[1::2]))
        out = f"{len(pairs)} {[b - a for a, b in pairs]!r}\n[]"
        why = "zip(it, it) берёт два элемента из одного итератора за шаг — пары (0,1), (2,3), …; итератор исчерпан"
    else:
        lines = [f"rows = iter({[name] + [str(v) for v in vals]!r})",
                 "header = next(rows)",
                 "parsed = map(int, rows)",
                 "peak = max(parsed)",
                 "print(header, peak)",
                 "print(len(list(parsed)), len(list(rows)))"]
        out = f"{name} {max(vals)}\n0 0"
        why = "next забрал заголовок; max прочитал map до конца, а map читает тот же итератор rows — оба пусты"
    code = "\n".join(lines)
    stem = (f"Фрагмент конвейера обработки данных ({descr}). Что напечатает программа? Запишите "
            f"вывод точно в том виде, в каком его печатает Python.")
    ak = AnswerKey(kind="output", value=out, explanation=f"Ключевая деталь: {why}.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=descr,
                         verification="execution", checks=checks, params={"template": t})
