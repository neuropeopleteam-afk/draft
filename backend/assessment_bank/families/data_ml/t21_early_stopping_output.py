"""data_ml.train.t21_early_stopping_output — predict_output (набор t21, порог Senior): ранняя остановка объектом
с состоянием на двух запусках обучения подряд.

Класс EarlyStopping хранит best, best_epoch и счётчик терпения wait: улучшение — только если
``loss < best - min_delta`` (потери на валидации ×1000, целые), при улучшении wait сбрасывается, иначе растёт;
step() возвращает ``wait == patience``. Два запуска (подбор скорости обучения) идут подряд, и по варианту объект
создаётся ОДИН раз до цикла по запускам (состояние переходит во второй запуск: best и best_epoch от первого,
wait уже равен patience — и после следующего «неулучшения» станет больше, так что ``==`` больше не сработает,
пока не случится улучшение) или заново в начале каждого запуска. После каждого запуска печатаются лучшая эпоха,
эпоха остановки (последняя пройденная) и best. Ловушки: улучшение меньше min_delta не обновляет best и не
сбрасывает wait; время жизни объекта (состояние между запусками); ``==`` при перескоке счётчика. Ключ —
независимая модель (явный автомат состояний) в генераторе; проверка — исполнение показанного кода в песочнице
Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.train.t21_early_stopping_output"

CTX = ["классификатор обращений в поддержку", "модель оттока абонентов", "ранжирование выдачи поиска",
       "распознавание товаров на фото", "прогноз спроса по магазинам"]
NAMES = [("stopper", "runs", "losses"), ("es", "trials", "val_loss"), ("early", "sweeps", "curve")]


def _run_curve(rng, start_lo, start_hi, n):
    """Кривая потерь на валидации ×1000: быстрый спуск, затем плато с мелкими колебаниями."""
    v = rng.randint(start_lo, start_hi)
    out = [v]
    drop_epochs = rng.randint(1, 3)
    for e in range(1, n):
        if e <= drop_epochs:
            v -= rng.randint(15, 70)
        else:
            v += rng.choice([-9, -6, -4, -3, -2, 2, 3, 5, 8])
        out.append(v)
    return out


def _simulate(runs, patience, min_delta, shared):
    """Явная модель: состояние (best, best_epoch, wait); при shared — одно на оба запуска."""
    res = []
    state = None
    for losses in runs:
        if state is None or not shared:
            state = [10 ** 6, 0, 0]
        last = 0
        stopped = False
        for epoch, loss in enumerate(losses, start=1):
            last = epoch
            if loss < state[0] - min_delta:
                state = [loss, epoch, 0]
            else:
                state[2] += 1
            if state[2] == patience:
                stopped = True
                break
        res.append((state[1], last, state[0], stopped, state[2]))
    return res


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    shared = rng.random() < 0.6
    sv, rv, lv = rng.choice(NAMES)
    for _ in range(3000):
        patience = rng.randint(2, 3)
        min_delta = rng.choice([3, 4, 5, 6])
        n1, n2 = rng.randint(5, 7), rng.randint(5, 7)
        r1 = _run_curve(rng, 880, 990, n1)
        r2 = _run_curve(rng, 860, 990, n2)
        if min(r1 + r2) < 500:
            continue
        res = _simulate([r1, r2], patience, min_delta, shared)
        alt = _simulate([r1, r2], patience, min_delta, not shared)
        if res[1][:3] == alt[1][:3]:
            continue                      # время жизни объекта должно менять ответ по второму запуску
        # первое улучшение меньше min_delta где-то случилось (ловушка порога улучшения)
        small = any(0 < (min(rr[:i]) - rr[i]) <= min_delta for rr in (r1, r2) for i in range(1, len(rr)))
        if not small:
            continue
        break
    else:
        raise RuntimeError("t21_early_stopping: не собрались кривые")
    init = f"        {sv} = EarlyStopping(patience={patience}, min_delta={min_delta})\n"
    head = (f"{rv} = [{r1}, {r2}]\n" + (init.strip() + "\n" if shared else "") +
            f"for {lv} in {rv}:\n" + ("    " + init.strip() + "\n" if not shared else ""))
    code = ("class EarlyStopping:\n"
            "    def __init__(self, patience, min_delta):\n"
            "        self.patience, self.min_delta = patience, min_delta\n"
            "        self.best, self.best_epoch, self.wait = 10**6, 0, 0\n"
            "\n"
            "    def step(self, epoch, loss):\n"
            "        if loss < self.best - self.min_delta:\n"
            "            self.best, self.best_epoch, self.wait = loss, epoch, 0\n"
            "        else:\n"
            "            self.wait += 1\n"
            "        return self.wait == self.patience\n"
            "\n"
            + head +
            f"    for epoch, loss in enumerate({lv}, start=1):\n"
            f"        if {sv}.step(epoch, loss):\n"
            "            break\n"
            f"    print({sv}.best_epoch, epoch, {sv}.best)")
    out = "\n".join(f"{b} {e} {best}" for b, e, best, _s, _w in res)
    parts = []
    for idx, (b, e, best, stopped, wait) in enumerate(res, 1):
        parts.append(f"запуск {idx}: лучшая эпоха {b} (best = {best}), "
                     + (f"остановка на эпохе {e} (wait == {patience})" if stopped
                        else f"остановки не было — цикл прошёл все {e} эпох (wait = {wait})"))
    b1, _e1, best1, stopped1, wait1 = res[0]
    if shared:
        life = (f"Объект создан один раз до цикла, поэтому второй запуск продолжает его состояние: best = {best1} "
                f"(эпоха {b1} первого запуска), wait = {wait1}; улучшением считается только loss < {best1} − "
                f"{min_delta}.")
        if wait1 == patience and not r2[0] < best1 - min_delta:
            life += (f" Уже на первой эпохе второго запуска wait станет {patience + 1} > patience, и проверка "
                     f"wait == patience не сработает, пока не случится улучшение.")
    else:
        life = ("Объект создаётся заново в начале каждого запуска, поэтому второй запуск начинается с чистого "
                "состояния.")
    expl = (f"Улучшение — только loss < best − {min_delta}; меньшее снижение не обновляет best и увеличивает wait. "
            + life + " По шагам: " + "; ".join(parts) + f". Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Подбор скорости обучения ({ctx}): два запуска обучения подряд с ранней остановкой по потерям на "
            f"валидации (потери умножены на 1000 и округлены до целых).")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"runs": [r1, r2], "patience": patience, "min_delta": min_delta,
                                  "shared": shared}, language="python")
