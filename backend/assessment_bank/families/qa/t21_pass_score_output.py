"""qa.reports.t21_pass_score_output — predict_output (набор t21, порог Стажёра): приоритет арифметических операций
в формуле «балла качества» прогона.

Программа складывает счётчики прогона и считает балл по формуле без лишних скобок. Умножение выполняется раньше
сложения и вычитания, а цепочка «−, +» — слева направо. Ловушка: прочитать `100 - f * w + s` как `100 - (f * w + s)`
или забыть, что скобки меняют порядок. Ключ — независимое вычисление в генераторе (формула собрана из токенов);
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.reports.t21_pass_score_output"

CTX = ["регресс мобильного приложения", "API-тесты платёжного шлюза", "смоук-набор личного кабинета",
       "ночной прогон UI-тестов каталога", "интеграционные тесты склада"]
NAMES = [("passed", "failed", "skipped"), ("ok", "broken", "ignored"), ("green", "red", "muted")]
# формы балла: (шаблон, функция) — шаблон с местами {f} {s} {w} {v}
FORMS = [
    ("100 - {f} * {w} + {s}", lambda f, s, w, v: 100 - f * w + s, "сначала {f} * {w} = {fw}, затем слева направо: "
     "100 − {fw} = {a1}, {a1} + {s} = {q}"),
    ("100 - ({f} + {s}) * {w}", lambda f, s, w, v: 100 - (f + s) * w, "скобки первыми: {f} + {s} = {fs}, "
     "затем {fs} * {w} = {fsw}, 100 − {fsw} = {q}"),
    ("100 - {f} + {s} * {v}", lambda f, s, w, v: 100 - f + s * v, "сначала {s} * {v} = {sv}, затем слева направо: "
     "100 − {f} = {a2}, {a2} + {sv} = {q}"),
    ("100 - {f} * {w} - {s} * {v}", lambda f, s, w, v: 100 - f * w - s * v, "сначала произведения {f} * {w} = {fw} "
     "и {s} * {v} = {sv}, затем 100 − {fw} − {sv} = {q}"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    pn, fn, sn = rng.choice(NAMES)
    p = rng.randint(18, 64)
    f = rng.randint(1, 7)
    s = rng.randint(1, 6)
    w = rng.choice([3, 4, 5, 6, 10])
    v = rng.choice([2, 3])
    tpl, fun, how = rng.choice(FORMS)
    expr = tpl.format(f=fn, s=sn, w=w, v=v)
    total = p + f + s
    q = fun(f, s, w, v)
    total_var = rng.choice(["total", "runs", "count"])
    score_var = rng.choice(["score", "quality", "grade"])
    code = (f"{pn} = {p}\n"
            f"{fn} = {f}\n"
            f"{sn} = {s}\n"
            f"{total_var} = {pn} + {fn} + {sn}\n"
            f"{score_var} = {expr}\n"
            f"print({total_var}, {score_var})")
    out = f"{total} {q}"
    trace = how.format(f=f, s=s, w=w, v=v, fw=f * w, a1=100 - f * w, fs=f + s, fsw=(f + s) * w, sv=s * v,
                       a2=100 - f, q=q)
    expl = (f"{total_var} = {p} + {f} + {s} = {total}. В {score_var} = {expr}: {trace}. "
            f"Ловушка — порядок операций: * раньше + и −, а + и − выполняются слева направо (без скрытых скобок). "
            f"Вывод: «{out}».")
    stem = (f"Отчёт о прогоне ({ctx}): программа считает число тестов и балл качества сборки по счётчикам "
            f"результатов.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"form": tpl, "counts": [p, f, s], "w": w, "v": v}, language="python")
