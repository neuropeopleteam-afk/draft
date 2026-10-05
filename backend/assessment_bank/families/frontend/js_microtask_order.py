"""frontend.js.microtask_order — mcq_concept: порядок микрозадач, await и таймеров.

Дистракторы — результаты «ошибочных ментальных моделей» цикла событий (см. _event_loop):
таймеры раньше промисов, цепочка then подряд, await без приостановки и т. д.
"""
from __future__ import annotations

from assessment_bank.families.frontend._event_loop import WRONG_MODELS, js_lines, simulate
from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.microtask_order"

CTX = [("loadProfile", "загрузка профиля"), ("syncCart", "синхронизация корзины"),
       ("refreshFeed", "обновление ленты"), ("initChart", "инициализация графика"),
       ("saveDraft", "сохранение черновика")]
WHY = {"timers_first": "таймер с нулевой задержкой не выполняется раньше микрозадач",
       "chain_eager": "следующий then цепочки ставится в очередь только после предыдущего",
       "await_sync": "await приостанавливает функцию до следующей микрозадачи",
       "executor_async": "исполнитель new Promise выполняется синхронно",
       "qm_macro": "queueMicrotask ставит микрозадачу, а не таймер",
       "source_order": "асинхронные колбэки не выполняются в порядке строк"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, ctx = rng.choice(CTX)
    for _ in range(200):
        kinds = ["async", "then2", rng.choice(["timeout", "timeout_micro"]), "log"]
        kinds += rng.sample(["qm", "executor", "then1", "timeout"], rng.randint(1, 2))
        rng.shuffle(kinds)
        n = sum(3 if k == "async" else 2 if k in ("then2", "timeout_micro", "executor") else 1
                for k in kinds)
        if n > 10:
            continue
        labels = rng.sample(list("ABCDEFGHKMNPRS"[:max(n, 10)]), n)
        it = iter(labels)
        stmts = []
        for k in kinds:
            if k == "async":
                stmts.append((k, next(it), next(it), next(it), fn))
            elif k in ("then2", "timeout_micro", "executor"):
                stmts.append((k, next(it), next(it)))
            else:
                stmts.append((k, next(it)))
        correct = " ".join(simulate(stmts))
        wrong = {}
        models = list(WRONG_MODELS)
        rng.shuffle(models)
        for mdl in models:
            w = " ".join(simulate(stmts, mdl))
            if w != correct and w not in wrong.values():
                wrong[mdl] = w
        if len(wrong) >= 3:
            break
    else:
        raise RuntimeError("мало дистракторов")
    chosen = list(wrong)[:3]
    opts, key = make_options(rng, (correct, None), [(wrong[m], None) for m in chosen])
    code = "\n".join(js_lines(stmts))
    stem = (f"Код ({ctx}) выполняется в Node.js 20 как обычный скрипт; каждая строка вывода — "
            f"одна буква. В каком порядке буквы появятся в консоли?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="Синхронный код (включая начало async-функции до await и тело "
                               "исполнителя Promise) → микрозадачи по очереди постановки "
                               "(каждый следующий then и продолжение после await — новая "
                               "микрозадача) → таймеры, после каждого — его микрозадачи. "
                               "Неверные варианты: " + "; ".join(WHY[m] for m in chosen) + ".")
    checks = [Check(name="stdout", runner="node", program=code, expect="stdout_equals",
                    expected_stdout=correct.replace(" ", "\n"))]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         params={"kinds": kinds, "distractor_models": chosen})
