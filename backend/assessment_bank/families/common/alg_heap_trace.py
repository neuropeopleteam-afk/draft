"""common.alg.heap_trace — predict_output (канарейка): трассировка очереди с приоритетом."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.alg.heap_trace"

CONTEXTS = [
    ("tasks", "планировщик фоновых задач", ["backup", "deploy", "email", "report", "cleanup",
                                           "index", "billing", "sync", "alerts"], "планировщик"),
    ("tickets", "очередь обращений в поддержку", ["INC-104", "INC-087", "INC-215", "INC-033",
                                                 "INC-150", "INC-009", "INC-342"], "поддержка"),
    ("jobs", "очередь сборок CI", ["lint", "test", "build", "docs", "pack", "e2e", "audit"], "CI"),
    ("orders", "очередь заказов курьерской службы", ["ord-17", "ord-05", "ord-42", "ord-31",
                                                    "ord-08", "ord-26", "ord-13"], "доставка"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    q, desc, names, ctx = rng.choice(CONTEXTS)
    names = rng.sample(names, rng.randint(5, 6))
    max_heap = rng.random() < 0.3
    n_push = len(names)
    n_pop = rng.randint(3, min(4, n_push))
    prios = [rng.randint(1, 4) for _ in names]
    if len(set(prios)) == len(prios):  # гарантируем хотя бы одну ничью по приоритету
        prios[1] = prios[0]
    ops = ["push"] * n_push + ["pop"] * n_pop
    while True:  # pop не раньше, чем в очереди что-то есть
        rng.shuffle(ops)
        depth, ok = 0, True
        for o in ops:
            depth += 1 if o == "push" else -1
            ok &= depth >= 0
        if ok and ops[0] == "push":
            break
    lines = ["import heapq", "", f"{q} = []", "done = []"]
    heap_model: list[tuple[int, str]] = []
    popped: list[str] = []
    it = iter(zip(prios, names))
    for o in ops:
        if o == "push":
            p, n = next(it)
            key = -p if max_heap else p
            lines.append(f'heapq.heappush({q}, ({key}, "{n}"))')
            heap_model.append((key, n))
        else:
            lines.append(f"done.append(heapq.heappop({q})[1])")
            heap_model.sort()
            popped.append(heap_model.pop(0)[1])
    final = rng.choice(["join", "join_len", "last_len"])
    if final == "join":
        lines.append('print(" ".join(done))')
        out = " ".join(popped)
    elif final == "join_len":
        lines.append(f'print(" ".join(done), len({q}))')
        out = " ".join(popped) + f" {len(heap_model)}"
    else:
        heap_model.sort()
        lines.append(f"print(done[-1], {q}[0][1])")
        out = f"{popped[-1]} {heap_model[0][1]}"
    code = "\n".join(lines)
    rule = ("Приоритет хранится со знаком минус, чтобы первым извлекался элемент с наибольшим "
            "исходным приоритетом." if max_heap else
            "Меньшее число — более срочный элемент.")
    stem = (f"Фрагмент моделирует {desc} на модуле heapq. {rule} Что напечатает программа? "
            f"Запишите вывод одной строкой так, как его напечатает print.")
    ak = AnswerKey(kind="output", value=out,
                   explanation="heapq — минимальная куча по кортежу (приоритет, имя): при равном "
                               "приоритете сравниваются строки лексикографически"
                               + ("; отрицательный приоритет превращает её в максимальную." if max_heap else "."))
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"max_heap": max_heap, "final": final})
