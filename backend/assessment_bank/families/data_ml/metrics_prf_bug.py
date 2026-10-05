"""data_ml.metrics.prf_bug — find_bug: ошибка в формуле precision / recall / F1 или в подсчёте TP/FP/FN.

Кандидату показывают функцию отчёта по бинарной классификации и пример, посчитанный
аналитиком вручную: какая-то метрика не сходится. Нужно найти строку с дефектом.
Подтипы (одна строка меняется в исправлении):
* precision делится на (tp + fn);
* recall делится на (tp + fp);
* F1 — среднее арифметическое вместо гармонического;
* ветка FN считает и истинно отрицательные (условие ``t != positive``).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.metrics.prf_bug"

# (контекст, положительный класс, отрицательный класс, что ищем)
CONTEXTS = [
    ("антифрод", '"fraud"', '"ok"', "мошеннические транзакции"),
    ("спам-фильтр", '"spam"', '"ham"', "спам"),
    ("прогноз оттока", "1", "0", "уходящих клиентов"),
    ("медицинский скрининг", '"sick"', '"healthy"', "пациентов с заболеванием"),
    ("модерация отзывов", '"toxic"', '"clean"', "токсичные отзывы"),
    ("контроль качества", '"defect"', '"good"', "бракованные изделия"),
]
SUBTYPES = ["precision_den", "recall_den", "f1_mean", "fn_branch"]


def _code(subtype: str, fn: str, pos_default: str, names: tuple[str, str]) -> tuple[str, int]:
    t, p = names
    lines = [f"def {fn}(y_true, y_pred, positive={pos_default}):",
             "    tp = fp = fn = 0",
             f"    for {t}, {p} in zip(y_true, y_pred):",
             f"        if {p} == positive and {t} == positive:",
             "            tp += 1",
             f"        elif {p} == positive:",
             "            fp += 1",
             (f"        elif {t} != positive:" if subtype == "fn_branch" else f"        elif {t} == positive:"),
             "            fn += 1",
             ("    precision = tp / (tp + fn) if tp + fn else 0.0" if subtype == "precision_den"
              else "    precision = tp / (tp + fp) if tp + fp else 0.0"),
             ("    recall = tp / (tp + fp) if tp + fp else 0.0" if subtype == "recall_den"
              else "    recall = tp / (tp + fn) if tp + fn else 0.0"),
             ("    f1 = (precision + recall) / 2" if subtype == "f1_mean"
              else "    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0"),
             "    return round(precision, 3), round(recall, 3), round(f1, 3)"]
    key = {"fn_branch": 8, "precision_den": 10, "recall_den": 11, "f1_mean": 12}.get(subtype, 0)
    return "\n".join(lines), key


def _metrics(y_true, y_pred, pos, subtype="good"):
    tp = fp = fn = 0
    for t, p in zip(y_true, y_pred):
        if p == pos and t == pos:
            tp += 1
        elif p == pos:
            fp += 1
        elif (t != pos) if subtype == "fn_branch" else (t == pos):
            fn += 1
    precision = (tp / (tp + fn) if tp + fn else 0.0) if subtype == "precision_den" else \
        (tp / (tp + fp) if tp + fp else 0.0)
    recall = (tp / (tp + fp) if tp + fp else 0.0) if subtype == "recall_den" else \
        (tp / (tp + fn) if tp + fn else 0.0)
    if subtype == "f1_mean":
        f1 = (precision + recall) / 2
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 3), round(recall, 3), round(f1, 3)


def _sample(rng, pos, neg, subtype):
    for _ in range(5000):
        n = rng.randint(8, 11)
        y_true = [rng.choice([pos, neg]) for _ in range(n)]
        y_pred = [rng.choice([pos, neg]) for _ in range(n)]
        tp = sum(t == pos and p == pos for t, p in zip(y_true, y_pred))
        fp = sum(t != pos and p == pos for t, p in zip(y_true, y_pred))
        fn = sum(t == pos and p != pos for t, p in zip(y_true, y_pred))
        if tp < 2 or fp < 1 or fn < 1 or fp == fn:
            continue
        good, bad = _metrics(y_true, y_pred, pos), _metrics(y_true, y_pred, pos, subtype)
        if good != bad:
            return y_true, y_pred, good, bad
    raise RuntimeError("не удалось подобрать пример")


def _lit(v):
    return v.strip('"') if v.startswith('"') else v


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pos_src, neg_src, what = rng.choice(CONTEXTS)
    subtype = rng.choice(SUBTYPES)
    fn = rng.choice(["binary_report", "classification_metrics", "prf_scores", "eval_binary"])
    names = rng.choice([("t", "p"), ("actual", "predicted"), ("y", "y_hat"), ("truth", "guess")])
    pos = int(pos_src) if pos_src.isdigit() else _lit(pos_src)
    neg = int(neg_src) if neg_src.isdigit() else _lit(neg_src)
    buggy, key_line = _code(subtype, fn, pos_src, names)
    fixed, _ = _code("good", fn, pos_src, names)
    assert changed_lines(buggy, fixed) == {key_line}
    y_true, y_pred, good, bad = _sample(rng, pos, neg, subtype)
    # отдельный тестовый набор для проверки исполнением
    t_true, t_pred, t_good, _ = _sample(rng, pos, neg, subtype)
    test = (f"assert {fn}({y_true!r}, {y_pred!r}) == {good!r}\n"
            f"assert {fn}({t_true!r}, {t_pred!r}) == {t_good!r}")
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Функция `{fn}` считает precision, recall и F1 для модели, которая ищет {what} "
            f"({ctx}). Аналитик проверил её на небольшом примере вручную:\n"
            f"y_true = {y_true!r}\ny_pred = {y_pred!r}\n"
            f"Вручную получилось (precision, recall, F1) = {good!r}, а функция вернула {bad!r}. "
            f"Укажите номер строки с ошибкой.")
    why = {"precision_den": "precision = TP / (TP + FP), а в коде в знаменателе FN",
           "recall_den": "recall = TP / (TP + FN), а в коде в знаменателе FP",
           "f1_mean": "F1 — гармоническое среднее 2PR / (P + R), а не среднее арифметическое",
           "fn_branch": "FN — это положительные объекты, предсказанные как отрицательные; "
                        "условие `!= positive` считает вместо них истинно отрицательные"}[subtype]
    ak = AnswerKey(kind="line", value=key_line, explanation=f"Строка {key_line}: {why}.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="metric_formula",
                         params={"fixed_code": fixed, "subtype": subtype})
