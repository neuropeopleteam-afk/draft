"""data_ml.train.t21_grad_accum_steps_output — predict_output (набор t21, порог Senior): накопление градиента по
батчам из генератора — drop_last, хвостовой шаг и исчерпание генератора между эпохами.

Функция-генератор batches() отдаёт размеры батчей ``min(bs, n - start)`` для ``start in range(0, stop, bs)``, где
при drop_last ``stop = n - n % bs`` (неполный последний батч отбрасывается). В цикле по эпохам шаг оптимизатора
делается каждые accum батчей (``if (i + 1) % accum == 0``) и, по варианту, «хвостовой» шаг на остатке
(``if count % accum``). По варианту генератор создаётся ОДИН раз до цикла по эпохам (после первой эпохи он
исчерпан: следующие эпохи не видят ни одного батча и не делают шагов) или заново в каждой эпохе. Печатаются число
батчей, размер последнего батча и шаги после первой эпохи, затем шаги за все эпохи. Ловушки: drop_last и размер
последнего батча, (i + 1) % accum, хвостовой шаг, генератор одноразовый. Ключ — независимая целочисленная модель
в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.train.t21_grad_accum_steps_output"

CTX = ["дообучение языковой модели на обращениях", "классификатор изображений товаров",
       "модель распознавания речи", "ранжирующая модель поиска", "модель прогноза спроса"]
BS = [16, 24, 32, 48, 64, 96, 128]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    once = rng.random() < 0.55            # генератор создан один раз до цикла по эпохам
    drop_last = rng.random() < 0.5
    tail = rng.random() < 0.6
    for _ in range(3000):
        bs = rng.choice(BS)
        n = rng.randint(6 * bs, 22 * bs)
        if n % bs == 0:
            continue
        accum = rng.randint(2, 5)
        epochs = rng.randint(2, 4)
        full, rest = divmod(n, bs)
        sizes = [bs] * full + ([] if drop_last or rest == 0 else [rest])
        n_b = len(sizes)
        if n_b % accum == 0:
            continue                      # остаток батчей есть — хвостовой шаг имеет значение
        if n % 10 == 0:
            continue
        break
    else:
        raise RuntimeError("t21_grad_accum_steps: не собрались параметры")
    per_epoch = n_b // accum + (1 if tail and n_b % accum else 0)
    total = per_epoch if once else per_epoch * epochs
    last = sizes[-1]
    gen_call = f"batches(n, bs, drop_last={drop_last})"
    loop_src = "loader" if once else gen_call
    code = ("def batches(n, bs, drop_last):\n"
            "    stop = n - n % bs if drop_last else n\n"
            "    for start in range(0, stop, bs):\n"
            "        yield min(bs, n - start)\n"
            "\n"
            f"n, bs, accum, epochs = {n}, {bs}, {accum}, {epochs}\n"
            + (f"loader = {gen_call}\n" if once else "") +
            "steps = 0\n"
            "for epoch in range(epochs):\n"
            "    count = 0\n"
            f"    for i, size in enumerate({loop_src}):\n"
            "        count += 1\n"
            "        if (i + 1) % accum == 0:\n"
            "            steps += 1\n"
            + ("    if count % accum:\n"
               "        steps += 1\n" if tail else "") +
            "    if epoch == 0:\n"
            "        print(count, size, steps)\n"
            "print(steps)")
    out = f"{n_b} {last} {per_epoch}\n{total}"
    stop = n - n % bs if drop_last else n
    b_txt = (f"drop_last=True: stop = {n} - {n} % {bs} = {stop}, батчей {n_b} по {bs}, неполный остаток "
             f"{n % bs} отброшен" if drop_last else
             f"drop_last=False: батчей {n_b} — {full} по {bs} и последний из {rest} ({n} - {full * bs})")
    s_txt = (f"шаг на каждом {accum}-м батче: {n_b} // {accum} = {n_b // accum}"
             + (f", плюс хвостовой шаг на остатке {n_b % accum} батч(а) → {per_epoch}" if tail else
                f", остаток {n_b % accum} батч(а) шага не даёт → {per_epoch}"))
    e_txt = (f"Генератор создан один раз до цикла и после первой эпохи исчерпан: в следующих эпохах count = 0, "
             f"шагов нет, итого {total}." if once else
             f"Генератор создаётся заново в каждой эпохе: {per_epoch} * {epochs} = {total}.")
    trap = ("забыть, что генератор одноразовый" if once else
            "решить, что генератор исчерпан, хотя он создаётся в каждой эпохе заново")
    expl = (f"{b_txt}; размер последнего батча {last}. За эпоху — {s_txt}. {e_txt} Ловушка — {trap}, или ошибиться "
            f"с (i + 1) % accum и последним неполным батчем.")
    stem = (f"Обучение с накоплением градиента ({ctx}): из-за ограничения памяти шаг оптимизатора делается раз в "
            f"несколько батчей, и программа считает батчи и шаги.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "bs": bs, "accum": accum, "epochs": epochs, "drop_last": drop_last,
                                  "tail": tail, "once": once}, language="python")
