"""data_ml.metrics.invariance_mcq — mcq_concept: какая метрика не изменится при преобразовании.

Три сценария:

* ``prior_shift`` — в продакшене негативов стало в m раз больше при тех же распределениях
  скоров внутри классов (дисбаланс вырос): не меняются ROC-AUC и recall (TPR) при пороге;
  precision, F1, accuracy и PR-AUC меняются;
* ``monotonic`` — скоры заменили строго возрастающим преобразованием (квадрат, корень,
  температурное шкалирование): ранжирование прежнее — не меняются ROC-AUC и PR-AUC;
  log-loss, Brier и пороговые метрики при прежнем пороге меняются;
* ``threshold`` — сдвинули порог классификации: беспороговые ROC-AUC, PR-AUC, log-loss,
  Brier не меняются, пороговые метрики меняются.

Ключ задаётся понятийно (какая метрика инвариантна) и проверяется исполнением: программа
на конкретной выборке считает метрики до и после преобразования (ROC-AUC — попарно, вручную)
и печатает, какие из предложенных не изменились. Генератор подбирает выборку так, что
каждый дистрактор на ней действительно меняется.
"""
from __future__ import annotations

import math

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options, check_lengths

FAMILY_ID = "data_ml.metrics.invariance_mcq"

CONTEXTS = ["антифрод", "прогноз оттока", "кредитный скоринг", "спам-фильтр", "модерация",
            "медицинский скрининг", "предсказание клика"]

METRICS_SRC = r'''
import math


def _confusion(y, s, thr):
    tp = sum(1 for t, v in zip(y, s) if t == 1 and v >= thr)
    fp = sum(1 for t, v in zip(y, s) if t == 0 and v >= thr)
    fn = sum(1 for t, v in zip(y, s) if t == 1 and v < thr)
    tn = len(y) - tp - fp - fn
    return tp, fp, fn, tn


def m_roc(y, s, thr):
    pos = [v for t, v in zip(y, s) if t == 1]
    neg = [v for t, v in zip(y, s) if t == 0]
    tot = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return tot / (len(pos) * len(neg))


def m_ap(y, s, thr):
    order = sorted(range(len(s)), key=lambda i: -s[i])
    hits, acc = 0, 0.0
    for k, i in enumerate(order, 1):
        if y[i] == 1:
            hits += 1
            acc += hits / k
    return acc / hits


def m_prec(y, s, thr):
    tp, fp, fn, tn = _confusion(y, s, thr)
    return tp / (tp + fp) if tp + fp else 0.0


def m_rec(y, s, thr):
    tp, fp, fn, tn = _confusion(y, s, thr)
    return tp / (tp + fn)


def m_f1(y, s, thr):
    tp, fp, fn, tn = _confusion(y, s, thr)
    return 2 * tp / (2 * tp + fp + fn)


def m_acc(y, s, thr):
    tp, fp, fn, tn = _confusion(y, s, thr)
    return (tp + tn) / len(y)


def m_logloss(y, s, thr):
    return -sum(math.log(v) if t == 1 else math.log(1 - v) for t, v in zip(y, s)) / len(y)


def m_brier(y, s, thr):
    return sum((v - t) ** 2 for t, v in zip(y, s)) / len(y)
'''

LABELS = {"roc": "ROC-AUC (площадь под ROC)",
          "ap": "PR-AUC (средняя точность, AP)",
          "prec": "Precision {at}",
          "rec": "Recall (TPR) {at}",
          "f1": "F1-мера {at}",
          "acc": "Accuracy {at}",
          "logloss": "Log-loss (кросс-энтропия)",
          "brier": "Brier score (средний квадрат)"}

SCENARIOS = {
    "prior_shift": dict(correct=["roc", "rec"], distractors=["prec", "f1", "acc", "ap"]),
    "monotonic": dict(correct=["roc", "ap"], distractors=["logloss", "brier", "acc", "f1", "prec"]),
    "threshold": dict(correct=["roc", "ap", "logloss", "brier"], distractors=["prec", "rec", "f1", "acc"]),
}

