"""common.python.principal_worker_fleet_mcq — mcq_concept (Principal): сколько узлов под синхронные воркеры Python.

Синхронный WSGI-сервер: воркер-процесс обслуживает один запрос за раз. Запрос — c мс CPU и w мс ожидания ввода-
вывода; пик λ запросов в секунду. Воркеров нужно λ·(c + w)/1000 / ρ (закон Литтла, занятость ρ), CPU — λ·c/1000
ядер с загрузкой не выше u; на узле K ядер и M ГБ памяти, воркер — m ГБ, под систему — 2 ГБ. Ответ — наименьшее
число узлов, при котором хватает и воркеров по памяти, и CPU. Ловушки: только CPU, только память, без ожидания
ввода-вывода, «воркеров = 2·ядра + 1» (правило по умолчанию), без запаса занятости.
"""
from __future__ import annotations

from math import ceil

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.python.principal_worker_fleet_mcq"
CONTEXTS = ["API личного кабинета", "сервис отчётов", "бэкенд админки магазина", "сервис генерации PDF",
            "API расписаний", "сервис подписи документов", "бэкенд CRM", "API поиска по каталогу"]

MODEL = '''
from math import ceil

def nodes(P, cpu=True, mem=True, io=True, rho=True, rule=False, cpu_io=False, sys_mem=True, util=True):
    workers = -(-(P["lam"] * (P["c"] + (P["w"] if io else 0)) * 100) // (1000 * (P["rho"] if rho else 100)))
    per_node_mem = (P["M"] - (2 if sys_mem else 0)) * 1024 // P["m"]
    if rule:
        per_node_mem = min(per_node_mem, 2 * P["K"] + 1)
    need_mem = -(-workers // per_node_mem) if mem else 0
    cpu_ms = P["c"] + (P["w"] if cpu_io else 0)
    need_cpu = -(-(P["lam"] * cpu_ms * 100) // (1000 * P["K"] * (P["u"] if util else 100))) if cpu else 0
    return max(need_mem, need_cpu, 1)

def answer(P):
    return nodes(P)

def brute(P):
    n = 1
    while True:
        wk = n * ((P["M"] - 2) * 1024 // P["m"])
        busy_x = P["lam"] * (P["c"] + P["w"]) * 100          # занято воркеров × 1000 × 100
        cpu_x = P["lam"] * P["c"] * 100
        if busy_x <= wk * P["rho"] * 1000 and cpu_x <= n * P["K"] * P["u"] * 1000:
            return n
        n += 1

def traps(P):
    return {"cpu_only": nodes(P, mem=False), "mem_only": nodes(P, cpu=False), "no_io": nodes(P, io=False),
            "rule_2k1": nodes(P, rule=True), "no_rho": nodes(P, rho=False), "no_io_no_rho": nodes(P, io=False, rho=False),
            "double": nodes(P) * 2, "cpu_with_io": nodes(P, cpu_io=True),
            "no_sys_mem": nodes(P, sys_mem=False), "cpu_full": nodes(P, util=False, mem=False)}

def fmt(x):
    if x % 10 == 1 and x % 100 != 11:
        return f"{x} узел"
    if 2 <= x % 10 <= 4 and not 12 <= x % 100 <= 14:
        return f"{x} узла"
    return f"{x} узлов"
'''


def _sample(rng):
    return {"lam": rng.choice([1200, 2000, 3000, 4000, 6000]), "c": rng.choice([5, 8, 10, 15, 20, 30]),
            "w": rng.choice([40, 60, 80, 120, 200, 300]), "rho": rng.choice([70, 75, 80]),
            "K": rng.choice([4, 8, 16]), "u": rng.choice([60, 70]), "M": rng.choice([8, 16, 32]),
            "m": rng.choice([256, 300, 400, 512])}


def _accept(P, ns):
    return 6 <= ns["answer"](P) <= 90


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]} на Python работает под синхронным WSGI-сервером: каждый воркер-процесс "
            f"обслуживает один запрос за раз. Запрос тратит в среднем {P['c']} мс CPU и {P['w']} мс ждёт БД и внешние "
            f"API; пик — {num(P['lam'])} запросов в секунду. Чтобы не росла очередь, воркеры заняты не больше чем на "
            f"{P['rho']} %, CPU узла загружен не больше чем на {P['u']} %. Узел: {P['K']} ядер, {P['M']} ГБ памяти, "
            f"под систему — 2 ГБ, воркер занимает {P['m']} МБ (число воркеров на узле ограничено только "
            "памятью).\n\nСколько узлов нужно в пик?")


def _explain(P, a, traps):
    busy = P["lam"] * (P["c"] + P["w"]) / 1000
    per = (P["M"] - 2) * 1024 // P["m"]
    return (f"Закон Литтла: одновременно занято λ·(c + w) = {num(busy, 1)} воркеров, при занятости {P['rho']} % нужно "
            f"{-(-(P['lam'] * (P['c'] + P['w']) * 100) // (1000 * P['rho']))}; на узел по памяти — {per} воркеров. CPU: λ·c = "
            f"{num(P['lam'] * P['c'] / 1000, 1)} ядра при загрузке {P['u']} %. Узлов нужно по большему из двух "
            f"ограничений — {a}. Правило «2·ядра + 1» относится к асинхронной/CPU-нагрузке, у синхронных воркеров с "
            "ожиданием ввода-вывода оно занижает число воркеров.")


TRAP_DESC = {"cpu_only": "только по CPU", "mem_only": "только по памяти", "no_io": "без ожидания ввода-вывода",
             "rule_2k1": "воркеров на узле по правилу 2·ядра + 1", "no_rho": "без запаса занятости воркеров",
             "no_io_no_rho": "без ввода-вывода и без запаса", "double": "двойной запас",
             "cpu_with_io": "ожидание ввода-вывода посчитано как CPU",
             "no_sys_mem": "без памяти под систему", "cpu_full": "по CPU с загрузкой 100 %"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.0, abs_min=1, trap_first="cpu_only",
                           trap_desc=TRAP_DESC, n_above_choices=(0, 1, 2, 3))
