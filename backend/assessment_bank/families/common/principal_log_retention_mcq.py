"""common.linux.principal_log_retention_mcq — mcq_concept (Principal): сколько ротаций журнала (rotate N) влезает в диск.

Сервис пишет журнал w ГБ в сутки, logrotate ротирует ежедневно с compress и delaycompress: текущий файл (до суток
записи) и самый свежий ротированный файл не сжаты, остальные сжаты с коэффициентом c. На диске D ГБ, под систему и
данные занято S ГБ; перед ротацией (пик) должен оставаться свободным запас не меньше q % диска. Вопрос: наибольшее
rotate N. Пик: S + w (текущий) + w (свежий ротированный, delaycompress) + (N − 1)·w·c ≤ D·(1 − q). Ловушки: без
delaycompress, без текущего файла, без запаса, все архивы несжатые, запас от свободного места вместо диска.
``brute`` — посуточная имитация заполнения диска при каждом N.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.linux.principal_log_retention_mcq"
CONTEXTS = ["журнал доступа nginx", "журнал приложения платёжного шлюза", "аудит-журнал базы", "журнал очереди задач",
            "журнал прокси API", "журнал сервиса авторизации", "журнал ETL-заданий", "журнал почтового шлюза"]

MODEL = '''
def best(P, delay=True, current=True, reserve=True, compress=True, free_based=False):
    D, S, w, c, q = P["D"], P["S"], P["w"], P["c"] / 100, P["q"] / 100
    limit = (D - S) * (1 - q) if free_based else D * (1 - q if reserve else 1)
    n = 0
    while n < 400:
        m = n + 1
        old = (m - 1) if delay else m
        used = S + (w if current else 0) + (w if delay else 0) + old * w * (c if compress else 1)
        if used > limit + 1e-9:
            break
        n = m
    return n

def answer(P):
    return best(P)

def brute(P):
    out = 0
    for n in range(1, 400):
        rotated = []                       # от свежего к старому: (сжат?, размер)
        peak = 0.0
        for day in range(n + 3):
            current = P["w"]               # за сутки записан текущий файл; пик — перед ротацией
            peak = max(peak, P["S"] + current + sum(sz for _z, sz in rotated))
            rotated = [(False, current)] + [(True, P["w"] * P["c"] / 100) for _z, _sz in rotated]
            rotated = rotated[:n]
        if peak <= P["D"] * (1 - P["q"] / 100) + 1e-9:
            out = n
        else:
            break
    return out

def traps(P):
    return {"no_delay": best(P, delay=False), "no_current": best(P, current=False), "no_reserve": best(P, reserve=False),
            "no_compress": best(P, compress=False), "free_based": best(P, free_based=True),
            "no_delay_no_current": best(P, delay=False, current=False)}

def fmt(x):
    return f"rotate {x}"
'''


def _sample(rng):
    return {"D": rng.choice([100, 200, 250, 500, 1000]), "S": rng.choice([20, 30, 40, 60]),
            "w": rng.choice([4, 6, 8, 10, 12, 16, 20]), "c": rng.choice([8, 10, 12, 15, 20]),
            "q": rng.choice([10, 15, 20, 25])}


def _accept(P, ns):
    return 6 <= ns["answer"](P) <= 300


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]}: сервис пишет ≈ {P['w']} ГБ в сутки, logrotate ротирует файл раз в сутки с "
            f"`compress` и `delaycompress`, сжатый архив занимает {P['c']} % исходного размера. Диск — {P['D']} ГБ, под "
            f"систему и данные занято {P['S']} ГБ (не растёт). Политика эксплуатации: в пик (перед ротацией) свободно не "
            f"меньше {P['q']} % объёма диска.\n\nКакое наибольшее значение `rotate N` (число хранимых ротированных "
            "файлов) можно задать?")


def _explain(P, a, traps):
    return (f"Перед ротацией на диске: текущий файл (сутки записи, {P['w']} ГБ), самый свежий ротированный — не сжат "
            f"из-за delaycompress ({P['w']} ГБ), остальные N − 1 — сжаты ({num(P['w'] * P['c'] / 100, 1)} ГБ каждый). "
            f"Условие {P['S']} + {P['w']} + {P['w']} + (N − 1)·{num(P['w'] * P['c'] / 100, 1)} ≤ {P['D']}·(1 − "
            f"{num(P['q'] / 100, 2)}) выполняется до N = {a}.")


TRAP_DESC = {"no_delay": "без delaycompress (свежий архив тоже сжат)", "no_current": "без текущего файла",
             "no_reserve": "без запаса свободного места", "no_compress": "архивы без сжатия",
             "free_based": "запас посчитан от свободного места, а не от диска",
             "no_delay_no_current": "без delaycompress и без текущего файла"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.05, abs_min=2, trap_first="no_delay",
                           trap_desc=TRAP_DESC, n_above_choices=(0, 1, 2, 3))
