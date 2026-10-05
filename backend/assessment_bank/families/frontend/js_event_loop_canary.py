"""frontend.js.event_loop_canary — predict_output (канарейка): синхронный код, промис, таймер."""
from __future__ import annotations

from assessment_bank.families.frontend._event_loop import js_lines, simulate
from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.event_loop_canary"

WORDS = ["альфа", "бета", "гамма", "дельта", "омега", "север", "юг", "восток", "запад",
         "центр"]
CTX = ["обработчик клика", "загрузка страницы", "инициализация виджета", "отправка формы"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    kinds = ["log", "log", "timeout", rng.choice(["then1", "qm"])]
    if rng.random() < 0.5:
        kinds.append(rng.choice(["log", "then1", "timeout"]))
    rng.shuffle(kinds)
    if kinds[0] != "log" and rng.random() < 0.5:
        i = kinds.index("log")
        kinds[0], kinds[i] = kinds[i], kinds[0]
    words = rng.sample(WORDS, len(kinds))
    stmts = [(k, w) for k, w in zip(kinds, words)]
    code = "\n".join(js_lines(stmts))
    out = "\n".join(simulate(stmts))
    ctx = rng.choice(CTX)
    stem = (f"Фрагмент кода ({ctx}) выполняется в Node.js 20 как обычный скрипт. Что он "
            f"выведет? Запишите строки вывода по порядку.")
    ak = AnswerKey(kind="output", value=out,
                   explanation="Сначала весь синхронный код, затем очередь микрозадач "
                               "(then, queueMicrotask), затем таймеры в порядке постановки.")
    checks = [Check(name="stdout", runner="node", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"kinds": kinds})
