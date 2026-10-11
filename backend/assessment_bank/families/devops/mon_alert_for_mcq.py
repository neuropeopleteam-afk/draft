"""devops.mon.alert_for_mcq — mcq_concept: когда правило алерта Prometheus с `for` перейдёт в firing.

Семантика правил алертов Prometheus (документация «Alerting rules»): на каждой оценке (здесь раз в минуту),
если выражение истинно, неактивный алерт становится pending с моментом активации ActiveAt; pending переходит в
firing на первой оценке, где now − ActiveAt ≥ for; если выражение ложно — алерт сбрасывается (inactive), и
отсчёт начинается заново. Подтип один: ряд значений с провалом ниже порога внутри первого «окна». Варианты
ответа — фиксированный состав: верная минута, на минуту раньше (отсчёт с первой оценки как с первой минуты),
ответ без учёта сброса и «не перейдёт за показанные минуты» (иногда это и есть верный ответ — тогда на его
месте минута без учёта сброса и минута по ошибке «на одну раньше»). Ключ — исполнение модели правила в песочнице
Python над показанным YAML и рядом значений.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import emit, program

FAMILY_ID = "devops.mon.alert_for_mcq"

# (алерт, что измеряет, метрика, пороги, превышения, недоборы)
ALERTS = [("HighErrorRatio", "доля ответов 5xx", "job:http_5xx:ratio5m", [0.02, 0.05], [0.01, 0.02, 0.04],
           [0.01, 0.015]),
          ("HighLatencyP99", "p99 задержки, с", "job:latency_p99:5m", [0.8, 1.2], [0.1, 0.3, 0.5], [0.1, 0.2]),
          ("QueueBacklog", "длина очереди", "queue:depth:max", [500, 1000], [10, 50, 120, 300], [20, 80, 150]),
          ("DiskAlmostFull", "доля занятого места", "node:fs_used:ratio", [0.85, 0.9], [0.01, 0.02, 0.04],
           [0.01, 0.03]),
          ("ReplicationLag", "отставание реплики, с", "pg:replication_lag:max", [30, 60], [5, 15, 40], [5, 10, 20])]
CTX = [("сервис платежей", "payments"), ("API каталога", "catalog"), ("кластер очередей", "queues"),
       ("база заказов", "orders-db"), ("шлюз авторизации", "auth-gw")]
NEVER = "Не перейдёт в firing за показанные минуты"

MODEL = '''
rule = parse_yaml(RULES)["groups"][0]["rules"][0]
op_threshold = rule["expr"].split(" > ")
thr = float(op_threshold[1])
for_min = int(str(rule["for"]).rstrip("m"))
active_at, firing = None, None
for minute, value in enumerate(VALUES):
    if value > thr:
        if active_at is None:
            active_at = minute          # pending
        if minute - active_at >= for_min:
            firing = minute
            break
    else:
        active_at = None                # выражение ложно — сброс
print(NEVER if firing is None else f"На {firing}-й минуте")
'''


def _first_firing(values, thr, for_min, reset=True):
    active = None
    for m, v in enumerate(values):
        if v > thr:
            if active is None:
                active = m
            if m - active >= for_min:
                return m
        elif reset:
            active = None
    return None


def _fmt(v, thr):
    return f"{v:g}".replace(".", ",") if isinstance(thr, float) else str(v)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, what, metric, thrs, ups, downs = rng.choice(ALERTS)
    ctx, group = rng.choice(CTX)
    thr = rng.choice(thrs)
    for _ in range(2000):
        for_min = rng.choice([2, 3, 4, 5])
        n = rng.randint(9, 12)
        pat = [rng.random() < 0.65 for _ in range(n)]
        pat[0] = False
        vals = []
        for hi in pat:
            v = thr + rng.choice(ups) if hi else thr - rng.choice(downs)
            if not hi and rng.random() < 0.2:
                v = thr  # равно порогу — выражение `>` ложно
            v = round(v, 3) if isinstance(thr, float) else v
            vals.append(v)
        right = _first_firing(vals, thr, for_min)
        noreset = _first_firing(vals, thr, for_min, reset=False)
        early = _first_firing(vals, thr, for_min - 1)
        if noreset is None or noreset == right or early is None or early == right:
            continue
        if right is not None and early >= right:
            continue
        break
    rule = {"groups": [{"name": group, "interval": "1m", "rules": [
        {"alert": name, "expr": f"{metric} > {_fmt(thr, thr).replace(',', '.')}", "for": f"{for_min}m",
         "labels": {"severity": "page"}}]}]}
    code = emit(rule)
    lab = lambda m: NEVER if m is None else f"На {m}-й минуте"  # noqa: E731
    correct = lab(right)
    base = right if right is not None else noreset
    pool = [lab(early), lab(noreset), NEVER] + [lab(base + d) for d in (1, -1, 2, -2, 3) if base + d > 0]
    wrong = []
    for w in pool:
        if w != correct and w not in wrong:
            wrong.append(w)
    wrong = wrong[:3]
    opts, key = make_options(rng, (correct, None), [(w, None) for w in wrong])
    series = ", ".join(f"{m}: {_fmt(v, thr)}" for m, v in enumerate(vals))
    stem = (f"Правило алерта ({ctx}) оценивается раз в минуту, начиная с минуты 0. Значения выражения `{metric}` "
            f"({what}) на оценках — минута: значение — {series}. На какой минуте алерт `{name}` впервые перейдёт "
            "в состояние firing?")
    expl = (f"Алерт становится pending на первой оценке, где значение строго больше порога, и переходит в firing, "
            f"когда с момента активации прошло не меньше {for_min} мин; оценка с ложным выражением (в том числе "
            "значение, равное порогу) сбрасывает отсчёт. Ответ: " + correct.lower() + ".")
    prog = program(f"NEVER = {NEVER!r}\nVALUES = {vals!r}\n" + MODEL, RULES=code)
    checks = [Check(name="alert_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=correct)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Исполняется модель состояний pending/firing над показанным правилом",
                         params={"for": for_min, "values": vals, "answer": right})
