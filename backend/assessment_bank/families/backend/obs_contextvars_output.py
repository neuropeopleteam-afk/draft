"""backend.obs.contextvars_output — predict_output: request_id в логах через contextvars и asyncio.

Корреляция логов по request_id держится на семантике контекста:
* прямой `await coro()` выполняется в том же контексте — `set` внутри виден вызывающему;
* `asyncio.create_task` и `gather` копируют контекст в момент создания задачи — изменения
  после создания и внутри задачи не видны снаружи;
* `asyncio.to_thread` копирует контекст в поток, `loop.run_in_executor` — нет (значение по
  умолчанию).
Ключ считает независимая модель «ячеек контекста», вывод сверяется с исполнением.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.obs.contextvars_output"

CHILDREN = [("audit", "аудит"), ("notify", "уведомления"), ("send_metric", "метрики"),
            ("publish_event", "события")]
CONTEXTS = ["API заказов", "платёжный шлюз", "профили пользователей", "API поиска", "доставка"]
HANDLE_STEPS = ["direct", "task", "thread", "executor"]


def _code(child, child_sets, steps, set_after, main_modes, rids, var):
    lines = ["import asyncio", "import contextvars", "",
             f'{var} = contextvars.ContextVar("{var}", default="-")', "", "",
             "def log(msg):", f'    print(f"[{{{var}.get()}}] {{msg}}")', "", "",
             f"async def {child}(tag):", "    await asyncio.sleep(0)"]
    if child_sets:
        lines.append(f'    {var}.set({var}.get() + "/{child[:3]}")')
    lines += [f'    log(f"{child} {{tag}}")', "", "", "async def handle(rid):", f"    {var}.set(rid)"]
    for st in steps:
        if st == "direct":
            lines.append(f'    await {child}("a")')
        elif st == "task":
            lines.append(f'    task = asyncio.create_task({child}("b"))')
            if set_after:
                lines.append(f'    {var}.set(rid + "-x")')
            lines.append("    await task")
        elif st == "thread":
            lines.append('    await asyncio.to_thread(log, "thread")')
        else:
            lines.append('    await asyncio.get_running_loop().run_in_executor(None, log, "executor")')
    lines += ['    log("done")', "", "", "async def main():", '    log("start")']
    for mode, rid in zip(main_modes, rids):
        call = {"direct": f'await handle("{rid}")',
                "task": f'await asyncio.create_task(handle("{rid}"))',
                "gather": f'await asyncio.gather(handle("{rid}"))'}[mode]
        lines += [f"    {call}", f'    log("after {rid}")']
    lines += ["", "", "asyncio.run(main())"]
    return "\n".join(lines)


def _model(child, child_sets, steps, set_after, main_modes, rids) -> str:
    """Независимая модель: контекст — изменяемая ячейка; задача получает копию ячейки."""
    out: list[str] = []

    def run_child(cell, tag):
        if child_sets:
            cell["v"] += f"/{child[:3]}"
        out.append(f"[{cell['v']}] {child} {tag}")

    def run_handle(cell, rid):
        cell["v"] = rid
        for st in steps:
            if st == "direct":
                run_child(cell, "a")
            elif st == "task":
                snapshot = {"v": cell["v"]}
                if set_after:
                    cell["v"] = rid + "-x"
                run_child(snapshot, "b")
            elif st == "thread":
                out.append(f"[{cell['v']}] thread")
            else:
                out.append("[-] executor")
        out.append(f"[{cell['v']}] done")

    main = {"v": "-"}
    out.append("[-] start")
    for mode, rid in zip(main_modes, rids):
        run_handle(main if mode == "direct" else {"v": main["v"]}, rid)
        out.append(f"[{main['v']}] after {rid}")
    return "\n".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    child, what = rng.choice(CHILDREN)
    ctx = rng.choice(CONTEXTS)
    var = rng.choice(["request_id", "trace_id", "correlation_id"])
    child_sets = rng.random() < 0.5
    first = rng.choice(["direct", "task"])
    rest = rng.sample([s for s in HANDLE_STEPS if s != first], rng.randint(1, 2))
    steps = [first] + rest
    rng.shuffle(steps)
    set_after = "task" in steps and rng.random() < 0.6
    main_modes = [rng.choice(["direct", "task", "gather"]), rng.choice(["direct", "task", "gather"])]
    if "direct" not in main_modes and rng.random() < 0.6:
        main_modes[rng.randrange(2)] = "direct"
    rids = [f"r{rng.randint(10, 99)}", f"r{rng.randint(100, 999)}"]
    code = _code(child, child_sets, steps, set_after, main_modes, rids, var)
    out = _model(child, child_sets, steps, set_after, main_modes, rids)
    stem = (f"Сервис ({ctx}) пишет `{var}` в каждую строку лога через `contextvars`, чтобы "
            f"связать записи одного запроса; фоновая отправка ({what}) — корутина `{child}`. "
            f"Что напечатает программа (Python 3.12)? Запишите вывод точно, по строкам.")
    notes = []
    if "direct" in steps or "direct" in main_modes:
        notes.append("прямой await выполняется в том же контексте: set внутри виден вызывающему")
    if "task" in steps or set(main_modes) & {"task", "gather"}:
        notes.append("create_task/gather копируют контекст при создании задачи: изменения внутри "
                     "задачи и после её создания не видны другой стороне")
    if "thread" in steps:
        notes.append("to_thread копирует контекст в поток")
    if "executor" in steps:
        notes.append("run_in_executor не копирует контекст — в потоке значение по умолчанию «-»")
    ak = AnswerKey(kind="output", value=out, explanation="; ".join(notes).capitalize() + ".")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"steps": steps, "child_sets": child_sets, "set_after": set_after,
                                 "main_modes": main_modes})
