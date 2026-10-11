"""data_eng.orch.trigger_rule_output — predict_output: состояния задач DAG Airflow после падения одной задачи.

Семантика правил запуска (документация Apache Airflow 2, «DAGs → Trigger Rules»; планировщик, trigger_rule_dep):
* all_success (по умолчанию) — задача запускается, если все вышестоящие успешны; если среди вышестоящих есть failed
  или upstream_failed — состояние upstream_failed; иначе, если есть skipped, — skipped;
* all_done — запускается, когда все вышестоящие завершились в любом состоянии;
* one_failed — запускается, если хотя бы одна вышестоящая failed или upstream_failed; иначе (все завершились без
  падений) — skipped;
* none_failed — запускается, если среди вышестоящих нет failed и upstream_failed (skipped допускается); иначе —
  upstream_failed.
Одна задача падает на своей команде, ещё одна (в части вариантов) пропускает себя сама, если её запустят (AirflowSkipException —
сказано в условии); остальные команды, если запускаются, успешны. Ответ — состояние каждой задачи в порядке
объявления: success / failed / skipped / upstream_failed. Проверка — исполнение показанного кода DAG дословно
в песочнице Python с заглушками модулей airflow (собирают граф и правила) и моделью планировщика.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.orch.trigger_rule_output"

CTX = [("ежедневная витрина продаж", "sales_daily"), ("загрузка логов приложения", "app_logs"),
       ("сверка платежей", "payments_recon"), ("выгрузка в CRM", "crm_export"),
       ("обновление признаков для моделей", "features_refresh"), ("отчёт по складу", "stock_report")]
POOL = [("extract_orders", "python extract.py orders"), ("extract_users", "python extract.py users"),
        ("check_source", "python checks/source.py"), ("clean", "python clean.py"),
        ("dedup", "python dedup.py"), ("validate", "python validate.py"), ("load_dwh", "python load.py"),
        ("build_mart", "dbt run -s mart"), ("refresh_cache", "python cache.py")]
TAIL = [("notify_fail", "./notify.sh fail"), ("cleanup_tmp", "./cleanup.sh"), ("report", "./report.sh"),
        ("alert_oncall", "./alert.sh")]
RULES = ["all_done", "one_failed", "none_failed"]

STUBS = '''import sys
import types

GRAPH = {"tasks": [], "up": {}, "rule": {}}


class DAG:
    def __init__(self, dag_id, **kw):
        self.dag_id = dag_id

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BashOperator:
    def __init__(self, task_id, bash_command, trigger_rule="all_success", **kw):
        self.task_id = task_id
        GRAPH["tasks"].append(task_id)
        GRAPH["up"][task_id] = []
        GRAPH["rule"][task_id] = trigger_rule

    def _link(self, other):
        for o in other if isinstance(other, list) else [other]:
            GRAPH["up"][o.task_id].append(self.task_id)
        return other

    def __rshift__(self, other):
        return self._link(other)

    def __rrshift__(self, other):
        for s in other:
            s._link(self)
        return self


m_air = types.ModuleType("airflow")
m_air.DAG = DAG
m_ops = types.ModuleType("airflow.operators")
m_bash = types.ModuleType("airflow.operators.bash")
m_bash.BashOperator = BashOperator
sys.modules.update({"airflow": m_air, "airflow.operators": m_ops, "airflow.operators.bash": m_bash})
'''

MODEL = '''

state = {}
while len(state) < len(GRAPH["tasks"]):
    for t in GRAPH["tasks"]:
        ups = GRAPH["up"][t]
        if t in state or any(u not in state for u in ups):
            continue
        st = [state[u] for u in ups]
        bad = any(s in ("failed", "upstream_failed") for s in st)
        rule = GRAPH["rule"][t]
        if rule == "all_done":
            run, other = True, None
        elif rule == "one_failed":
            run, other = bad, "skipped"
        elif rule == "none_failed":
            run, other = not bad, "upstream_failed"
        else:
            run = all(s == "success" for s in st)
            other = "upstream_failed" if bad else "skipped"
        if run:
            state[t] = "failed" if t == FAILING else ("skipped" if t == SKIPPING else "success")
        else:
            state[t] = other
for t in GRAPH["tasks"]:
    print(t + ": " + state[t])
'''


def _states(order, ups, rule, failing, skipping):
    """Независимый расчёт состояний (в порядке генерации — он топологический)."""
    res = {}
    for t in order:
        st = [res[u] for u in ups[t]]
        bad = "failed" in st or "upstream_failed" in st
        r = rule.get(t, "all_success")
        if r == "all_done":
            run = True
        elif r == "one_failed":
            run = bad
        elif r == "none_failed":
            run = not bad
        else:
            run = all(s == "success" for s in st)
        if run:
            res[t] = "failed" if t == failing else ("skipped" if t == skipping else "success")
        elif r == "one_failed":
            res[t] = "skipped"
        elif r == "none_failed" or bad:
            res[t] = "upstream_failed"
        else:
            res[t] = "skipped"
    return res


def _code(dag_id, order, cmds, ups, rule, sched):
    lines = ["from datetime import datetime", "", "from airflow import DAG", "from airflow.operators.bash import BashOperator",
             "", f'with DAG("{dag_id}", start_date=datetime(2026, 10, 1), schedule="{sched}", catchup=False):']
    for t in order:
        tr = f', trigger_rule="{rule[t]}"' if t in rule else ""
        lines.append(f'    {t} = BashOperator(task_id="{t}", bash_command="{cmds[t]}"{tr})')
    lines.append("")
    # рёбра: группируем по нижестоящей задаче
    for t in order:
        if not ups[t]:
            continue
        if len(ups[t]) == 1:
            lines.append(f"    {ups[t][0]} >> {t}")
        else:
            lines.append(f"    [{', '.join(ups[t])}] >> {t}")
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, dag_id = rng.choice(CTX)
    sched = rng.choice(["@daily", "@hourly", "0 3 * * *", "30 6 * * *"])
    for _ in range(3000):
        k = rng.randint(4, 5)
        n_tail = rng.randint(1, 2)
        main = [POOL[i] for i in sorted(rng.sample(range(len(POOL)), k))]
        tail = [TAIL[i] for i in sorted(rng.sample(range(len(TAIL)), n_tail))]
        order = [t for t, _ in main + tail]
        cmds = dict(main + tail)
        ups = {order[0]: []}
        for i, t in enumerate(order[1:], 1):
            m = rng.choice([1, 1, 2]) if i >= 2 else 1
            ups[t] = sorted(rng.sample(order[:i], min(m, i)), key=order.index)
        rule = {}
        for t in order[k:]:
            rule[t] = rng.choice(RULES)
        if rng.random() < 0.4:
            mid = rng.choice(order[2:k])
            rule[mid] = rng.choice(["none_failed", "all_done"])
        failing = rng.choice([t for t in order[:k - 1]])
        skipping = rng.choice([None, None] + [t for t in order[:k] if t != failing])
        res = _states(order, ups, rule, failing, skipping)
        vals = list(res.values())
        # в каждом варианте: upstream_failed, сработавшее особое правило, и ловушка — skipped по правилу или
        # запуск после упавшей ветки
        fired = [t for t in rule if res[t] in ("success",)]
        trap = any(rule.get(t) == "one_failed" and res[t] == "skipped" for t in order) or \
            any(rule.get(t) == "none_failed" and res[t] == "success" and any(res[u] == "skipped" for u in ups[t])
                for t in order) or "skipped" in vals
        if "upstream_failed" in vals and fired and trap and len(set(vals)) >= 3:
            break
    code = _code(dag_id, order, cmds, ups, rule, sched)
    expected = "\n".join(f"{t}: {res[t]}" for t in order)
    skip_txt = (f" Задача `{skipping}`, если её запустят, пропускает себя сама (данных за период нет, вызывает "
                "AirflowSkipException) — тогда её состояние skipped." if skipping else "")
    stem = (f"DAG Airflow 2 «{ctx}». В очередном запуске команда задачи `{failing}` завершилась с ошибкой "
            f"(повторов нет).{skip_txt} Остальные команды, если запускаются, проходят успешно. Какое итоговое "
            "состояние будет у каждой задачи? Ответ — строки `task_id: состояние` в порядке объявления задач, "
            "состояние — `success`, `failed`, `skipped` или `upstream_failed`.")
    expl = ("all_success (по умолчанию): упавшая или upstream_failed вышестоящая даёт upstream_failed, пропущенная — "
            "skipped. all_done запускается всегда; one_failed — только если выше есть failed/upstream_failed, иначе "
            "skipped; none_failed допускает skipped выше, но не падения.")
    prog = STUBS + "\n" + code + "\n\nFAILING = " + repr(failing) + "\nSKIPPING = " + repr(skipping) + MODEL
    checks = [Check(name="stdout", runner="python", program=prog, expect="stdout_equals", expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="python",
                         display_code_note="Показанный код DAG исполняется дословно с заглушками airflow; состояния "
                                           "считает модель планировщика (правила запуска)",
                         params={"failing": failing, "skipping": skipping, "rules": rule})
