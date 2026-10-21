"""backend.queue.t21_priority_sort_key_output — predict_output (набор t21, порог Junior): sorted с key-кортежем
и генератор списка.

Планировщик упорядочивает задачи: сначала по приоритету по убыванию (минус в ключе), при равном приоритете —
по оценке длительности по возрастанию; затем печатает имена (генератор списка) и суммарную длительность первых k.
Ловушки: знак минус обращает только первый компонент ключа, второй остаётся по возрастанию; срез [:k] берётся
уже из отсортированного списка. Ключ — независимая модель (сортировка вставками по сравнению пар) в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.queue.t21_priority_sort_key_output"

CTX = [("фоновые задачи магазина", ["report", "email", "resize", "backup", "sync", "reindex", "export"]),
       ("задачи биллинга", ["charge", "refund", "invoice", "remind", "payout", "close", "audit"]),
       ("очередь интеграций", ["crm", "erp", "sms", "ledger", "geo", "webhook", "catalog"]),
       ("задачи медиасервиса", ["thumb", "transcode", "scan", "tag", "preview", "purge", "upload"])]


def _before(a, b, desc_first: bool) -> bool:
    """a идёт раньше b? Приоритет (индекс 1) по убыванию/возрастанию, затем длительность (индекс 2) по возрастанию."""
    if a[1] != b[1]:
        return a[1] > b[1] if desc_first else a[1] < b[1]
    return a[2] < b[2]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    for _ in range(200):
        n = rng.randint(5, 6)
        names = rng.sample(pool, n)
        prios = [rng.randint(1, 3) for _ in range(n)]
        durs = rng.sample(range(2, 60), n)
        jobs = [(names[i], prios[i], durs[i]) for i in range(n)]
        # есть хотя бы одна пара с равным приоритетом, где более длинная задача стоит раньше в исходном списке
        tie = any(jobs[i][1] == jobs[j][1] and jobs[i][2] > jobs[j][2] for i in range(n) for j in range(i + 1, n))
        if tie and len(set(prios)) >= 2:
            break
    else:
        raise RuntimeError("t21_priority_sort: не собраны задачи")
    desc_first = rng.random() < 0.75
    k = rng.randint(2, 3)
    key = "(-j[1], j[2])" if desc_first else "(j[1], j[2])"
    var = rng.choice(["jobs", "tasks", "backlog"])
    lit = "[" + ", ".join(f'("{a}", {b}, {c})' for a, b, c in jobs) + "]"
    code = (f"{var} = {lit}\n"
            f"order = sorted({var}, key=lambda j: {key})\n"
            "names = [j[0] for j in order]\n"
            f"first = order[:{k}]\n"
            'print(" ".join(names))\n'
            "print(sum(j[2] for j in first))")
    # сортировка вставками по явному правилу сравнения
    srt: list = []
    for job in jobs:
        pos = len(srt)
        for i, other in enumerate(srt):
            if _before(job, other, desc_first):
                pos = i
                break
        srt.insert(pos, job)
    names_out = " ".join(j[0] for j in srt)
    total = sum(j[2] for j in srt[:k])
    out = f"{names_out}\n{total}"
    expl = ("Ключ " + key + ": сначала приоритет " + ("по убыванию (минус)" if desc_first else "по возрастанию")
            + ", при равном приоритете — длительность по возрастанию"
            + (" (минус стоит только у первого компонента)" if desc_first else "") + ". Порядок: "
            + ", ".join(f"{j[0]} ({j[1]}, {j[2]})" for j in srt)
            + f". Сумма длительностей первых {k}: " + " + ".join(str(j[2]) for j in srt[:k]) + f" = {total}.")
    stem = (f"Планировщик («{ctx}») хранит задачи как кортежи (имя, приоритет, оценка длительности в минутах) и "
            "упорядочивает их перед запуском.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"jobs": jobs, "desc": desc_first, "k": k}, language="python")
