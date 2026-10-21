"""devops.k8s.lp3_rollout_pdb_steps_output — predict_output: сколько волн займёт выкатка с maxSurge и PDB.

Deployment из N подов, стратегия RollingUpdate с maxSurge и maxUnavailable, плюс PodDisruptionBudget minAvailable
(упрощённая модель команды: одновременно можно держать недоступными не больше min(maxUnavailable,
N − minAvailable) старых подов, а новых поднимать сверх N не больше maxSurge; волна = одновременная замена).
Узлы кластера вмещают ограниченное число подов этого сервиса — лишние новые поды не встанут. Ловушки: N / (surge +
unavailable) без PDB; не учесть ёмкость узлов; округление вниз. Ответ — число волн.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.k8s.lp3_rollout_pdb_steps_output"
SVCS = ["checkout-api", "search-api", "profile-svc", "billing-worker", "notify-gateway", "catalog-api"]

CALC = r'''
import re, math
v = {}
for l in DATA.splitlines():
    m = re.match(r"^([^:]+):\s*(\d+)", l)
    if m:
        v[m.group(1).strip()] = int(m.group(2))
N = v["replicas"]
unav = min(v["maxUnavailable"], N - v["PDB minAvailable"])
surge = min(v["maxSurge"], v["свободных мест под поды сервиса на узлах"])
print(math.ceil(N / (surge + unav)))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SVCS)
    for _ in range(3000):
        N = rng.randint(6, 40)
        surge = rng.randint(1, 8)
        unav = rng.randint(0, 6)
        mina = rng.randint(max(0, N - 8), N - 1)
        free = rng.randint(0, 10)
        u = min(unav, N - mina)
        s = min(surge, free)
        if u + s == 0:
            continue
        good = -(-N // (u + s))
        n1 = -(-N // max(1, surge + unav))       # без PDB и ёмкости
        n2 = -(-N // max(1, min(unav, N - mina) + surge))   # без ёмкости
        n3 = -(-N // max(1, unav + s))           # без PDB
        if good in (n1,) or len({good, n2, n3}) < 2 or good > 40:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"replicas: {N}", f"maxSurge: {surge}", f"maxUnavailable: {unav}", f"PDB minAvailable: {mina}",
                       f"свободных мест под поды сервиса на узлах: {free}"])
    stem = (f"Сервис {svc} выкатывается обновлением RollingUpdate. Модель команды для оценки окна выкатки: за одну "
            "волну одновременно заменяется не больше (новых подов сверх replicas) + (старых, которые можно держать "
            "недоступными); новых сверх replicas — не больше maxSurge и не больше свободных мест на узлах; "
            "недоступных — не больше maxUnavailable и не больше, чем разрешает PodDisruptionBudget. Сколько волн "
            "займёт замена всех подов? Ответ — целое число.")
    expl = (f"Недоступных одновременно: min({unav}, {N} − {mina}) = {u}; сверх replicas: min({surge}, {free}) = {s}. "
            f"Волн = ⌈{N} / ({u} + {s})⌉ = {good}. Без PDB и ёмкости узлов — {n1}, без ёмкости узлов — {n2}, "
            f"без PDB — {n3}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=svc,
                         accept=num_accept(good, ("волн", "волны")),
                         params={"N": N, "surge": surge, "unav": unav, "mina": mina, "free": free})
