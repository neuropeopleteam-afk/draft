"""devops.ci.job_needs_output — predict_output: какие job конвейера GitHub Actions выполнятся после падения одной.

Семантика (документация GitHub Actions, «Using jobs» и «Expressions → Status check functions»):
* job без ``if`` (неявно ``success()``) выполняется, только если ВСЕ job из ``needs`` завершились успешно;
  если какая-то из них упала или пропущена — job пропускается (skipped);
* ``if: always()`` — выполняется всегда, когда завершились job из ``needs``;
* ``if: failure()`` — выполняется, если упала любая job-предок (по цепочке needs, не только прямая).
Одна job падает на своём шаге (сказано в условии); остальные шаги успешны. Ответ — статус каждой job в порядке
файла: success / failure / skipped. Ключ считает генератор; проверка — исполнение модели в песочнице Python над
показанным YAML (подмножество YAML, _yaml_model).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import Flow, emit, program

FAMILY_ID = "devops.ci.job_needs_output"

CTX = ["монорепозиторий магазина", "сервис платежей", "мобильный бэкенд", "библиотека клиентов API",
       "сайт документации", "сервис отчётов"]
POOL = [("lint", "make lint"), ("build", "make build"), ("unit", "make test"), ("e2e", "make e2e"),
        ("scan", "make audit"), ("package", "make image"), ("deploy", "make deploy"), ("smoke", "make smoke"),
        ("notify", "./ci/notify.sh"), ("report", "./ci/report.sh"), ("cleanup", "./ci/cleanup.sh")]

MODEL = '''
wf = parse_yaml(WORKFLOW)
jobs = wf["jobs"]


def needs(j):
    n = jobs[j].get("needs") or []
    return [n] if isinstance(n, str) else list(n)


def ancestors(j):
    out, todo = set(), needs(j)
    while todo:
        a = todo.pop()
        if a not in out:
            out.add(a)
            todo += needs(a)
    return out


res = {}
while len(res) < len(jobs):
    for j in jobs:
        if j in res or any(n not in res for n in needs(j)):
            continue
        cond = jobs[j].get("if", "success()")
        if cond == "always()":
            run = True
        elif cond == "failure()":
            run = any(res[a] == "failure" for a in ancestors(j))
        else:
            run = all(res[n] == "success" for n in needs(j))
        res[j] = ("failure" if j == FAILING else "success") if run else "skipped"
for j in jobs:
    print(j + ": " + res[j])
'''


def _statuses(order, needs, cond, failing):
    """Независимый расчёт статусов (по топологическому порядку генерации)."""
    res = {}
    for j in order:
        anc, todo = set(), list(needs[j])
        while todo:
            a = todo.pop()
            if a not in anc:
                anc.add(a)
                todo.extend(needs[a])
        c = cond.get(j)
        if c == "always()":
            run = True
        elif c == "failure()":
            run = any(res[a] == "failure" for a in anc)
        else:
            run = all(res[n] == "success" for n in needs[j])
        res[j] = ("failure" if j == failing else "success") if run else "skipped"
    return res


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    for _ in range(1000):
        k = rng.randint(5, 6)
        n_tail = rng.randint(1, 2)  # служебные job (notify/report/cleanup) — только они получают always()/failure()
        idx = sorted(rng.sample(range(len(POOL) - 3), k - n_tail)) + sorted(
            rng.sample(range(len(POOL) - 3, len(POOL)), n_tail))
        order = [POOL[i][0] for i in idx]
        cmds = dict(POOL[i] for i in idx)
        needs = {order[0]: []}
        for i, j in enumerate(order[1:], 1):
            m = rng.choice([1, 1, 2]) if i >= 2 else 1
            needs[j] = sorted(rng.sample(order[:i], min(m, i)), key=order.index)
        cond = {}
        for j in order[-n_tail:]:
            cond[j] = rng.choice(["always()", "failure()", "always()", "failure()", None])
        cond = {j: c for j, c in cond.items() if c}
        cands = [j for j in order[:-1] if j not in cond]
        failing = rng.choice(cands)
        res = _statuses(order, needs, cond, failing)
        vals = list(res.values())
        cond_ran = [j for j in cond if res[j] != "skipped"]
        # нужны и пропуск, и сработавшее условие, и хотя бы одна ловушка: failure() у не прямого потомка или
        # job без if после пропущенной
        indirect = any(cond.get(j) == "failure()" and failing not in needs[j] and res[j] == "success" for j in order)
        after_skip = any(j not in cond and any(res[n] == "skipped" for n in needs[j]) for j in order)
        if vals.count("skipped") >= 1 and cond_ran and (indirect or after_skip):
            break
    jobs = {}
    for j in order:
        body = {"runs-on": "ubuntu-latest"}
        if needs[j]:
            body["needs"] = needs[j][0] if len(needs[j]) == 1 else Flow(needs[j])
        if j in cond:
            body["if"] = cond[j]
        body["steps"] = [{"uses": "actions/checkout@v4"}, {"run": cmds[j]}]
        jobs[j] = body
    wf = {"name": "ci", "on": {"push": {"branches": Flow(["main"])}}, "jobs": jobs}
    code = emit(wf)
    expected = "\n".join(f"{j}: {res[j]}" for j in order)
    stem = (f"Конвейер GitHub Actions ({ctx}). При очередном пуше в main команда `{cmds[failing]}` в job "
            f"`{failing}` завершилась с ошибкой; все остальные шаги, если выполняются, проходят успешно. "
            "Какой итоговый статус будет у каждой job? Ответ — строки `имя: статус` в порядке job в файле, статус — "
            "`success`, `failure` или `skipped`.")
    expl = ("Job без if выполняется, только если все job из needs успешны; упавшая или пропущенная зависимость "
            "даёт skipped. always() выполняется всегда, failure() — если упала любая job-предок по цепочке needs.")
    checks = [Check(name="stdout", runner="python", program=program(MODEL, WORKFLOW=code) .replace(
        "\n\nwf = parse_yaml", f"\n\nFAILING = {failing!r}\nwf = parse_yaml", 1),
        expect="stdout_equals", expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Исполняется модель статусов job (needs, if) над показанным YAML",
                         params={"failing": failing, "conditions": cond})
