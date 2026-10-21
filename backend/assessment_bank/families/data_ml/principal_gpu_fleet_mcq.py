"""data_ml.serving.principal_gpu_fleet_mcq — mcq_concept (Principal, у границы Lead): парк GPU для обслуживания модели.

Дана таблица нагрузочного теста одной GPU (размер пакета динамического пакетирования → пропускная способность и
p95 задержки), требование p95 ≤ S мс, средний поток и коэффициент пика, предел загрузки u (выше него p95 растёт
нелинейно) и требование пережить потерю одной зоны из z в пик. Сколько GPU нужно минимум (поровну по зонам)?

Ключ: пропускная способность c — у наибольшего пакета, укладывающегося в S; в зону — n = ⌈пик / ((z − 1)·c·u)⌉;
всего z·n. Ловушки одной формы (число GPU), ранг ключа задаётся по seed до подбора чисел (0–3 ниже ключа) и
выбирается через spread_pick. Ключ проверяется исполнением: программа выбирает пакет по таблице, затем перебирает
число GPU в зоне и для каждой возможной потери зоны проверяет, что оставшиеся GPU держат пик при пределе загрузки.
"""
from __future__ import annotations

import math

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import pick_traps, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, text_table

FAMILY_ID = "data_ml.serving.principal_gpu_fleet_mcq"

CONTEXTS = ["модель ранжирования ленты", "модель распознавания речи в колл-центре", "языковую модель подсказок",
            "модель поиска похожих товаров", "модель оценки заявок на кредит", "модель модерации изображений"]
BATCHES = [1, 2, 4, 8, 16, 32]

