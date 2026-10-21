"""data_ml.eval.t21_threshold_confusion_output — predict_output (набор t21, порог Senior): матрица ошибок при
пороге классификации — скоры, равные порогу, и цепочки сравнений с bool.

Предсказания — список bool ``s >= t`` или ``s > t`` (по варианту); в списке есть скоры, РАВНЫЕ порогу. TP/FP/FN/TN
считаются суммами сравнений: ``p == y == 1`` и ``p == y == 0`` — цепочки сравнений (``p == y and y == 1``), а не
``(p == y) == 1``; ``p > y`` и ``p < y`` сравнивают bool с int (True == 1). Затем полнота целой арифметикой
``tp * 100 // (tp + fn)``. Ловушки: скор на пороге при ``>`` / ``>=``, чтение цепочки как ``(p == y) == 1`` (тогда
TP посчитал бы и верные отрицательные), сравнение bool с числом, целочисленное деление. Ключ — независимая модель
в генераторе (явные ветки по классу и метке); проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.eval.t21_threshold_confusion_output"

CTX = [("антифрод платежей", "мошенническая операция"), ("отток абонентов", "абонент уйдёт"),
       ("модерация отзывов", "токсичный отзыв"), ("кредитный скоринг", "дефолт по кредиту"),
       ("поиск брака на конвейере", "деталь с браком")]
THRESH = [40, 45, 50, 55, 60, 65, 70]
NAMES = [("scores", "labels", "preds"), ("proba", "y_true", "y_pred"), ("s_val", "y_val", "pred")]


def _sc(v: int) -> str:
    return repr(v / 100)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, target = rng.choice(CTX)
    strict = rng.random() < 0.5
    sv, lv, pv = rng.choice(NAMES)
    for _ in range(2000):
        t = rng.choice(THRESH)
        n = rng.randint(8, 10)
        n_eq = rng.randint(2, 3)
        others = [rng.choice([x for x in range(10, 96) if x != t]) for _ in range(n - n_eq)]
        sc = others + [t] * n_eq
        rng.shuffle(sc)
        ys = [rng.choice([0, 1]) for _ in range(n)]
        eq_labels = [ys[i] for i in range(n) if sc[i] == t]
        if len(set(eq_labels)) < 2:
            continue                      # на пороге есть и положительные, и отрицательные
        tp = fp = fn = tn = 0
        for s, y in zip(sc, ys):
            pred = (s > t) if strict else (s >= t)
            if pred and y == 1:
                tp += 1
            elif pred and y == 0:
                fp += 1
            elif not pred and y == 1:
                fn += 1
            else:
                tn += 1
        if min(tp, fp, fn, tn) == 0 or tp + fn == 0:
            continue
        # полнота не целая — видно, что деление целочисленное
        if (tp * 100) % (tp + fn) == 0:
            continue
        break
    else:
        raise RuntimeError("t21_threshold_confusion: не собрались скоры")
    op = ">" if strict else ">="
    recall = tp * 100 // (tp + fn)
    code = (f"{sv} = [{', '.join(_sc(x) for x in sc)}]\n"
            f"{lv} = {ys}\n"
            f"t = {_sc(t)}\n"
            f"{pv} = [s {op} t for s in {sv}]\n"
            f"tp = sum(p == y == 1 for p, y in zip({pv}, {lv}))\n"
            f"fp = sum(p > y for p, y in zip({pv}, {lv}))\n"
            f"fn = sum(p < y for p, y in zip({pv}, {lv}))\n"
            f"tn = sum(p == y == 0 for p, y in zip({pv}, {lv}))\n"
            "print(tp, fp, fn, tn)\n"
            "print(tp * 100 // (tp + fn))")
    out = f"{tp} {fp} {fn} {tn}\n{recall}"
    n_eq = sc.count(t)
    eq_pos = sum(1 for s, y in zip(sc, ys) if s == t and y == 1)
    expl = (f"Порог {_sc(t)}, сравнение «{op}»: скоров, равных порогу, {n_eq} (из них положительных {eq_pos}) — они "
            + ("НЕ попадают в положительный класс (строгое >)" if strict else "попадают в положительный класс (>=)")
            + ". p — bool, а True == 1, False == 0. «p == y == 1» — цепочка сравнений: p == y и y == 1, то есть "
            f"верно предсказанные положительные, TP = {tp}; «p > y» — предсказан 1 при метке 0, FP = {fp}; «p < y» — "
            f"предсказан 0 при метке 1, FN = {fn}; «p == y == 0» — TN = {tn}. Полнота: {tp} * 100 // ({tp} + {fn}) = "
            f"{recall} (целочисленное деление). Ловушка — прочитать цепочку как (p == y) == 1 или ошибиться со "
            f"скором, равным порогу.")
    stem = (f"Оценка классификатора ({ctx}, класс 1 — {target}): программа переводит вероятности в метки по порогу "
            f"и считает матрицу ошибок и полноту в процентах.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"scores": sc, "labels": ys, "t": t, "strict": strict}, language="python")
