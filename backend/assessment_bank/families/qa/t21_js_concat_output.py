"""qa.reports.t21_js_concat_output — predict_output (набор t21, порог Стажёра, JavaScript): сложение строк и чисел
слева направо в подписи отчёта.

`"total: " + a + b` склеивает числа как строки («total: 72»), а `a + b + " tests"` сначала складывает числа
(«9 tests»); скобки возвращают арифметику. Программа печатает 3 строки сводки автотестов. Ключ — независимая модель
(вычисление слева направо с типами) в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.reports.t21_js_concat_output"

CTX = ["сводка автотестов фронтенда", "отчёт e2e-прогона личного кабинета", "итоги регресса мобильного веба",
       "сводка API-тестов в CI", "отчёт ночного прогона витрины"]
NAMES = [("passed", "failed", "skipped"), ("ok", "fail", "skip"), ("green", "red", "pending")]


def _eval(tokens):
    """Слева направо: число + число = сумма; если хоть один операнд строка — склейка."""
    acc = tokens[0]
    for t in tokens[1:]:
        if isinstance(acc, int) and isinstance(t, int):
            acc = acc + t
        else:
            acc = str(acc) + str(t)
    return str(acc)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    pn, fn, sn = rng.choice(NAMES)
    p, f, s = rng.randint(3, 48), rng.randint(1, 9), rng.randint(1, 9)
    label = rng.choice(["total", "all", "sum"])
    forms = {
        "str_first": (f'"{label}: " + {pn} + {fn}', [f"{label}: ", p, f],
                      f'строка слева — {pn} и {fn} приклеиваются как текст: "{label}: {p}{f}"'),
        "num_first": (f'{pn} + {fn} + {sn} + " tests"', [p, f, s, " tests"],
                      f'сначала числа: {p} + {f} + {s} = {p + f + s}, потом строка: "{p + f + s} tests"'),
        "paren": (f'"not passed: " + ({fn} + {sn})', None,
                  f'скобки первыми: {f} + {s} = {f + s}, затем склейка: "not passed: {f + s}"'),
        "mixed": (f'{fn} + {sn} + "/" + {pn} + {fn}', [f, s, "/", p, f],
                  f'{f} + {s} = {f + s}, дальше строка "/" — остальное приклеивается: "{f + s}/{p}{f}"'),
    }
    keys = rng.sample(["str_first", "num_first", "paren", "mixed"], 3)
    if not ({"str_first", "mixed"} & set(keys)):
        keys[0] = rng.choice(["str_first", "mixed"])
    lines, outs, notes = [], [], []
    for k in keys:
        src, toks, note = forms[k]
        lines.append(f"console.log({src});")
        outs.append(f"not passed: {f + s}" if toks is None else _eval(toks))
        notes.append(note)
    code = "\n".join([f"const {pn} = {p};", f"const {fn} = {f};", f"const {sn} = {s};", *lines])
    out = "\n".join(outs)
    expl = ("Оператор + выполняется слева направо; пока оба операнда — числа, он складывает, как только один из них "
            "строка — склеивает. По строкам: " + "; ".join(notes) + ".")
    stem = f"{ctx[0].upper() + ctx[1:]}: программа собирает строки итогов из счётчиков тестов ({pn}, {fn}, {sn})."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"counts": [p, f, s], "forms": keys}, language="javascript")