PROGRAM = """import math
table = {table!r}          # пакет -> (запросов/с на одну GPU, p95 мс)
sla, avg, peak_k, util, zones = {sla}, {avg}, {peak_k}, {util}, {zones}
ok = [b for b, (thr, p95) in table.items() if p95 <= sla]
cap = max(table[b][0] for b in ok)
peak = avg * peak_k
n = 1
while True:
    # потеря любой одной зоны: остаются zones - 1 зон по n GPU
    if all((zones - 1) * n * cap * util >= peak - 1e-9 for _lost in range(zones)):
        break
    n += 1
total = zones * n
opts = __OPTS__
hit = [k for k, t in opts.items() if int(t.split(" ")[0]) == total]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _need(load, cap, util, zones, survive=True):
    if survive:
        return zones * math.ceil(load / ((zones - 1) * cap * util) - 1e-9)
    return zones * math.ceil(load / (zones * cap * util) - 1e-9)


WHY = {
    "batch1": "без пакетирования (пропускная способность пакета 1)",
    "prev_batch": "взят пакет на ступень меньше максимального допустимого по SLA",
    "two_zones": "запас на потерю двух зон одновременно вместо одной",
    "each_zone": "каждая зона держит весь пик в одиночку",
    "avg": "средний поток вместо пика",
    "no_zone": "пик поровну на все зоны без запаса на потерю зоны",
    "no_sla": "самый большой пакет, хотя его p95 выше требования",
    "no_cap": "без предела загрузки",
}


def _sample(rng):
    l0 = rng.choice([40, 60, 80, 120])
    alpha = rng.choice([0.12, 0.18, 0.25])
    eff = rng.choice([0.6, 0.7])
    lat = {b: round(l0 * (1 + alpha * (b - 1)) / 5) * 5 for b in BATCHES}
    thr = {b: round(eff * b * 1000 / lat[b]) for b in BATCHES}
    best = rng.choice([2, 4, 8, 16])
    nxt = BATCHES[BATCHES.index(best) + 1]
    sla = int(math.floor((lat[best] + lat[nxt]) / 2 / 10) * 10)
    return {"l0": l0, "alpha": alpha, "eff": eff, "lat": lat, "thr": thr, "best": best, "sla": sla,
            "avg": rng.choice([150, 250, 300, 450, 600, 900, 1200, 1800, 2500]),
            "peak_k": rng.choice([1.6, 2.0, 2.5, 3.0]),
            "util": rng.choice([0.6, 0.7, 0.75]), "zones": rng.choice([3, 4])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_above = make_rng(FAMILY_ID, seed // 4, "rank").sample(range(4), 4)[seed % 4]

    def accept(p):
        if not (p["lat"][p["best"]] <= p["sla"] < p["lat"][BATCHES[BATCHES.index(p["best"]) + 1]]):
            return None
        if len(set(p["thr"].values())) < len(BATCHES):
            return None
        cap, peak, u, z = p["thr"][p["best"]], p["avg"] * p["peak_k"], p["util"], p["zones"]
        good = _need(peak, cap, u, z)
        if not (12 <= good <= 85):
            return None
        prev_b = BATCHES[max(0, BATCHES.index(p["best"]) - 1)]
        alln = {
            "batch1": _need(peak, p["thr"][1], u, z),
            "prev_batch": _need(peak, p["thr"][prev_b], u, z),
            "two_zones": z * math.ceil(peak / (max(1, z - 2) * cap * u) - 1e-9),
            "each_zone": z * math.ceil(peak / (cap * u) - 1e-9),
            "avg": _need(p["avg"], cap, u, z),
            "no_zone": _need(peak, cap, u, z, survive=False),
            "no_sla": _need(peak, p["thr"][32], u, z),
            "no_cap": _need(peak, cap, 1.0, z),
        }
        cand = {k: v for k, v in alln.items() if v != good and 10 <= v <= 99}
        traps = pick_traps(rng, good, cand, n_above, rel=0.10, abs_min=2)
        if traps is None:
            return None
        return good, cand, traps

    p, (good, alln, traps) = search(rng, _sample, accept)
    rows = [(b, p["thr"][b], p["lat"][b]) for b in BATCHES]
    table = text_table(["Пакет", "Запросов/с на одну GPU", "p95, мс"], rows)
    stem = (f"Вы планируете бюджет мощности на год: {ctx}, синхронный ответ, требование p95 ≤ {p['sla']} мс. "
            f"Нагрузочный тест одной GPU с динамическим пакетированием (сервер ждёт, пока наберётся пакет):\n"
            f"{table}\n"
            f"Средний поток — {fmt_num(p['avg'], 0)} запросов/с, в пиковый час — в {ru_num(p['peak_k'])} раза больше. "
            f"Выше {fmt_num(100 * p['util'], 0)} % загрузки p95 растёт нелинейно, поэтому загрузку выше этого предела "
            f"не планируют. GPU стоят поровну в {p['zones']} зонах доступности; в пик сервис обязан пережить потерю любой одной "
            f"зоны без нарушения p95. Сколько GPU нужно минимум?")
    cap, peak = p["thr"][p["best"]], p["avg"] * p["peak_k"]
    n_zone = good // p["zones"]
    gpu = lambda n: f"{n} GPU"
    expl = (f"Пакет — наибольший с p95 ≤ {p['sla']} мс: {p['best']} ({cap} запросов/с на GPU). Пик — "
            f"{fmt_num(peak, 0)} запросов/с; после потери зоны остаются {p['zones'] - 1} из {p['zones']}, на них при "
            f"загрузке {fmt_num(p['util'], 2)} нужно ⌈{fmt_num(peak, 0)} / ({p['zones'] - 1} × {cap} × "
            f"{fmt_num(p['util'], 2)})⌉ = {n_zone} GPU в зоне, всего {gpu(good)}. Ловушки: " +
            "; ".join(f"{WHY[t]} — {gpu(alln[t])}" for t in traps) + ".")
    program = PROGRAM.format(table={b: (p["thr"][b], p["lat"][b]) for b in BATCHES}, sla=p["sla"], avg=p["avg"],
                             peak_k=p["peak_k"], util=p["util"], zones=p["zones"])
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=gpu(good),
                       distractors=[gpu(alln[t]) for t in traps], program=program, explanation=expl,
                       params={"sla": p["sla"], "avg": p["avg"], "peak_k": p["peak_k"], "util": p["util"],
                               "zones": p["zones"], "best_batch": p["best"], "gpus": good, "n_above": n_above,
                               "traps": {t: alln[t] for t in traps}},
                       note="Ответ проверяется программой: выбор пакета по таблице и перебор числа GPU в зоне с "
                            "проверкой каждой возможной потери зоны.")
