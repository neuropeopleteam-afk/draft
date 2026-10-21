"""devops.k8s.pdb_disruptions_mcq — mcq_concept: сколько подов можно выселить по PodDisruptionBudget.

По спецификации Kubernetes (DisruptionController): desiredHealthy = ⌈minAvailable × replicas⌉ или
replicas − ⌈maxUnavailable × replicas⌉ (процент округляется вверх: intstr.GetScaledValueFromIntOrPercent(..., true));
disruptionsAllowed = max(0, currentHealthy − desiredHealthy), где currentHealthy — число подов в состоянии Ready.
Неготовые поды уже «съедают» бюджет выселений. Подтипы: min_available, max_unavailable (число или процент).
Ранг ключа задаётся по seed до подбора параметров (0–3 ниже ключа), ловушки отбираются через spread_pick.
Ключ — исполнение модели контроллера над показанным манифестом и списком подов в песочнице Python.
"""
from __future__ import annotations

import math

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural, spread_pick
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import emit, program

FAMILY_ID = "devops.k8s.pdb_disruptions_mcq"

CTX = [("API заказов", "orders-api"), ("шлюз платежей", "payments-gw"), ("поиск по каталогу", "search"),
       ("сервис уведомлений", "notifier"), ("кэш сессий", "session-cache"), ("рендер превью", "preview")]

MODEL = '''
import math

pdb = parse_yaml(PDB)["spec"]
pods = [line.split() for line in PODS.splitlines()[1:]]
healthy = sum(1 for p in pods if p[1].split("/")[0] == p[1].split("/")[1] and p[2] == "Running")


def scaled(v, total):
    v = str(v)
    return math.ceil(int(v[:-1]) * total / 100) if v.endswith("%") else int(v)


if "minAvailable" in pdb:
    desired = scaled(pdb["minAvailable"], REPLICAS)
else:
    desired = REPLICAS - scaled(pdb["maxUnavailable"], REPLICAS)
print(max(0, healthy - desired))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, app = rng.choice(CTX)
    sub = rng.choice(["min_available", "max_unavailable"])
    n_below = make_rng(FAMILY_ID, seed // 4, "rank").sample(range(4), 4)[seed % 4]
    for _ in range(3000):
        rep = rng.randint(7, 15)
        unready = rng.randint(1, 3)
        healthy = rep - unready
        pct = rng.random() < 0.65
        if sub == "min_available":
            if pct:
                p = rng.choice([25, 30, 35, 40, 50, 60, 65, 70])
                val, desired, desired_floor = f"{p}%", math.ceil(p * rep / 100), math.floor(p * rep / 100)
            else:
                v = rng.randint(2, rep - 4)
                val, desired, desired_floor = v, v, v
        else:
            if pct:
                p = rng.choice([25, 30, 35, 40, 50, 60, 65])
                mu, mu_floor = math.ceil(p * rep / 100), math.floor(p * rep / 100)
                val, desired, desired_floor = f"{p}%", rep - mu, rep - mu_floor
            else:
                v = rng.randint(3, rep - 3)
                val, desired, desired_floor = v, rep - v, rep - v
        right = max(0, healthy - desired)
        if not (3 <= right <= 6):
            continue
        cand_raw = {
            "zero": 0,
            "one_only": 1,
            "double_unready": right - unready,
            "strict_gt": right - 1,
            "plus_one": right + 1,
            "from_rep": rep - desired,
            "rounded": healthy - desired_floor,
            "plus_unready": right + unready,
            "desired_val": desired,
            "healthy_val": healthy,
        }
        cand = {}
        for k, x in cand_raw.items():
            if 0 <= x <= 9 and x != right and x not in cand.values():
                cand[k] = x
        below = [k for k, x in cand.items() if x < right]
        above = [k for k, x in cand.items() if x > right]
        if len(below) < n_below or len(above) < 3 - n_below:
            continue
        rng.shuffle(below)
        rng.shuffle(above)
        sp = spread_pick(rng, right, below, above, n_below, 3 - n_below, cand.__getitem__, min_step=0.05)
        if sp is not None:
            wrong = [x for _, x in sp]
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    key_field = "minAvailable" if sub == "min_available" else "maxUnavailable"
    manifest = {"apiVersion": "policy/v1", "kind": "PodDisruptionBudget",
                "metadata": {"name": f"{app}-pdb"},
                "spec": {key_field: val, "selector": {"matchLabels": {"app": app}}}}
    code = emit(manifest).rstrip("\n")
    names = [f"{app}-{rng.choice('6789bcdf')}{rng.randint(10, 99)}f{rng.randint(1, 9)}-{''.join(rng.sample('abcdxyzkmnpq', 5))}"
             for _ in range(rep)]
    bad = set(rng.sample(range(rep), unready))
    lines = ["NAME READY STATUS RESTARTS AGE"]
    for i, n in enumerate(names):
        if i in bad:
            st = rng.choice([("0/1", "Running"), ("0/1", "CrashLoopBackOff"), ("0/1", "Pending")])
        else:
            st = ("1/1", "Running")
        lines.append(f"{n} {st[0]} {st[1]} {rng.randint(0, 6) if i in bad else 0} {rng.randint(2, 40)}h")
    pods = "\n".join(lines)
    texts = {x: f"{x} {plural(x, 'под', 'пода', 'подов')}" for x in [right, *wrong]}
    opts, key = make_options(rng, (texts[right], None), [(texts[w], None) for w in wrong])
    stem = (f"Сервис «{ctx}»: Deployment `{app}` с replicas: {rep}, у него PodDisruptionBudget ниже. Вывод "
            f"`kubectl get pods -l app={app}` (колонки через пробел):\n{pods}\nАдминистратор собирается выполнить "
            "`kubectl drain` на узлах кластера. Сколько подов сервиса можно выселить прямо сейчас, пока не "
            "поднялись новые (status.disruptionsAllowed)?")
    rule = (f"desiredHealthy = {key_field} {val}" + (" от replicas с округлением вверх" if pct else "")
            + f" → {desired}" if sub == "min_available" else
            f"desiredHealthy = replicas − maxUnavailable {val}" + (" (процент округляется вверх)" if pct else "")
            + f" = {desired}")
    expl = (f"{rule}; готовых подов {healthy} из {rep} — неготовые уже расходуют бюджет, поэтому "
            f"disruptionsAllowed = max(0, {healthy} − {desired}) = {right}. При 0 выселение отклоняется (429), drain "
            "ждёт.")
    prog = program(f"REPLICAS = {rep}\n" + MODEL, PDB=code, PODS=pods)
    checks = [Check(name="pdb_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=str(right))]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="yaml",
                         display_code_note="Исполняется модель контроллера PodDisruptionBudget над показанным "
                                           "манифестом и списком подов",
                         params={"subtype": sub, "value": str(val), "replicas": rep, "unready": unready,
                                 "n_below": n_below})
