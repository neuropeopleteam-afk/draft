"""devops.retry.t21_backoff_gen_send_output — predict_output (набор t21, порог Senior): генератор-корутина паузы
повторов — next, send, return и StopIteration.value.

Генератор выдаёт паузу перед повтором; клиент сообщает результат попытки через `send`: «ok» сбрасывает паузу к
базовой, «stop» завершает генератор, остальное (в том числе None) увеличивает паузу до потолка. Правила: `next(g)`
доходит только до первого yield; значение `send(x)` становится результатом выражения yield, а сам вызов возвращает
СЛЕДУЮЩЕЕ выданное значение; `return v` в генераторе — это StopIteration с `.value == v`. Ключ — независимая
модель протокола в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.retry.t21_backoff_gen_send_output"

CTX = ["клиент API склада", "отправщик вебхуков", "загрузчик артефактов", "клиент реестра образов",
       "синхронизатор DNS", "клиент хранилища секретов", "отправщик метрик"]
FN = [("backoff", "delay"), ("pauses", "wait"), ("retry_delays", "pause"), ("schedule", "sleep_s")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn, dv = rng.choice(FN)
    base = rng.randint(1, 4)
    factor = rng.choice([2, 2, 3])
    cap = base * factor ** rng.randint(2, 3) - rng.choice([0, 1, 2])
    ok_word = rng.choice(["ok", "success", "done"])
    stop_word = rng.choice(["stop", "quit", "giveup"])
    for _ in range(200):
        k = rng.randint(3, 5)
        cmds = [rng.choice([None, "fail", "fail", ok_word, "timeout"]) for _ in range(k)]
        if ok_word in cmds and sum(c != ok_word for c in cmds) >= 2:
            break
    first = rng.choice(["next(g)", "g.send(None)"])
    lines = [f"def {fn}(base, cap):",
             f"    {dv} = base",
             "    while True:",
             f"        cmd = yield {dv}",
             f'        if cmd == "{stop_word}":',
             f'            return f"stopped at {{{dv}}}"',
             f'        {dv} = base if cmd == "{ok_word}" else min({dv} * {factor}, cap)',
             "",
             f"g = {fn}({base}, {cap})",
             f"print({first})",
             f"for cmd in {cmds!r}:",
             "    print(g.send(cmd))",
             "try:",
             f'    g.send("{stop_word}")',
             "except StopIteration as e:",
             '    print("result:", e.value)']
    code = "\n".join(lines)
    d = base
    outs = [str(d)]
    steps = [f"{first} → первый yield: {d}"]
    for c in cmds:
        d = base if c == ok_word else min(d * factor, cap)
        outs.append(str(d))
        steps.append(f"send({c!r}) → {d}")
    outs.append(f"result: stopped at {d}")
    out = "\n".join(outs)
    expl = (f"{first} запускает тело до первого yield и возвращает {base}. Каждый send(x) подставляет x как "
            f"результат yield, пересчитывает паузу (\"{ok_word}\" — сброс к {base}, иначе ×{factor}, но не больше "
            f"{cap}) и возвращает следующее выданное значение: " + "; ".join(steps[1:])
            + f". send(\"{stop_word}\") доходит до return — генератор бросает StopIteration, а возвращённая строка "
            f"лежит в e.value: «stopped at {d}». Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = f"{ctx[0].upper() + ctx[1:]} берёт паузу перед повтором из генератора и сообщает ему результат попытки."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"base": base, "cap": cap, "factor": factor, "cmds": cmds}, language="python")
