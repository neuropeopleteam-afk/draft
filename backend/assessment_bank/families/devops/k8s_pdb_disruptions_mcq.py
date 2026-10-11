"""devops.k8s.pdb_disruptions_mcq — mcq_concept: допустимые выселения по PodDisruptionBudget.

Семантика (документация Kubernetes «Specifying a Disruption Budget for your Application», контроллер disruption):
expectedPods — число реплик владельца (Deployment); desiredHealthy = minAvailable (процент — от expectedPods с
округлением ВВЕРХ) или expectedPods − maxUnavailable (процент — тоже с округлением вверх); currentHealthy — число
ГОТОВЫХ подов под селектором; disruptionsAllowed = max(0, currentHealthy − desiredHealthy). Выселение (kubectl drain,
Eviction API) при disruptionsAllowed = 0 отклоняется (429). Подтипы: min_available, max_unavailable; значение —
число или процент; в каждом варианте часть подов не готова. Дистракторы — фиксированный состав типовых ошибок:
для процента — считать от replicas, а не от готовых; округлить процент вниз; взять бюджет «как есть»
(maxUnavailable или replicas − minAvailable), не вычитая уже неготовые; для числа (где «от replicas» и «как есть»
совпадают) — от replicas, «0: пока есть неготовые, выселять нельзя», «все готовые поды». Ключ — исполнение модели контроллера над показанным манифестом
и списком подов в песочнице Python.
"""
from __future__ import annotations

import math

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
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
    for _ in range(3000):
        rep = rng.randint(4, 12)
        unready = rng.randint(1, 3)
        healthy = rep - unready
        pct = rng.random() < 0.6
        if sub == "min_available":
            if pct:
                p = rng.choice([25, 30, 40, 50, 60, 70, 75, 80])
                val, desired, desired_floor = f"{p}%", math.ceil(p * rep / 100), math.floor(p * rep / 100)
            else:
                v = rng.randint(1, rep - 1)
                val, desired, desired_floor = v, v, v
            as_is = rep - desired
        else:
            if pct:
                p = rng.choice([10, 20, 25, 30, 40, 50])
                mu, mu_floor = math.ceil(p * rep / 100), math.floor(p * rep / 100)
                val, desired, desired_floor = f"{p}%", rep - mu, rep - mu_floor
            else:
                v = rng.randint(1, max(1, rep // 2))
                val, desired, desired_floor = v, rep - v, rep - v
            as_is = rep - desired
        right = max(0, healthy - desired)
        from_rep = max(0, rep - desired)
        rounded = max(0, healthy - desired_floor)
        if pct:
            wrong = [from_rep, rounded, as_is]
        else:  # для числа «от replicas» и «как есть» совпадают: вместо них — «0» и «все готовые»
            wrong = [from_rep, 0, healthy]
        if len({right, *wrong}) == 4:
            break
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
                         params={"subtype": sub, "value": str(val), "replicas": rep, "unready": unready})
