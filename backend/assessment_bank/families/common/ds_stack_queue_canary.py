"""common.ds.stack_queue_canary — predict_output (канарейка): стек на list и очередь на deque."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.ds.stack_queue_canary"

CONTEXTS = [("undo", "history", "pending", ["вставка", "удаление", "жирный", "курсив", "отступ", "цвет"],
             "редактор: стек отмены и очередь автосохранения"),
            ("jobs", "calls", "inbox", ["отчёт", "письмо", "выгрузка", "бэкап", "счёт", "аудит"],
             "планировщик: стек вызовов и очередь задач"),
            ("pages", "back", "prefetch", ["главная", "каталог", "товар", "корзина", "оплата", "профиль"],
             "браузер: история «назад» и очередь предзагрузки")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    _, st, qu, words, ctx = rng.choice(CONTEXTS)
    items = rng.sample(words, rng.randint(4, 5))
    extra = rng.choice([w for w in words if w not in items])
    lines = ["from collections import deque", "", f"{st} = []", f"{qu} = deque()",
             f"for item in {items!r}:", f"    {st}.append(item)", f"    {qu}.append(item)"]
    s, q = list(items), list(items)
    ops = rng.sample(["pop", "popleft", "push", "appendleft"], 3)
    for op in ops:
        if op == "pop":
            lines.append(f"{st}.pop()")
            s.pop()
        elif op == "popleft":
            lines.append(f"{qu}.popleft()")
            q.pop(0)
        elif op == "push":
            lines += [f"{st}.append({extra!r})", f"{qu}.append({extra!r})"]
            s.append(extra)
            q.append(extra)
        else:
            lines.append(f"{qu}.appendleft({st}[0])")
            q.insert(0, s[0])
    lines += [f"print({st}.pop(), {st}[-1])", f"print({qu}.popleft(), {qu}[0], len({qu}))"]
    a1 = s.pop()
    out = f"{a1} {s[-1]}\n{q.pop(0)} {q[0]} {len(q)}"
    code = "\n".join(lines)
    stem = (f"Что выведет программа ({ctx})? Запишите обе строки вывода; значения в строке "
            "разделены пробелом, как их печатает print.")
    ak = AnswerKey(kind="output", value=out,
                   explanation="list.append/pop работают с концом списка (LIFO), deque.append/"
                               "popleft — очередь FIFO; appendleft кладёт элемент в начало очереди.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"ops": ops})
