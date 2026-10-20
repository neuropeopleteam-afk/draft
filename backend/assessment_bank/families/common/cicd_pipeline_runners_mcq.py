"""common.cicd.cicd_pipeline_runners_mcq — mcq_concept (Senior/Lead, CI/CD): длительность конвейера при ограничении раннеров.

Конвейер — граф задач с зависимостями (needs) и длительностями; раннеров k, свободный раннер берёт первую готовую
задачу в порядке списка. Вопрос: через сколько минут завершится конвейер. Ловушки: критический путь без ограничения
раннеров, сумма всех задач, сумма / k, этапы строго по очереди (сумма максимумов по этапам), критический путь + самая
длинная задача. Модель — событийная имитация; ``brute`` — поминутная имитация.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import numeric_variant

FAMILY_ID = "common.cicd.cicd_pipeline_runners_mcq"
CONTEXTS = ["монорепозиторий интернет-магазина", "мобильное приложение", "сервис платежей", "фронтенд личного кабинета",
            "библиотека SDK", "сервис аналитики", "бэкенд CRM", "инфраструктурный репозиторий"]
JOBS = [("lint", 0), ("build", 0), ("unit", 1), ("integration", 1), ("e2e", 1), ("security_scan", 1),
        ("docker_image", 1), ("deploy_staging", 2), ("smoke", 2)]

MODEL = '''
def simulate(P, k):
    jobs = P["jobs"]
    done_at, running, t, started = {}, [], 0, set()
    while len(done_at) < len(jobs):
        for name, dur, deps in jobs:
            if len(running) >= k:
                break
            if name not in started and all(d in done_at and done_at[d] <= t for d in deps):
                running.append((t + dur, name)); started.add(name)
        running.sort()
        t_next, name = running.pop(0)
        t = t_next
        done_at[name] = t
        for end, nm in list(running):
            if end == t:
                running.remove((end, nm)); done_at[nm] = t
    return max(done_at.values())

def answer(P):
    return simulate(P, P["k"])

def brute(P):
    jobs, k = P["jobs"], P["k"]
    left = {n: d for n, d, _ in jobs}
    deps = {n: ds for n, _, ds in jobs}
    done, run, t = set(), [], 0
    while len(done) < len(jobs):
        for n, _d, _ds in jobs:
            if len(run) < k and n not in done and n not in run and all(x in done for x in deps[n]):
                run.append(n)
        t += 1
        for n in list(run):
            left[n] -= 1
            if left[n] == 0:
                run.remove(n); done.add(n)
    return t

def crit(P):
    memo = {}
    def f(n):
        if n not in memo:
            d = [x for x in P["jobs"] if x[0] == n][0]
            memo[n] = d[1] + max([f(x) for x in d[2]] or [0])
        return memo[n]
    return max(f(n) for n, _, _ in P["jobs"])

def traps(P):
    total = sum(d for _, d, _ in P["jobs"])
    stages = {}
    for n, d, _ in P["jobs"]:
        st = P["stage"][n]
        stages[st] = max(stages.get(st, 0), d)
    return {"critical_path": crit(P), "sum_all": total, "sum_div_k": -(-total // P["k"]),
            "stages_serial": sum(stages.values()), "one_more_runner": simulate(P, P["k"] + 1),
            "one_runner_less": simulate(P, max(1, P["k"] - 1)) if P["k"] > 1 else None}

def fmt(x):
    return f"{x} мин"
'''


def _sample(rng):
    names = ["lint", "build"] + rng.sample(["unit", "integration", "e2e", "security_scan", "docker_image"], rng.randint(3, 5)) \
        + rng.sample(["deploy_staging", "smoke"], rng.randint(1, 2))
    stage = {n: s for n, s in JOBS}
    jobs = []
    for n in names:
        dur = rng.randint(2, 6) if stage[n] == 0 else rng.randint(4, 18)
        if n == "lint":
            deps = []
        elif n == "build":
            deps = []
        elif stage[n] == 1:
            deps = ["build"] if n != "security_scan" else rng.choice([[], ["build"]])
        else:
            pool = [x for x in names if stage[x] == 1]
            deps = sorted(rng.sample(pool, min(len(pool), rng.randint(1, 2)))) + (["lint"] if rng.random() < 0.5 else [])
        jobs.append((n, dur, deps))
    return {"jobs": jobs, "k": rng.choice([2, 3]), "stage": stage}


def _accept(P, ns):
    return ns["answer"](P) > ns["crit"](P)


def _stem(P, ctx):
    rows = "\n".join(f"• {n} — {d} мин" + (f", needs: {', '.join(ds)}" if ds else "") for n, d, ds in P["jobs"])
    return (f"Конвейер CI ({ctx}) — задачи с зависимостями needs (задача стартует, когда завершены все её needs):\n"
            f"{rows}\n\nВ группе {P['k']} раннера, каждый выполняет одну задачу за раз; освободившийся раннер берёт "
            "первую по списку задачу, у которой выполнены needs. Задачи не падают, очередь к раннерам пустая.\n\n"
            "Через сколько минут после старта завершится весь конвейер?")


def _explain(P, a, traps):
    from assessment_bank.families._w2010_kit import load_model
    cp = load_model(MODEL)["crit"](P)
    return (f"Без ограничения раннеров конвейер шёл бы по критическому пути ({cp} мин), "
            f"но раннеров {P['k']}: готовые задачи ждут освобождения раннера. Имитация по правилу «первая готовая по "
            f"списку» даёт {a} мин.")


TRAP_DESC = {"critical_path": "критический путь без ограничения раннеров", "sum_all": "сумма всех задач",
             "sum_div_k": "сумма задач, делённая на число раннеров", "stages_serial": "этапы строго по очереди",
             "one_more_runner": "на один раннер больше", "one_runner_less": "на один раннер меньше"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.0, abs_min=2, trap_first="critical_path",
                           trap_desc=TRAP_DESC)
