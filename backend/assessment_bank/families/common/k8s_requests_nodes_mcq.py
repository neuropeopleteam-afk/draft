"""common.k8s.k8s_requests_nodes_mcq — mcq_concept (Senior/Lead, Kubernetes): сколько узлов под реплики по requests.

Планировщик размещает поды по requests (не по limits) в пределах allocatable узла за вычетом DaemonSet-подов. Под:
requests CPU и памяти, limits больше. Ответ — ⌈N / min(⌊CPU свободно / req⌋, ⌊память свободно / req⌋)⌉. Ловушки: по
limits, без DaemonSet, только CPU, только память, по capacity вместо allocatable. ``brute`` — жадное размещение по
одному поду (first fit).
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import numeric_variant
from assessment_bank.gen_utils import plural

FAMILY_ID = "common.k8s.k8s_requests_nodes_mcq"
CONTEXTS = ["воркеры обработки заказов", "API поиска", "консьюмеры событий", "сервис рендеринга превью", "API профилей",
            "воркеры отчётов", "сервис расчёта цен", "шлюз уведомлений"]

MODEL = '''
def per_node(P, limits=False, ds=True, cpu=True, mem=True, capacity=False):
    cpu_free = (P["cap_cpu"] if capacity else P["alloc_cpu"]) - (P["ds_cpu"] if ds else 0)
    mem_free = (P["cap_mem"] if capacity else P["alloc_mem"]) - (P["ds_mem"] if ds else 0)
    rc = P["lim_cpu"] if limits else P["req_cpu"]
    rm = P["lim_mem"] if limits else P["req_mem"]
    k = []
    if cpu:
        k.append(cpu_free // rc)
    if mem:
        k.append(mem_free // rm)
    return min(k)

def nodes(P, **kw):
    k = per_node(P, **kw)
    return None if k <= 0 else -(-P["N"] // k)

def answer(P):
    return nodes(P)

def brute(P):
    free = []
    for _ in range(P["N"]):
        for f in free:
            if f[0] >= P["req_cpu"] and f[1] >= P["req_mem"]:
                f[0] -= P["req_cpu"]; f[1] -= P["req_mem"]
                break
        else:
            free.append([P["alloc_cpu"] - P["ds_cpu"] - P["req_cpu"], P["alloc_mem"] - P["ds_mem"] - P["req_mem"]])
    return len(free)

def traps(P):
    return {"limits": nodes(P, limits=True), "no_ds": nodes(P, ds=False), "cpu_only": nodes(P, mem=False),
            "mem_only": nodes(P, cpu=False), "capacity": nodes(P, capacity=True),
            "limits_no_ds": nodes(P, limits=True, ds=False)}

def fmt(x):
    if x % 10 == 1 and x % 100 != 11:
        return f"{x} узел"
    if 2 <= x % 10 <= 4 and not 12 <= x % 100 <= 14:
        return f"{x} узла"
    return f"{x} узлов"
'''


def _sample(rng):
    cap_cpu = rng.choice([8000, 16000, 32000])
    cap_mem = cap_cpu // 1000 * rng.choice([2048, 4096, 8192])
    return {"N": rng.choice([24, 36, 40, 60, 80, 120, 150]), "cap_cpu": cap_cpu, "alloc_cpu": cap_cpu - rng.choice([200, 400, 600]),
            "cap_mem": cap_mem, "alloc_mem": cap_mem - rng.choice([1024, 1536, 2048]),
            "ds_cpu": rng.choice([300, 500, 800]), "ds_mem": rng.choice([512, 768, 1024]),
            "req_cpu": rng.choice([250, 500, 750, 1000]), "lim_cpu": 0, "req_mem": rng.choice([512, 768, 1024, 1536, 2048]),
            "lim_mem": 0, "_f": rng.choice([2, 3, 4])}


def _accept(P, ns):
    P["lim_cpu"] = P["req_cpu"] * P["_f"]
    P["lim_mem"] = P["req_mem"] * 2
    a = ns["answer"](P)
    return a is not None and 2 <= a <= 60


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]}: нужно {P['N']} реплик. Под: requests — cpu {P['req_cpu']}m, memory "
            f"{P['req_mem']}Mi; limits — cpu {P['lim_cpu']}m, memory {P['lim_mem']}Mi. Узел пула: capacity — cpu "
            f"{P['cap_cpu']}m, memory {P['cap_mem']}Mi; allocatable — cpu {P['alloc_cpu']}m, memory {P['alloc_mem']}Mi. "
            f"На каждом узле работают DaemonSet-поды (логи, мониторинг, сеть) с requests cpu {P['ds_cpu']}m и memory "
            f"{P['ds_mem']}Mi. Других подов в пуле нет.\n\nСколько узлов нужно, чтобы планировщик разместил все реплики?")


def _explain(P, a, traps):
    c = (P["alloc_cpu"] - P["ds_cpu"]) // P["req_cpu"]
    m = (P["alloc_mem"] - P["ds_mem"]) // P["req_mem"]
    return (f"Планировщик сравнивает requests с allocatable минус уже размещённые поды (DaemonSet). На узел влезает "
            f"по CPU {c}, по памяти {m} {plural(m, 'под', 'пода', 'подов')} — берём меньшее, {min(c, m)}; "
            f"⌈{P['N']} / {min(c, m)}⌉ = {a}. Limits на размещение не влияют.")


TRAP_DESC = {"limits": "по limits вместо requests", "no_ds": "без DaemonSet-подов", "cpu_only": "только по CPU",
             "mem_only": "только по памяти", "capacity": "по capacity вместо allocatable",
             "limits_no_ds": "по limits и без DaemonSet"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.0, abs_min=1, trap_first="limits", trap_desc=TRAP_DESC)