TRANSFORMS = {"square": ("s ** 2", "квадрат скора", lambda v: v ** 2),
              "sqrt": ("s ** 0.5", "квадратный корень из скора", lambda v: v ** 0.5),
              "temp": ("1 / (1 + ((1 - s) / s) ** 0.5)",
                       "скор после температурного шкалирования логита с T = 2",
                       lambda v: 1 / (1 + ((1 - v) / v) ** 0.5))}

WHY = {
    "prior_shift": {
        "roc": "TPR и FPR считаются внутри своих классов, поэтому ROC-кривая и площадь под ней "
               "не зависят от соотношения классов",
        "rec": "recall = TP / (TP + FN) считается только по позитивам, а их распределение скоров "
               "прежнее",
        "ap": "PR-AUC падает: при каждом пороге над ним оказывается больше негативов, precision ниже",
        "prec": "precision = TP / (TP + FP), а FP выросло вместе с числом негативов",
        "f1": "F1 включает precision, которая упала",
        "acc": "accuracy взвешивает классы по их доле: вес ошибок на негативах вырос"},
    "monotonic": {
        "roc": "ROC-AUC зависит только от порядка объектов, а строго возрастающее преобразование "
               "его сохраняет",
        "ap": "PR-AUC (AP) зависит только от порядка объектов, поэтому сохраняется",
        "logloss": "log-loss зависит от самих значений вероятностей, а они изменились",
        "brier": "Brier score зависит от самих значений вероятностей, а они изменились",
        "prec": "при прежнем пороге часть объектов перешла через порог",
        "f1": "при прежнем пороге часть объектов перешла через порог",
        "acc": "при прежнем пороге часть объектов перешла через порог"},
    "threshold": {
        "roc": "ROC-AUC не зависит от порога — это интеграл по всем порогам",
        "ap": "PR-AUC не зависит от порога — это усреднение по всем порогам",
        "logloss": "log-loss считается по вероятностям, порог в нём не участвует",
        "brier": "Brier score считается по вероятностям, порог в нём не участвует",
        "prec": "precision пересчитывается по новой матрице ошибок",
        "rec": "recall пересчитывается по новой матрице ошибок",
        "f1": "F1 пересчитывается по новой матрице ошибок",
        "acc": "accuracy пересчитывается по новой матрице ошибок"},
}


def _times(m):
    return f"в {m} раза" if m in (2, 3, 4) else f"в {m} раз"


def _metrics_ns():
    ns: dict = {}
    exec(compile(METRICS_SRC, "<metrics>", "exec"), ns)  # детерминированный код банка
    return ns


_NS = _metrics_ns()


