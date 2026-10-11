"""data_ml.serving.lead_batching_mcq — mcq_concept (Lead): настройка динамического пакетирования модели под SLO.

Сервер модели на GPU пакетирует запросы: если в очереди набралось max_batch — запускает пакет сразу,
иначе ждёт, пока наберётся max_batch или старейший запрос прождёт timeout, и запускает то, что есть.
Время пакета — a + b · n мс (n — размер пакета). Поток распределяется по G одинаковым GPU поровну,
запросы приходят равномерно. Даны четыре конфигурации (max_batch, timeout); вопрос — какая требует
меньше всего GPU при p99 задержки ≤ SLO.

Ловушки: самый большой пакет (лучшая пропускная способность, но ожидание набора съедает бюджет p99),
без пакетирования (каждый запрос платит накладные a), короткое ожидание при большом пакете и т. п.;
верная конфигурация меняется между вариантами. Генератор подбирает параметры так, что минимум G
единственный, отрыв ≥ 1 GPU, ожидание каждой конфигурации меньше SLO и выполнимы хотя бы три из четырёх;
max_batch у четырёх конфигураций различны, место верной по max_batch (2–4) выбирается равновероятно до
подбора (версия 2).
Ключ проверяется исполнением: программа заново проигрывает очередь каждого GPU по событиям (своя
реализация, не код генератора), ищет минимальное G для каждой конфигурации и печатает букву.
"""
from __future__ import annotations

import math

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.serving.lead_batching_mcq"

CONTEXTS = ["ранжирование ленты", "антифрод платежей", "поиск похожих товаров", "распознавание речи в звонках",
            "классификация обращений", "модерация картинок"]

POOL = [(1, 0), (4, 1), (8, 2), (8, 5), (16, 3), (16, 10), (32, 4), (32, 15), (64, 8), (64, 25), (128, 20)]

N_ARR, WARM = 700, 150

