"""devops.k8s.qos_class_mcq — mcq_concept: класс QoS пода по requests/limits контейнеров.

Правила Kubernetes (документация «Pod Quality of Service Classes» и валидация API):
* Guaranteed — у КАЖДОГО контейнера есть limits и requests по cpu и memory и они равны; если задан только
  limit, request по умолчанию равен ему;
* BestEffort — ни у одного контейнера нет ни requests, ни limits по cpu/memory (пустой ``resources: {}`` —
  тоже «нет»);
* Burstable — всё остальное;
* request больше limit — API отклоняет под.
Ловушки варианта: равенство в разных единицах (``500m`` = ``0.5``, ``1Gi`` = ``1024Mi``), десятичные и
двоичные единицы (``512M`` ≠ ``512Mi``), только limits, сайдкар без ресурсов. Варианты ответа — всегда эти
четыре исхода; целевой исход выбирается равномерно. Ключ проверяется исполнением модели: разбор показанного
YAML и количеств в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import emit, program

FAMILY_ID = "devops.k8s.qos_class_mcq"

OUTCOMES = ["Guaranteed", "Burstable", "BestEffort", "Под не будет создан: request больше limit"]
APPS = [("каталог товаров", "catalog"), ("биллинг", "billing"), ("поиск", "search"), ("уведомления", "notify"),
        ("отчёты", "reports"), ("авторизация", "auth"), ("рекомендации", "recs")]
SIDECARS = ["log-agent", "envoy", "metrics-exporter"]
CPU_EQ = [("500m", "0.5"), ("1", "1000m"), ("250m", "0.25"), ("2", "2000m"), ("100m", "0.1")]
MEM_EQ = [("1Gi", "1024Mi"), ("512Mi", "0.5Gi"), ("256Mi", "256Mi"), ("2Gi", "2048Mi"), ("128Mi", "128Mi")]

MODEL = '''
from fractions import Fraction

UNITS = {"m": Fraction(1, 1000), "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "K": 1000, "M": 10 ** 6, "G": 10 ** 9}


def qty(v):
    s = str(v)
    for u in ("Ki", "Mi", "Gi", "m", "K", "M", "G"):
        if s.endswith(u):
            return Fraction(s[:-len(u)]) * UNITS[u]
    return Fraction(s)


pod = parse_yaml(POD)
cs = pod["spec"]["containers"]
rejected, guaranteed, any_res = False, True, False
for c in cs:
    r = c.get("resources") or {}
    lim = r.get("limits") or {}
    req = dict(lim)
    req.update(r.get("requests") or {})  # request по умолчанию = limit
    for res in ("cpu", "memory"):
        if res in req or res in lim:
            any_res = True
        if res in req and res in lim and qty(req[res]) > qty(lim[res]):
            rejected = True
        if not (res in lim and res in req and qty(req[res]) == qty(lim[res])):
            guaranteed = False
if rejected:
    print("Под не будет создан: request больше limit")
elif guaranteed:
    print("Guaranteed")
elif any_res:
    print("Burstable")
else:
    print("BestEffort")
'''


def _guaranteed(rng, tricky):
    cpu = rng.choice(CPU_EQ)
    mem = rng.choice(MEM_EQ)
    form = rng.choice(["limits_only", "units"]) if tricky else rng.choice(["same", "same", "limits_only"])
    if form == "limits_only":
        return {"limits": {"cpu": cpu[0], "memory": mem[0]}}
    if form == "units":
        return {"requests": {"cpu": cpu[1], "memory": mem[1]}, "limits": {"cpu": cpu[0], "memory": mem[0]}}
    return {"requests": {"cpu": cpu[0], "memory": mem[0]}, "limits": {"cpu": cpu[0], "memory": mem[0]}}


def _containers(rng, outcome, app):
    n = rng.randint(1, 3)
    names = [app] + rng.sample(SIDECARS, n - 1)
    res = []
    if outcome == "BestEffort":
        empty = rng.randrange(n) if rng.random() < 0.6 else None
        res = [({} if i == empty else None) for i in range(n)]
        trap = "empty" if empty is not None else "none"
    else:
        res = [_guaranteed(rng, i == 0) for i in range(n)]
        trap = "guaranteed"
        if outcome == "Burstable":
            i = rng.randrange(n)
            trap = rng.choice(["cpu_lower", "no_mem_limit", "sidecar_none", "decimal_mem", "no_cpu"])
            if trap == "sidecar_none" and n == 1:
                trap = "decimal_mem"
            r = res[i]
            if trap == "cpu_lower":
                r["requests"] = {"cpu": "100m", "memory": r["limits"]["memory"]}
                r["limits"]["cpu"] = rng.choice(["500m", "1"])
            elif trap == "no_mem_limit":
                mem = r["limits"]["memory"]
                r["requests"] = {"cpu": r["limits"]["cpu"], "memory": mem}
                del r["limits"]["memory"]
            elif trap == "sidecar_none":
                res[n - 1] = None
            elif trap == "decimal_mem":
                r["requests"] = {"cpu": r["limits"]["cpu"], "memory": "512M"}
                r["limits"]["memory"] = "512Mi"
            else:
                r["requests"] = {"memory": r["limits"]["memory"]}
                r["limits"] = {"memory": r["limits"]["memory"]}
        elif outcome == "Под не будет создан: request больше limit":
            i = rng.randrange(n)
            trap = rng.choice(["mem_over", "cpu_units", "decimal_over"])
            r = res[i]
            if trap == "mem_over":
                r["requests"] = {"cpu": r["limits"]["cpu"], "memory": "1Gi"}
                r["limits"]["memory"] = "768Mi"
            elif trap == "cpu_units":
                r["requests"] = {"cpu": "1", "memory": r["limits"]["memory"]}
                r["limits"]["cpu"] = "800m"
            else:
                r["requests"] = {"cpu": r["limits"]["cpu"], "memory": "600M"}
                r["limits"]["memory"] = "512Mi"
    cs = []
    for name, r in zip(names, res):
        c = {"name": name, "image": f"registry.local/{name}:{rng.randint(1, 4)}.{rng.randint(0, 9)}"}
        if name == app and rng.random() < 0.5:
            c["ports"] = [{"containerPort": rng.choice([8080, 8000, 3000])}]
        if r is not None:
            c["resources"] = r
        cs.append(c)
    return cs, trap


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, app = rng.choice(APPS)
    outcome = rng.choice(OUTCOMES)
    cs, trap = _containers(rng, outcome, app)
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": f"{app}-{rng.randint(100, 999)}",
                                                          "labels": {"app": app}},
           "spec": {"containers": cs}}
    code = emit(pod)
    opts, key = make_options(rng, (outcome, None), [(o, None) for o in OUTCOMES if o != outcome])
    expl = {"guaranteed": "у каждого контейнера requests = limits по cpu и memory (только limits — request "
                          "по умолчанию равен limit; 500m = 0.5, 1Gi = 1024Mi)",
            "empty": "ни у одного контейнера нет requests и limits; пустой resources: {} ничего не задаёт",
            "none": "ни у одного контейнера нет requests и limits",
            "cpu_lower": "у одного контейнера request cpu меньше limit — это Burstable",
            "no_mem_limit": "у одного контейнера нет limit по памяти — Guaranteed невозможен",
            "sidecar_none": "у сайдкара нет ресурсов, а условие Guaranteed — для каждого контейнера",
            "decimal_mem": "512M — десятичные мегабайты (512·10⁶ байт), 512Mi — 512·2²⁰; request меньше limit",
            "no_cpu": "по cpu не заданы ни request, ни limit — Guaranteed требует обоих ресурсов",
            "mem_over": "request памяти 1Gi больше limit 768Mi — валидация API отклонит под",
            "cpu_units": "request cpu 1 (= 1000m) больше limit 800m — валидация API отклонит под",
            "decimal_over": "600M = 600·10⁶ байт больше 512Mi = 536 870 912 байт — под отклонён"}[trap]
    ak = AnswerKey(kind="option", value=key, explanation=f"{outcome}: {expl}.")
    stem = (f"Под сервиса «{ctx}» создаётся из манифеста ниже (других контейнеров и LimitRange в пространстве "
            "имён нет). Какой класс QoS получит под?")
    checks = [Check(name="qos_model", runner="python", program=program(MODEL, POD=code), expect="stdout_equals",
                    expected_stdout=outcome)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Исполняется модель правил QoS Kubernetes над показанным YAML",
                         params={"outcome": outcome, "trap": trap, "n_containers": len(cs)})
