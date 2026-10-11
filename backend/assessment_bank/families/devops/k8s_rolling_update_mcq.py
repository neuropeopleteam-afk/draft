"""devops.k8s.rolling_update_mcq — mcq_concept: границы RollingUpdate по maxSurge и maxUnavailable в процентах.

Правило Kubernetes (Deployment, стратегия RollingUpdate): процент maxSurge округляется ВВЕРХ, процент
maxUnavailable — ВНИЗ (от spec.replicas). Отсюда максимум подов во время обновления = replicas + surge,
минимум доступных = replicas − unavailable. Один подтип — оба параметра в процентах, произведения нецелые.
Дистракторы — фиксированный состав: остальные три сочетания направлений округления. Ключ проверяется
исполнением модели (разбор показанного YAML, округление в песочнице Python).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import emit, program

FAMILY_ID = "devops.k8s.rolling_update_mcq"

APPS = [("API заказов", "orders-api"), ("фронтенд витрины", "storefront"), ("сервис поиска", "search"),
        ("воркер очереди писем", "mailer"), ("шлюз платежей", "pay-gw"), ("сервис профилей", "profiles"),
        ("сервис тарифов", "tariffs")]
PCTS = [10, 15, 20, 25, 30, 35, 40, 50]

MODEL = '''
import math
d = parse_yaml(DEPLOY)
n = d["spec"]["replicas"]
ru = d["spec"]["strategy"]["rollingUpdate"]


def pct(v):
    return int(str(v).rstrip("%"))


surge = math.ceil(n * pct(ru["maxSurge"]) / 100)          # maxSurge — вверх
unavail = math.floor(n * pct(ru["maxUnavailable"]) / 100)  # maxUnavailable — вниз
print(f"не больше {n + surge} подов, доступно не меньше {n - unavail}")
'''


def _text(total, avail):
    return f"не больше {total} подов, доступно не меньше {avail}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, app = rng.choice(APPS)
    for _ in range(500):
        n = rng.randint(3, 17)
        s, u = rng.choice(PCTS), rng.choice(PCTS)
        if (n * s) % 100 and (n * u) % 100:
            break
    sc, sf = -(-n * s // 100), n * s // 100
    uc, uf = -(-n * u // 100), n * u // 100
    correct = _text(n + sc, n - uf)
    wrong = [_text(n + sf, n - uc), _text(n + sc, n - uc), _text(n + sf, n - uf)]
    dep = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": app},
           "spec": {"replicas": n, "strategy": {"type": "RollingUpdate",
                                                "rollingUpdate": {"maxSurge": f"{s}%", "maxUnavailable": f"{u}%"}},
                    "selector": {"matchLabels": {"app": app}},
                    "template": {"metadata": {"labels": {"app": app}},
                                 "spec": {"containers": [{"name": app,
                                                          "image": f"registry.local/{app}:{rng.randint(2, 9)}.0"}]}}}}
    if rng.random() < 0.5:
        dep["spec"]["minReadySeconds"] = rng.choice([5, 10, 30])
    code = emit(dep)
    opts, key = make_options(rng, (correct, None), [(w, None) for w in wrong])
    dec = lambda x: f"{x:g}".replace(".", ",")  # noqa: E731
    expl = (f"maxSurge {s}% от {n} = {dec(n * s / 100)} → вверх {sc}; maxUnavailable {u}% от {n} = {dec(n * u / 100)} → "
            f"вниз {uf}. Во время обновления не больше {n} + {sc} = {n + sc} "
            f"{plural(n + sc, 'пода', 'подов', 'подов')}, доступно не меньше {n} − {uf} = {n - uf}.")
    stem = (f"Deployment «{ctx}» обновляется на новую версию образа. Какие границы соблюдает контроллер во время "
            "обновления (все поды проходят готовность)?")
    checks = [Check(name="rollout_model", runner="python", program=program(MODEL, DEPLOY=code),
                    expect="stdout_equals", expected_stdout=correct)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Исполняется модель округления RollingUpdate над показанным YAML",
                         params={"replicas": n, "surge_pct": s, "unavail_pct": u})