PROGRAM = """opts = __OPTS__
configs = {configs!r}      # подпись варианта -> (max_batch, timeout_ms)
rate, slo, a, b = {rate}, {slo}, {a}, {b}

def p99(per_gpu_rate, B, T, n={n}, warm={warm}):
    step = 1000.0 / per_gpu_rate
    queue, lat = [], {{}}
    nxt, now = 0, 0.0
    while nxt < n or queue:
        while nxt < n and nxt * step <= now + 1e-9:
            queue.append(nxt); nxt += 1
        if not queue:
            now = nxt * step
            continue
        if len(queue) < B:
            deadline = queue[0] * step + T
            k = nxt + (B - len(queue)) - 1          # индекс прихода, который доберёт пакет
            fill = k * step if k < n else float("inf")
            now = max(now, min(deadline, fill))
            while nxt < n and nxt * step <= now + 1e-9:
                queue.append(nxt); nxt += 1
        run, queue = queue[:B], queue[B:]
        now += a + b * len(run)
        for j in run:
            lat[j] = now - j * step
    xs = sorted(v for j, v in lat.items() if j >= warm)
    return xs[int(0.99 * (len(xs) - 1))]

def min_gpus(B, T):
    g = max(1, int(rate * (a + b * B) / (1000.0 * B)))
    top = 3 * g + 20                                 # дальше рост G только удлиняет ожидание набора
    while g <= top:
        if p99(rate / g, B, T) <= slo:
            return g
        g += 1
    return 10 ** 9

need = {{name: min_gpus(*cfg) for name, cfg in configs.items()}}
best = min(need.values())
win = [name for name, g in need.items() if g == best]
hit = [k for k, t in opts.items() if len(win) == 1 and t == win[0]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _p99(per_gpu_rate: float, B: int, T: float, a: float, b: float) -> float:
    """Генератор: очередь по пакетам (индексы прихода), p99 после прогрева."""
    dt = 1000.0 / per_gpu_rate
    arr = [i * dt for i in range(N_ARR)]
    t, i, q, lat = 0.0, 0, [], []
    while i < N_ARR or q:
        while i < N_ARR and arr[i] <= t + 1e-9:
            q.append(i)
            i += 1
        if not q:
            t = arr[i]
            continue
        if len(q) < B:
            need = B - len(q)
            fill = arr[i + need - 1] if i + need - 1 < N_ARR else math.inf
            t = max(t, min(arr[q[0]] + T, fill))
            while i < N_ARR and arr[i] <= t + 1e-9:
                q.append(i)
                i += 1
        batch, q = q[:B], q[B:]
        t += a + b * len(batch)
        lat += [(j, t - arr[j]) for j in batch]
    xs = sorted(v for j, v in lat if j >= WARM)
    return xs[int(0.99 * (len(xs) - 1))]


def _min_gpus(rate: float, B: int, T: float, a: float, b: float, slo: float) -> int:
    g = max(1, int(rate * (a + b * B) / (1000.0 * B)))
    top = 3 * g + 20
    while g <= top:
        if _p99(rate / g, B, T, a, b) <= slo:
            return g
        g += 1
    return 10 ** 9


def _label(B: int, T: int) -> str:
    return "без пакетирования (max_batch = 1)" if B == 1 else f"max_batch = {B}, ожидание до {T} мс"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    # место верной конфигурации по max_batch среди четырёх — 2, 3 или 4 равновероятно (самый малый пакет при
    # трёх выполнимых конфигурациях почти никогда не минимален); при неудаче подбора — другое место
    want = rng.choice([2, 3, 4])
    found = False
    for want in (want, *rng.sample([r for r in (2, 3, 4) if r != want], 2)):
        if found:
            break
        for _ in range(500):
            rate = rng.choice([1500, 3000, 6000, 12000])
            a = rng.choice([3, 5, 8])
            b = rng.choice([0.2, 0.4, 0.6])
            slo = rng.choice([20, 30, 45, 60])
            cfgs = rng.sample([c for c in POOL if c[1] < slo], 4)
            need = {c: _min_gpus(rate, c[0], c[1], a, b, slo) for c in cfgs}
            if sum(g < 10 ** 9 for g in need.values()) < 3:   # сравнивать есть что: выполнимы хотя бы три
                continue
            vals = sorted(need.values())
            if vals[0] >= 10 ** 9 or vals[1] - vals[0] < 1:
                continue
            best = min(need, key=need.get)
            batches = sorted(c[0] for c in cfgs)
            if len(set(batches)) != 4 or batches.index(best[0]) + 1 != want:
                continue                      # иначе «средний по размеру пакет» угадывается без расчёта
            found = True
            break
    if not found:
        raise RuntimeError("не удалось подобрать параметры")
    labels = {c: _label(*c) for c in cfgs}
    stem = (f"Модель «{ctx}» обслуживается на GPU с динамическим пакетированием: если в очереди набралось max_batch "
            f"запросов — пакет запускается сразу, иначе сервер ждёт, пока наберётся max_batch или старейший запрос "
            f"прождёт заданное время, и запускает то, что есть. Время обработки пакета из n запросов — "
            f"{a} + {fmt_num(b, 1)} · n мс. Поток — {fmt_num(rate, 0)} запросов в секунду, равномерно, делится поровну между G "
            f"одинаковыми GPU. Требование — p99 задержки (ожидание в очереди + обработка) не больше {slo} мс.\n\n"
            "Какая конфигурация позволяет выполнить требование на наименьшем числе GPU?")
    good = labels[best]
    expl = (f"Минимальное число GPU при p99 ≤ {slo} мс: " +
            "; ".join(f"{labels[c]} — {need[c] if need[c] < 10 ** 9 else 'не выполнимо'}" for c in cfgs) +
            f". Минимум — {good}. Большой пакет лучше по пропускной способности, но ожидание набора и время "
            "самого пакета входят в задержку; без пакетирования каждый запрос платит накладные "
            f"{a} мс.")
    program = PROGRAM.format(configs={labels[c]: c for c in cfgs}, rate=rate, slo=slo, a=a, b=b, n=N_ARR, warm=WARM)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good,
                       distractors=[labels[c] for c in cfgs if c != best], program=program, explanation=expl,
                       params={"rate": rate, "a": a, "b": b, "slo": slo, "configs": [list(c) for c in cfgs],
                               "need": [need[c] for c in cfgs], "best": list(best)},
                       note="Ответ проверяется программой: очередь каждого GPU проигрывается по событиям для каждой "
                            "конфигурации, ищется минимальное число GPU.")
