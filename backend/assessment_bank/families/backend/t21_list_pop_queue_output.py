"""backend.queue.t21_list_pop_queue_output — predict_output (набор t21, порог Стажёра): список как очередь задач —
append, pop(0) и pop().

Планировщик держит задачи в списке: новые дописываются в конец (append), воркер берёт первую (pop(0)),
а «срочный» обработчик — последнюю (pop() без аргумента). Ловушки: pop() без аргумента снимает элемент с конца —
только что добавленный; после двух pop длина уменьшается на два, а индексы сдвигаются. Ключ — независимая модель
по индексам исходного списка в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.queue.t21_list_pop_queue_output"

CTX = [("фоновые задачи магазина", ["resize", "email", "report", "invoice", "backup", "sync", "reindex", "export"]),
       ("очередь интеграций", ["crm", "erp", "billing", "sms", "webhook", "ledger", "audit", "geo"]),
       ("задачи биллинга", ["charge", "refund", "notify", "close", "remind", "recount", "archive", "payout"]),
       ("задачи медиасервиса", ["thumb", "transcode", "upload", "scan", "tag", "preview", "purge", "watermark"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    names = rng.sample(pool, rng.randint(3, 4) + 2)
    n_init = len(names) - rng.randint(1, 2)
    init, added = names[:n_init], names[n_init:]
    var = rng.choice(["jobs", "tasks", "queue"])
    lit = "[" + ", ".join(f'"{x}"' for x in init) + "]"
    lines = [f"{var} = {lit}"] + [f'{var}.append("{a}")' for a in added]
    order = rng.choice(["front_first", "back_first"])
    if order == "front_first":
        lines += [f"first = {var}.pop(0)", f"last = {var}.pop()"]
    else:
        lines += [f"last = {var}.pop()", f"first = {var}.pop(0)"]
    tail_idx = rng.choice(["0", "-1"])
    lines += ["print(first, last)", f"print(len({var}), {var}[{tail_idx}])"]
    code = "\n".join(lines)
    full = init + added
    first, last = full[0], full[-1]
    rest = full[1:-1]
    shown = rest[0] if tail_idx == "0" else rest[-1]
    out = f"{first} {last}\n{len(rest)} {shown}"
    expl = (f"После append список: [{', '.join(full)}]. pop(0) снимает первый элемент — «{first}», pop() без аргумента — "
            f"последний, то есть только что добавленный «{last}» (порядок двух pop здесь не важен). Осталось "
            f"{len(rest)}: [{', '.join(rest)}]; [{tail_idx}] — «{shown}».")
    stem = (f"Планировщик («{ctx}») держит задачи в списке: новые дописывает в конец, а воркеры забирают задачи "
            "с разных концов списка.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"init": init, "added": added, "order": order}, language="python")
