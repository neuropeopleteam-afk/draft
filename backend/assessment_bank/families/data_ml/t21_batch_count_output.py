"""data_ml.batches.t21_batch_count_output — predict_output (набор t21, порог Стажёра): число батчей и границы
последнего батча при обходе выборки range(0, n, batch_size).

Программа идёт по началам батчей с шагом batch_size, для каждого считает конец min(start + batch_size, n)
и число шагов; после цикла печатает число шагов и границы последнего батча (переменные цикла сохраняют последние
значения). Ловушки чтения: последний неполный батч тоже даёт шаг (шагов — округление n / batch_size вверх),
последнее значение start — наибольшее кратное batch_size, меньшее n, конец обрезается до n. Ключ — независимый
расчёт в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_ml.batches.t21_batch_count_output"

CTX = [("пакетный скоринг клиентов", "клиентов"), ("расчёт эмбеддингов документов", "документов"),
       ("разметка изображений моделью", "изображений"), ("инференс по журналу транзакций", "транзакций"),
       ("обучение на отзывах покупателей", "отзывов")]
NAMES = [("n_samples", "batch_size", "steps"), ("n_rows", "bs", "batches"), ("total", "size", "calls"),
         ("dataset_len", "batch", "n_steps")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, unit = rng.choice(CTX)
    nv, bv, sv = rng.choice(NAMES)
    full = rng.random() < 0.15                     # иногда n делится на batch_size нацело
    for _ in range(500):
        bs = rng.randint(4, 16)
        n = rng.randint(2 * bs + 1, 6 * bs)
        if (n % bs == 0) != full:
            continue
        break
    else:
        raise RuntimeError("t21_batch_count: не собрались размеры")
    starts = list(range(0, n, bs))
    steps, last_start = len(starts), starts[-1]
    last_end = min(last_start + bs, n)
    code = (f"{nv} = {n}\n"
            f"{bv} = {bs}\n"
            f"{sv} = 0\n"
            f"for start in range(0, {nv}, {bv}):\n"
            f"    end = min(start + {bv}, {nv})\n"
            f"    {sv} += 1\n"
            f"print({sv}, start, end)")
    out = f"{steps} {last_start} {last_end}"
    shown = ", ".join(map(str, starts[:3])) + (", …, " + str(last_start) if steps > 4 else
                                               "".join(", " + str(x) for x in starts[3:]))
    tail = (f"последний батч неполный: {last_end - last_start} из {bs}" if last_end - last_start < bs else
            "все батчи полные")
    expl = (f"range(0, {n}, {bs}) даёт начала {shown} — всего {steps} {plural(steps, 'шаг', 'шага', 'шагов')}. После цикла start = {last_start} "
            f"(последнее значение range, а не {n}), end = min({last_start} + {bs}, {n}) = {last_end}; {tail}. "
            f"Ловушка — посчитать шаги как {n} / {bs} с отбрасыванием остатка. Вывод: «{out}».")
    stem = (f"Задача «{ctx}»: выборка {unit} обрабатывается батчами фиксированного размера; программа "
            f"считает шаги и запоминает границы последнего батча.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"n": n, "batch_size": bs}, language="python")
