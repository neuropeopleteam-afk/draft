"""data_ml.metrics.threshold_canary — predict_output (канарейка): порог, матрица ошибок, precision/recall.

Скоры модели переводятся в метки по порогу (``>=``), затем считаются TP, FP, FN и
precision/recall. Канарейка: seed 1..24 опубликованы, в грейд не входит.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.metrics.threshold_canary"

CONTEXTS = ["антифрод", "спам-фильтр", "прогноз оттока", "кредитный скоринг", "модерация"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    thr = rng.choice([0.4, 0.5, 0.6, 0.7])
    for _ in range(1000):
        n = rng.randint(7, 9)
        scores = [round(rng.randint(5, 95) / 100, 2) for _ in range(n)]
        # хотя бы один скор ровно на пороге — проверка понимания «>=»
        scores[rng.randrange(n)] = thr
        y_true = [rng.randint(0, 1) for _ in range(n)]
        y_pred = [int(s >= thr) for s in scores]
        tp = sum(t == 1 and p == 1 for t, p in zip(y_true, y_pred))
        fp = sum(t == 0 and p == 1 for t, p in zip(y_true, y_pred))
        fn = sum(t == 1 and p == 0 for t, p in zip(y_true, y_pred))
        if tp >= 1 and fp >= 1 and fn >= 1:
            break
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    code = "\n".join([
        f"scores = {scores!r}",
        f"y_true = {y_true!r}",
        f"y_pred = [int(s >= {thr}) for s in scores]",
        "tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)",
        "fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)",
        "fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)",
        "print(tp, fp, fn)",
        "print(round(tp / (tp + fp), 2), round(tp / (tp + fn), 2))",
    ])
    out = f"{tp} {fp} {fn}\n{round(precision, 2)} {round(recall, 2)}"
    stem = (f"Модель ({ctx}) выдаёт вероятность положительного класса. Что напечатает программа? "
            f"Запишите вывод точно в том виде, в каком его печатает Python.")
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"Порог {thr} включительно (>=); TP={tp}, FP={fp}, FN={fn}; "
                               "precision = TP/(TP+FP), recall = TP/(TP+FN).")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"thr": thr})
