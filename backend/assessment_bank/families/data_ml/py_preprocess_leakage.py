"""data_ml.py.preprocess_leakage — find_bug: статистики предобработки считаются по всем данным.

Функция сортирует записи по времени, отделяет последние записи как отложенную выборку и
масштабирует/заполняет признак. Дефект — параметры преобразования (min/max, mean/std,
медиана или среднее для заполнения пропусков) вычисляются по всем данным, включая
отложенную часть: утечка информации из «будущего». Рядом стоит безопасное поэлементное
преобразование (log1p, замена служебного значения на None) — оно не требует обучения на
данных, и пометить его как ошибку — типичная неверная гипотеза.
"""
from __future__ import annotations

import math
from statistics import mean, median, pstdev

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.py.preprocess_leakage"

# (признак, поле даты, контекст, единицы, диапазон значений)
CONTEXTS = [
    ("income", "applied_at", "кредитный скоринг", "тыс. ₽", (40, 160)),
    ("session_minutes", "day", "прогноз оттока", "мин", (5, 90)),
    ("basket_sum", "order_date", "рекомендации в ритейле", "₽", (300, 4000)),
    ("vibration", "measured_at", "предиктивное обслуживание", "мм/с", (2, 30)),
    ("delivery_hours", "created_at", "логистика", "ч", (6, 96)),
    ("page_views", "visit_date", "веб-аналитика", "просмотров", (3, 60)),
    ("call_seconds", "call_date", "колл-центр", "с", (30, 600)),
]
KINDS = ["minmax", "zscore", "impute_median", "impute_mean"]
ACTION = {
    "minmax": "приводит значения к диапазону [0, 1] (min-max)",
    "zscore": "стандартизирует значения (z-оценка)",
    "impute_median": "заполняет пропуски медианой",
    "impute_mean": "заполняет пропуски средним",
}


def _lines(kind: str, feat: str, date: str, share: float, stateless: bool, fixed: bool,
           names: dict):
    V, C, F, P = names["values"], names["cut"], names["fn"], names["param"]
    src = f"{V}[:{C}]" if fixed else V
    imp = {"minmax": [], "zscore": ["from statistics import mean, pstdev"],
           "impute_median": ["from statistics import median"],
           "impute_mean": ["from statistics import mean"]}[kind]
    if stateless and kind in ("minmax", "zscore"):
        imp = ["import math"] + imp
    head = imp + ["", ""] if imp else []
    body = [f"def {F}_{feat}(rows, {P}={share}):",
            f"    rows = sorted(rows, key=lambda r: r[\"{date}\"])",
            f"    {V} = [r[\"{feat}\"] for r in rows]"]
    if stateless:
        body.append(f"    {V} = [math.log1p(v) for v in {V}]" if kind in ("minmax", "zscore")
                    else f"    {V} = [None if v == -1 else v for v in {V}]")
    body.append(f"    {C} = int(len({V}) * (1 - {P}))")
    if kind == "minmax":
        body += [f"    lo, hi = min({src}), max({src})",
                 f"    prepared = [(v - lo) / ((hi - lo) or 1.0) for v in {V}]"]
    elif kind == "zscore":
        body += [f"    mu, sd = mean({src}), pstdev({src})",
                 f"    prepared = [(v - mu) / (sd or 1.0) for v in {V}]"]
    else:
        fn = "median" if kind == "impute_median" else "mean"
        body += [f"    fill = {fn}(v for v in {src} if v is not None)",
                 f"    prepared = [fill if v is None else v for v in {V}]"]
    body.append(f"    return prepared[:{C}], prepared[{C}:]")
    stat_line = len(head) + len(body) - 2  # строка со статистиками (с 1)
    return "\n".join(head + body), stat_line


def _reference(kind, values, share, stateless, use_all):
    vals = list(values)
    if stateless:
        vals = [math.log1p(v) for v in vals] if kind in ("minmax", "zscore") else \
            [None if v == -1 else v for v in vals]
    cut = int(len(vals) * (1 - share))
    src = vals if use_all else vals[:cut]
    if kind == "minmax":
        lo, hi = min(src), max(src)
        out = [(v - lo) / ((hi - lo) or 1.0) for v in vals]
    elif kind == "zscore":
        mu, sd = mean(src), pstdev(src)
        out = [(v - mu) / (sd or 1.0) for v in vals]
    else:
        fn = median if kind == "impute_median" else mean
        fill = fn(v for v in src if v is not None)
        out = [fill if v is None else v for v in vals]
    return out[:cut], out[cut:]


