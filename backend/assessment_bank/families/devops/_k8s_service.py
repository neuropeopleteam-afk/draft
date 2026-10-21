"""Общий генератор двух find_bug-семейств «Deployment + Service» (по подтипу на семейство).

* ``selector`` — селектор Service не совпадает с метками подов (endpoints пусты);
* ``target_port`` — targetPort Service не ведёт на порт, который слушает приложение (connection refused).

Порт, который слушает приложение, задан аргументом ``--port`` или переменной ``PORT``; containerPort и
readinessProbe с ним согласованы. Поэтому единственная строка, исправление которой чинит манифест, — строка
Service: правка порта приложения ломает readinessProbe, правка меток шаблона — selector Deployment.
Ключ проверяется исполнением модели на Python: разбор показанного YAML (подмножество, _yaml_model) и
проверка правил сопоставления Service → под → порт.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import Flow, emit, program

APPS = [("каталог товаров", "catalog", "shop"), ("платёжный модуль", "payments", "bank"),
        ("уведомления", "notify", "crm"), ("поиск", "search", "shop"), ("личный кабинет", "account", "portal"),
        ("отчёты", "reports", "bi"), ("доставка", "delivery", "logistics"), ("расписание", "schedule", "school")]
PORTS = [8000, 8080, 8081, 3000, 5000, 9000]

MODEL = '''
docs = parse_yaml_docs(MANIFEST)
dep = [d for d in docs if d["kind"] == "Deployment"][0]
svc = [d for d in docs if d["kind"] == "Service"][0]
tpl = dep["spec"]["template"]
labels = tpl["metadata"]["labels"]
ok = all(labels.get(k) == v for k, v in dep["spec"]["selector"]["matchLabels"].items())
# Service выбирает поды, у которых есть ВСЕ пары селектора
ok = ok and all(labels.get(k) == v for k, v in svc["spec"]["selector"].items())
c = tpl["spec"]["containers"][0]
listen = None
args = c.get("args") or []
if "--port" in args:
    listen = int(args[args.index("--port") + 1])
metrics = None
if "--metrics-port" in args:
    metrics = int(args[args.index("--metrics-port") + 1])
for e in c.get("env") or []:
    if e["name"] == "PORT":
        listen = int(e["value"])
    if e["name"] == "METRICS_PORT":
        metrics = int(e["value"])
named = {p.get("name"): p["containerPort"] for p in c.get("ports") or []}


def resolve(p):
    return named.get(p) if isinstance(p, str) else p


ok = ok and resolve(c["readinessProbe"]["httpGet"]["port"]) == listen
# порт http Service — на порт приложения, порт metrics — на порт метрик
for sp in svc["spec"]["ports"]:
    ok = ok and resolve(sp.get("targetPort", sp["port"])) == (metrics if sp["name"] == "metrics" else listen)
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''


def _manifest(p, bug):
    labels = dict(p["labels"])
    tpl_labels = dict(labels, **p["tpl_extra"])
    container = {"name": p["app"], "image": f"registry.local/{p['app']}:{p['ver']}"}
    m = p["metrics"]
    if p["port_via"] == "args":
        container["args"] = Flow(["--port", str(p["listen"])] + (["--metrics-port", str(m)] if m else []))
    env = []
    if p["port_via"] == "env":
        env.append({"name": "PORT", "value": str(p["listen"])})
        if m:
            env.append({"name": "METRICS_PORT", "value": str(m)})
    if p["log"]:
        env.append({"name": "LOG_LEVEL", "value": p["log"]})
    if env:
        container["env"] = env
    container["ports"] = [{"name": p["pname"], "containerPort": p["listen"]}]
    if m:
        container["ports"].append({"name": "metrics", "containerPort": m})
    container["readinessProbe"] = {"httpGet": {"path": "/healthz",
                                               "port": p["pname"] if p["probe_named"] else p["listen"]},
                                   "periodSeconds": p["period"]}
    if p["resources"]:
        container["resources"] = {"requests": {"cpu": p["resources"], "memory": "128Mi"}}
    dep_meta = {"name": p["app"]}
    if p["ns"]:
        dep_meta["namespace"] = p["ns"]
    dep = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": dep_meta,
           "spec": {"replicas": p["replicas"], "selector": {"matchLabels": labels},
                    "template": {"metadata": {"labels": tpl_labels}, "spec": {"containers": [container]}}}}
    sel = dict(labels)
    target = p["pname"] if p["target_named"] else p["listen"]
    if bug == "selector":
        kind = p["sel_bug"]
        if kind == "value":
            sel["app"] = p["app"] + p["suffix"]
        elif kind == "extra":
            sel = dict(sel, version=p["wrong_version"])
        else:  # key: другое имя ключа метки с тем же значением
            sel = {("app.kubernetes.io/name" if k == "app" else k): v for k, v in sel.items()}
    elif p["sel_extra"]:
        sel = dict(sel, version=p["tpl_extra"]["version"])
    if bug == "target_port":
        target = p["wrong_name"] if p["target_named"] else p["wrong_port"]
    svc_meta = {"name": p["svc"]}
    if p["ns"]:
        svc_meta["namespace"] = p["ns"]
    svc = {"apiVersion": "v1", "kind": "Service", "metadata": svc_meta,
           "spec": {"selector": sel, "ports": [{"name": "http", "port": p["svc_port"], "targetPort": target}]}}
    if m:
        mp = {"name": "metrics", "port": m, "targetPort": "metrics" if p["metrics_named"] else m}
        svc["spec"]["ports"].insert(0 if p["metrics_first"] else 1, mp)
    docs = [dep, svc] if p["dep_first"] else [svc, dep]
    return "---\n".join(emit(d) for d in docs)


def generate_variant(family_id: str, seed: int, bug: str):
    rng = make_rng(family_id, seed)
    ctx, app, part = rng.choice(APPS)
    labels = {"app": app}
    if rng.random() < 0.5:
        labels["tier"] = rng.choice(["backend", "api"])
    if rng.random() < 0.4:
        labels["app.kubernetes.io/part-of"] = part
    listen = rng.choice(PORTS)
    p = dict(app=app, labels=labels, ver=f"1.{rng.randint(0, 9)}.{rng.randint(0, 20)}",
             tpl_extra={"version": rng.choice(["v1", "v2", "v3"])}, port_via=rng.choice(["args", "env"]),
             listen=listen, log=rng.choice([None, "info", "debug"]), pname=rng.choice(["http", "web", "api"]),
             probe_named=rng.random() < 0.5, period=rng.choice([5, 10, 15]),
             resources=rng.choice([None, "100m", "250m"]), ns=rng.choice([None, part, "prod"]),
             replicas=rng.randint(2, 4), svc=rng.choice([app, f"{app}-svc"]),
             svc_port=rng.choice([80, 8080, 8000, 9090]), target_named=rng.random() < 0.5,
             dep_first=rng.random() < 0.5, sel_extra=rng.random() < 0.3, sel_bug=rng.choice(["value", "extra", "key"]),
             suffix=rng.choice(["-api", "-svc", "-app", "s"]))
    if p["svc_port"] == listen:
        p["svc_port"] = 80
    p["metrics"] = rng.choice([None, 9100, 9102, 9464, 9090]) if rng.random() < 0.7 else None
    if p["metrics"] in (p["svc_port"], listen):
        p["metrics"] = 9464
    p["metrics_named"] = rng.random() < 0.5
    p["metrics_first"] = rng.random() < 0.5
    others = [x for x in ("http", "web", "api", "main", "metrics") if x != p["pname"]]
    if not p["metrics"]:
        others.remove("metrics")
    p["wrong_name"] = rng.choice(others)
    p["wrong_port"] = rng.choice([p["svc_port"]] + [x for x in PORTS if x != listen][:3] + [p["metrics"] or p["svc_port"]])
    if p["wrong_port"] == listen:
        p["wrong_port"] = p["svc_port"]
    p["wrong_version"] = rng.choice([v for v in ("v1", "v2", "v3") if v != p["tpl_extra"]["version"]])
    if bug == "selector" and p["sel_bug"] == "key" and "app.kubernetes.io/name" in labels:
        p["sel_bug"] = "value"
    if bug == "target_port" and p["target_named"]:
        p["probe_named"] = True  # иначе переименование порта контейнера — второе равноценное исправление
    buggy = _manifest(p, bug)
    fixed = _manifest(p, None)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1, ch
    key = next(iter(ch))
    svc_name = p["svc"]
    if bug == "selector":
        symptom = (f"Поды `{app}` в статусе Running и Ready, но `kubectl get endpoints {svc_name}` показывает "
                   f"`<none>`, и запросы к `http://{svc_name}:{p['svc_port']}` из соседних подов не проходят.")
        why = {"value": "значение метки в селекторе Service не совпадает с меткой подов",
               "extra": "в селекторе есть пара version, которой нет у подов (Service выбирает поды со ВСЕМИ парами)",
               "key": "селектор Service использует другой ключ метки, которого у подов нет"}[p["sel_bug"]]
        expl = (f"Строка {key}: {why}. Service без подходящих подов не получает endpoints. Метки шаблона менять "
                "нельзя — их же выбирает selector Deployment.")
        dtype = "service_selector_mismatch"
    else:
        symptom = (f"Поды `{app}` Ready, у Service `{svc_name}` есть endpoints, но запрос "
                   f"`curl http://{svc_name}:{p['svc_port']}/healthz` из соседнего пода завершается "
                   "`connection refused`" + (f" (метрики на порту {p['metrics']} Service при этом собираются)."
                                             if p["metrics"] else "."))
        expl = (f"Строка {key}: targetPort Service должен вести на порт, который слушает приложение "
                f"({listen}; именованный порт `{p['pname']}`). port Service ({p['svc_port']}) — порт самого "
                "Service, а не контейнера. Порт приложения менять нельзя: на него настроена readinessProbe.")
        dtype = "service_target_port_mismatch"
    stem = (f"Манифест Kubernetes ({ctx}). {symptom} Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    checks = [Check(name="buggy_fails", runner="python", program=program(MODEL, MANIFEST=buggy), expect="fail"),
              Check(name="fixed_passes", runner="python", program=program(MODEL, MANIFEST=fixed), expect="pass",
                    embeds_display_code=False)]
    ak = AnswerKey(kind="line", value=key, explanation=expl)
    return build_variant(family_id, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type=dtype,
                         display_code_note="Исполняется модель сопоставления Service → под → порт над показанным YAML",
                         params={"fixed_code": fixed, "sel_bug": p["sel_bug"] if bug == "selector" else None,
                                 "target_named": p["target_named"]})
