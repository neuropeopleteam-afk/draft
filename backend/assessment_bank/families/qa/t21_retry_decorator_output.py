"""qa.flaky.t21_retry_decorator_output — predict_output (набор t21, порог Senior): декоратор повторов для
нестабильной проверки — журнал попыток в замыкании, except только для AssertionError и finally.

`retry(fn)` возвращает wrapper, который перебирает записанные ответы сервиса: на каждой попытке пишет её в журнал
`log` (общий список в замыкании декоратора), проверяет `assert fn(code)` и при успехе возвращает "pass"; `except
AssertionError` переходит к следующей попытке, `finally` печатает номер попытки. Ловушки: журнал один на все вызовы
декорированной проверки — нумерация попыток второй проверки продолжается; `finally` печатает и при return, и при
исключении, причём ДО того, как вызывающий print напечатает итог; ValueError из int("n/a") не ловится except
AssertionError и пролетает к вызывающему (finally всё равно печатает); если все попытки провалились, wrapper
доходит до конца и возвращает None. Ключ — независимая модель попыток в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.flaky.t21_retry_decorator_output"

CTX = [("нестабильные UI-тесты витрины", ["login", "cart", "search", "profile"]),
       ("смоук платёжного API", ["auth", "charge", "refund", "status"]),
       ("регресс мобильного бэкенда", ["feed", "push", "upload", "sync"]),
       ("проверки после выкладки", ["health", "orders", "reports", "billing"])]
PREDS = [("int(code) == 200", lambda v: v == 200, "ответ ровно 200"),
         ("int(code) < 500", lambda v: v < 500, "код меньше 500"),
         ("int(code) in (200, 204)", lambda v: v in (200, 204), "код 200 или 204")]
BAD_TEXT = ["n/a", "null", "html", "oops"]
LABELS = ["try", "attempt", "run"]


def _codes(rng, ok, kind):
    """Последовательность ответов для одной проверки: pass — успех после 0–2 провалов, fail — все провалы,
    crash — нечисловой ответ после 0–1 провала (и, возможно, ещё ответы после него)."""
    good = [c for c in [200, 204, 302] if ok(c)]
    bad = [c for c in [500, 502, 503, 504, 404, 429] if not ok(c)]
    if kind == "pass":
        return [rng.choice(bad) for _ in range(rng.randint(1, 2))] + [rng.choice(good)]
    if kind == "fail":
        return [rng.choice(bad) for _ in range(rng.randint(2, 3))]
    head = [rng.choice(bad) for _ in range(rng.randint(0, 1))]
    return head + [rng.choice(BAD_TEXT)] + ([rng.choice(good)] if rng.random() < 0.5 else [])


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, names = rng.choice(CTX)
    pred_src, ok, pred_ru = rng.choice(PREDS)
    lbl = rng.choice(LABELS)
    two = rng.sample(names, 2)
    kinds = ["crash", rng.choice(["pass", "pass", "fail"])]
    rng.shuffle(kinds)
    seqs = [_codes(rng, ok, k) for k in kinds]
    # модель
    outs, log, trace = [], 0, []
    for name, codes, kind in zip(two, seqs, kinds):
        res = None
        crashed = False
        for c in codes:
            log += 1
            if isinstance(c, str):
                outs.append(f"{lbl} {log} {c}")
                crashed = True
                trace.append(f"{name}: попытка {log} — int(\"{c}\") бросает ValueError, except AssertionError её не "
                             f"ловит, finally печатает попытку, исключение уходит к вызывающему")
                break
            outs.append(f"{lbl} {log} {c}")
            if ok(c):
                res = "pass"
                trace.append(f"{name}: попытка {log} — {c} проходит, return \"pass\" (finally печатает до итога)")
                break
            trace.append(f"{name}: попытка {log} — {c} не проходит, AssertionError, следующая попытка")
        if crashed:
            outs.append(f"{name} crashed")
        else:
            if res is None:
                trace.append(f"{name}: ответы кончились — wrapper доходит до конца и возвращает None")
            outs.append(f"{name} {res}")
    lit = lambda seq: "(" + ", ".join(repr(c) if isinstance(c, str) else str(c) for c in seq) + \
        ("," if len(seq) == 1 else "") + ")"  # noqa: E731
    pairs = ", ".join(f'("{n}", {lit(s)})' for n, s in zip(two, seqs))
    code = "\n".join([
        "def retry(fn):",
        "    log = []",
        "    def wrapper(*codes):",
        "        for code in codes:",
        "            log.append(code)",
        "            try:",
        "                assert fn(code)",
        '                return "pass"',
        "            except AssertionError: pass",
        "            finally:",
        f'                print("{lbl}", len(log), code)',
        "    return wrapper",
        "",
        f"check = retry(lambda code: {pred_src})",
        f"for name, codes in [{pairs}]:",
        "    try:",
        "        print(name, check(*codes))",
        "    except ValueError:",
        '        print(name, "crashed")',
    ]).replace("'", '"')
    out = "\n".join(outs)
    expl = (f"Проверка проходит, если {pred_ru}. Журнал log — один список в замыкании retry, поэтому номер попытки "
            f"второй проверки продолжает первую. " + "; ".join(trace) + ". Вывод по строкам: "
            + " / ".join(f"«{o}»" for o in outs) + ".")
    stem = (f"Автотесты ({ctx}): нестабильную проверку оборачивают декоратором повторов и прогоняют на записанных "
            f"ответах сервиса для двух сценариев.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"seqs": [[str(c) for c in s] for s in seqs], "kinds": kinds, "pred": pred_src},
                          language="python")