def _data(rng, kind, rng_vals, n, share, stateless, date_fmt):
    lo, hi = rng_vals
    cut = int(n * (1 - share))
    for _ in range(2000):
        vals = [rng.randint(lo, hi) for _ in range(n)]
        # дрейф в отложенной части: значения выше обучающих — типичная ситуация
        for i in range(cut, n):
            vals[i] = rng.randint(hi, hi + (hi - lo))
        if kind.startswith("impute"):
            miss = rng.sample(range(n), max(2, n // 4))
            if not any(i < cut for i in miss) or not any(i >= cut for i in miss):
                continue
            for i in miss:
                vals[i] = -1 if stateless else None
        good = _reference(kind, vals, share, stateless, use_all=False)
        bad = _reference(kind, vals, share, stateless, use_all=True)
        if [round(x, 9) for x in good[0] + good[1]] != [round(x, 9) for x in bad[0] + bad[1]]:
            dates = [date_fmt(i) for i in range(n)]
            order = list(range(n))
            rng.shuffle(order)  # записи приходят не по порядку — функция обязана сортировать
            return [(dates[i], vals[i]) for i in order], good
    raise RuntimeError("не удалось подобрать данные")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    feat, date, ctx, unit, rng_vals = rng.choice(CONTEXTS)
    kind = rng.choice(KINDS)
    share = rng.choice([0.15, 0.2, 0.25, 0.3])
    stateless = rng.random() < 0.6
    n = rng.choice([8, 10, 12])
    month = rng.randint(1, 9)
    date_fmt = lambda i: f"2026-{month:02d}-{i + 3:02d}"
    names = dict(values=rng.choice(["values", "vals", "xs", "series"]),
                 cut=rng.choice(["cut", "n_train", "split_at"]),
                 fn=rng.choice(["prepare", "build", "make_feature"]),
                 param=rng.choice(["test_share", "holdout_share"]))
    buggy, key_line = _lines(kind, feat, date, share, stateless, False, names)
    fixed, _ = _lines(kind, feat, date, share, stateless, True, names)
    assert changed_lines(buggy, fixed) == {key_line}
    rows, (exp_tr, exp_te) = _data(rng, kind, rng_vals, n, share, stateless, date_fmt)
    rows_lit = "[" + ", ".join(f"{{\"{date}\": \"{d}\", \"{feat}\": {v!r}}}" for d, v in rows) + "]"
    test = (f"rows = {rows_lit}\n"
            f"train, test = {names['fn']}_{feat}(rows)\n"
            f"assert [round(x, 9) for x in train] == {[round(x, 9) for x in exp_tr]!r}\n"
            f"assert [round(x, 9) for x in test] == {[round(x, 9) for x in exp_te]!r}")
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    miss_note = ""
    if kind.startswith("impute"):
        miss_note = (" Пропуски в выгрузке обозначены значением -1." if stateless
                     else " Пропуски в выгрузке — None.")
    pct = int(share * 100)
    stem = (f"Функция готовит признак `{feat}` ({unit}) для модели ({ctx}): сортирует записи по "
            f"`{date}`, последние {pct}% записей оставляет как отложенную выборку и "
            f"{ACTION[kind]}.{miss_note} Качество на отложенной выборке получилось заметно выше, "
            f"чем потом в продакшене, и ревьюер подозревает утечку информации из отложенной "
            f"части в обучение. Укажите номер строки с ошибкой.")
    what = {"minmax": "min и max считаются", "zscore": "среднее и стандартное отклонение считаются",
            "impute_median": "медиана для заполнения считается",
            "impute_mean": "среднее для заполнения считается"}[kind]
    tail = (" Поэлементное преобразование в строке выше (log1p или замена -1 на None) не "
            "обучается на данных и утечки не даёт." if stateless else "")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {what} по всем данным, включая отложенную "
                               "часть, — параметры преобразования «подсматривают» будущее. Их "
                               f"нужно оценивать только по {names['values']}[:{names['cut']}] и "
                               "затем применять к обеим частям." + tail)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="preprocessing_leakage",
                         params={"fixed_code": fixed, "kind": kind, "stateless": stateless})
