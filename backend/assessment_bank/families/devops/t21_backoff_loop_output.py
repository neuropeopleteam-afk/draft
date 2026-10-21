"""devops.retry.t21_backoff_loop_output — predict_output (набор t21, порог Стажёра): цикл for с накоплением суммы
(экспоненциальная пауза между повторами) в Python.

Клиент повторяет запрос к сервису: на каждой попытке прибавляет текущую паузу к суммарному ожиданию и умножает паузу.
После цикла печатаются последнее значение счётчика попыток, суммарное ожидание и пауза. Ловушки чтения: число
итераций `range(k)` и `range(1, k)`, счётчик после цикла хранит последнее значение (а не k), пауза после цикла уже
умножена ещё раз — больше последней прибавленной. Ключ — независимый расчёт в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.retry.t21_backoff_loop_output"

CTX = ["запрос к API склада", "отправка вебхука партнёру", "загрузка артефакта в хранилище",
       "проверка готовности базы", "регистрация в балансировщике", "запись метрик в хранилище",
       "получение секрета из хранилища"]
NAMES = [("delay", "waited", "attempt"), ("pause", "total", "try_no"), ("backoff", "slept", "i"),
         ("wait_s", "spent", "n"), ("sleep_s", "elapsed", "retry"), ("interval", "waited_s", "k")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    dv, wv, av = rng.choice(NAMES)
    d0 = rng.randint(1, 9)
    factor = rng.choice([2, 2, 3])
    k = rng.randint(3, 6 if factor == 2 else 4)
    start = rng.choice([0, 1])
    rng_expr = f"range({k})" if start == 0 else f"range(1, {k})"
    iters = k - start
    w0 = rng.choice([0, 0, 1])
    delay, waited, adds = d0, w0, []
    for _ in range(iters):
        adds.append(delay)
        waited += delay
        delay *= factor
    last = k - 1
    code = (f"{dv} = {d0}\n"
            f"{wv} = {w0}\n"
            f"for {av} in {rng_expr}:\n"
            f"    {wv} += {dv}\n"
            f"    {dv} *= {factor}\n"
            f"print({av}, {wv}, {dv})")
    out = f"{last} {waited} {delay}"
    expl = (f"{rng_expr} даёт {iters} {plural(iters, 'итерацию', 'итерации', 'итераций')} ({av} = {', '.join(str(x) for x in range(start, k))}), после цикла "
            f"{av} = {last}. К {wv} (было {w0}) прибавляются паузы {' + '.join(map(str, adds))} → {waited}. Пауза "
            f"умножается на {factor} на каждой итерации, в том числе после последнего прибавления: "
            f"{d0} × {factor}^{iters} = {delay}. Вывод: «{out}».")
    stem = f"Клиент повторяет операцию «{ctx}» с растущей паузой между попытками; код считает ожидание."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"d0": d0, "factor": factor, "k": k, "start": start, "w0": w0}, language="python")