def _sample(rng, n):
    y = [1] * rng.randint(n // 4, n // 2)
    y += [0] * (n - len(y))
    rng.shuffle(y)
    used, s = set(), []
    for t in y:
        while True:
            v = round(min(0.97, max(0.03, rng.gauss(0.62 if t else 0.38, 0.17))), 3)
            if v not in used:
                used.add(v)
                s.append(v)
                break
    return y, s


def _apply(scen, y, s, m, tname, thr, thr2):
    if scen == "prior_shift":
        y2 = y + [t for t in y if t == 0] * (m - 1)
        s2 = s + [v for t, v in zip(y, s) if t == 0] * (m - 1)
        return y2, s2, thr
    if scen == "monotonic":
        f = TRANSFORMS[tname][2]
        return y, [f(v) for v in s], thr
    return y, s, thr2


def _unchanged(names, y, s, y2, s2, thr, thr_after):
    out = []
    for nm in names:
        a = _NS["m_" + nm](y, s, thr)
        b = _NS["m_" + nm](y2, s2, thr_after)
        if abs(a - b) < 1e-12:
            out.append(nm)
    return out


PROGRAM_TAIL = '''

Y = {y!r}
S = {s!r}
THR = {thr!r}
{transform}
OPTIONS = {names!r}
same = []
for name in OPTIONS:
    before = globals()["m_" + name](Y, S, THR)
    after = globals()["m_" + name](Y2, S2, THR2)
    if abs(before - after) < 1e-12:
        same.append(name)
print(" ".join(same))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    scen = rng.choice(sorted(SCENARIOS))
    sc = SCENARIOS[scen]
    correct = rng.choice(sc["correct"])
    m = rng.choice([3, 5, 10])
    tname = rng.choice(sorted(TRANSFORMS))
    # при T-шкалировании точка 0,5 неподвижна, поэтому порог 0,5 там не берём
    thr = rng.choice([0.4, 0.6] if scen == "monotonic" and tname == "temp" else [0.4, 0.5, 0.6])
    thr2 = rng.choice([t for t in (0.3, 0.35, 0.45, 0.55, 0.65, 0.7) if abs(t - thr) > 0.04])
    for _ in range(300):
        y, s = _sample(rng, rng.randint(30, 44))
        chosen = rng.sample(sc["distractors"], 3)
        y2, s2, thr_after = _apply(scen, y, s, m, tname, thr, thr2)
        names = [correct] + chosen
        if _unchanged(names, y, s, y2, s2, thr, thr_after) == [correct]:
            break
    else:
        raise RuntimeError("не удалось подобрать выборку")
    t_txt = str(thr).replace(".", ",")
    at = "при рабочем пороге" if scen == "threshold" else f"при пороге {t_txt}"
    labels = {k: v.format(at=at) for k, v in LABELS.items()}
    texts = [labels[n] for n in names]
    check_lengths(texts)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (labels[correct], None),
                                 [(labels[d], None) for d in chosen])
    order = [next(n for n in names if labels[n] == o.text) for o in opts]
    if scen == "prior_shift":
        what = (f"В продакшене дисбаланс вырос: на каждый позитивный объект теперь приходится "
                f"{_times(m)} больше негативных, чем в валидационной выборке, а распределения скоров "
                f"внутри каждого класса не изменились (модель та же, порог {t_txt}).")
        transform = (f"Y2 = Y + [t for t in Y if t == 0] * {m - 1}\n"
                     f"S2 = S + [v for t, v in zip(Y, S) if t == 0] * {m - 1}\nTHR2 = THR")
    elif scen == "monotonic":
        expr, desc, _ = TRANSFORMS[tname]
        what = (f"Перед выдачей скор модели s заменили на {desc} (`{expr}`) — это строго "
                f"возрастающее преобразование, порядок объектов не меняется; порог {t_txt} "
                f"оставили прежним.")
        transform = f"Y2 = Y\nS2 = [{expr} for s in S]\nTHR2 = THR"
    else:
        what = (f"Порог классификации сдвинули с {t_txt} на {str(thr2).replace('.', ',')}; "
                f"модель и выборка не менялись. «Рабочий порог» в вариантах — порог, по которому "
                f"модель принимает решения (до сдвига и после).")
        transform = f"Y2 = Y\nS2 = S\nTHR2 = {thr2!r}"
    program = METRICS_SRC + PROGRAM_TAIL.format(y=y, s=s, thr=thr, transform=transform,
                                                names=order)
    stem = (f"Бинарный классификатор ({ctx}) выдаёт вероятность положительного класса. {what} "
            f"Какая из метрик гарантированно не изменится?")
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Верно: {labels[correct]} — {WHY[scen][correct]}. Остальные "
                                "меняются: " + "; ".join(f"{labels[d]} — {WHY[scen][d]}"
                                                         for d in chosen) + "."))
    checks = [Check(name="invariance", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=correct, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Код не показывается: программа считает метрики на "
                                           "сгенерированной выборке до и после преобразования.",
                         params={"scenario": scen, "correct": correct, "distractors": chosen,
                                 "m": m, "transform": tname, "thr": thr, "thr2": thr2})
