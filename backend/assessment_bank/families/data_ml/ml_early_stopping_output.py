"""data_ml.ml.early_stopping_output — predict_output: ранняя остановка с patience и min_delta.

Переобучение: метрика на обучении продолжает улучшаться, а на валидации выходит на плато и
ухудшается. Ранняя остановка запоминает лучшую эпоху и останавливает обучение, если
улучшения больше min_delta нет patience эпох подряд. Ловушки: улучшение меньше min_delta не
сбрасывает счётчик, сравнение ``>=``/``>`` с patience, нумерация эпох с 0 или 1, направление
метрики (loss минимизируем, AUC максимизируем), цикл может закончиться без остановки.
Ключ считается независимой моделью и сверяется с исполнением показанного кода.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.ml.early_stopping_output"

CONTEXTS = ["классификация изображений товаров", "прогноз спроса", "распознавание речи",
            "скоринг заявок", "рекомендации", "классификация обращений в поддержку"]


def _series(rng, mode, n):
    """Ряд метрики на валидации: быстрое улучшение, затем шумное плато и ухудшение."""
    if mode == "loss":
        v = rng.uniform(0.85, 1.2)
        out = []
        for e in range(n):
            if e < rng.randint(2, 4):
                v -= rng.uniform(0.05, 0.14)
            else:
                v += rng.choice([-1, 1, 1]) * rng.uniform(0.001, 0.012)
            out.append(round(v, 3))
        return out
    v = rng.uniform(0.62, 0.72)
    out = []
    for e in range(n):
        if e < rng.randint(2, 4):
            v += rng.uniform(0.02, 0.06)
        else:
            v += rng.choice([1, -1, -1]) * rng.uniform(0.001, 0.012)
        out.append(round(min(v, 0.99), 3))
    return out


def _model(values, mode, patience, delta, start, strict):
    best = float("inf") if mode == "loss" else float("-inf")
    best_epoch, wait, epoch, margins = 0, 0, None, []
    stopped = False
    for i, x in enumerate(values):
        epoch = i + start
        bound = best - delta if mode == "loss" else best + delta
        if bound not in (float("inf"), float("-inf")):
            margins.append(abs(x - bound))
        better = x < bound if mode == "loss" else x > bound
        if better:
            best, best_epoch, wait = x, epoch, 0
        else:
            wait += 1
            if (wait > patience) if strict else (wait >= patience):
                stopped = True
                break
    return epoch, best_epoch, best, stopped, min(margins), wait


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    mode = rng.choice(["loss", "auc"])
    name = "val_loss" if mode == "loss" else "val_auc"
    for _ in range(2000):
        n = rng.randint(8, 11)
        values = _series(rng, mode, n)
        patience = rng.choice([2, 3])
        delta = rng.choice([0.002, 0.005, 0.01])
        start = rng.choice([0, 1])
        strict = rng.random() < 0.4
        epoch, best_epoch, best, stopped, margin, _ = _model(values, mode, patience, delta, start, strict)
        # нет сравнений «впритык» (плавающая точка) и есть ловушка «улучшение < min_delta»
        small = any(0 < (values[i - 1] - values[i] if mode == "loss" else values[i] - values[i - 1]) < delta
                    for i in range(1, n))
        if margin > 1e-6 and small and (stopped or rng.random() < 0.15) and best_epoch - start >= 2:
            break
    else:
        raise RuntimeError("не удалось подобрать ряд")
    init = 'float("inf")' if mode == "loss" else 'float("-inf")'
    cond = f"{name[4:]} < best - min_delta" if mode == "loss" else f"{name[4:]} > best + min_delta"
    var = name[4:]
    stop = "wait > patience" if strict else "wait >= patience"
    loop = f"for epoch, {var} in enumerate({name}, start={start}):" if start else \
        f"for epoch, {var} in enumerate({name}):"
    code = "\n".join([
        f"{name} = {values!r}",
        f"patience = {patience}",
        f"min_delta = {delta}",
        f"best, best_epoch, wait = {init}, 0, 0",
        loop,
        f"    if {cond}:",
        f"        best, best_epoch, wait = {var}, epoch, 0",
        "    else:",
        "        wait += 1",
        f"        if {stop}:",
        "            break",
        "print(epoch, best_epoch, best)"])
    out = f"{epoch} {best_epoch} {best}"
    stem = (f"Обучение нейросети ({ctx}): метрика на обучении продолжает улучшаться, а на "
            f"валидации после нескольких эпох выходит на плато — признак переобучения. Команда "
            f"добавила раннюю остановку. Что напечатает программа? Запишите вывод точно в том "
            f"виде, в каком его печатает Python.")
    expl = (f"Улучшением считается только изменение больше min_delta = {delta}; меньшие "
            f"улучшения увеличивают wait. Лучшая эпоха {best_epoch} ({name} = {best}); "
            + (f"остановка на эпохе {epoch}, когда {stop}." if stopped else
               f"остановки не было, цикл дошёл до последней эпохи {epoch}.")
            + (" Эпохи нумеруются с 0." if start == 0 else " Эпохи нумеруются с 1."))
    ak = AnswerKey(kind="output", value=out, explanation=expl)
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"mode": mode, "patience": patience, "min_delta": delta,
                                 "start": start, "strict": strict, "stopped": stopped})
