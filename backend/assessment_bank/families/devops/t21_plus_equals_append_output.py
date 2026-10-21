"""devops.bash.t21_plus_equals_append_output — predict_output (набор t21, порог Стажёра): `+=` и `$(( ))` в bash —
дописывание строки против сложения чисел.

Скрипт настройки воркера меняет три числовых параметра разными способами и печатает их одной строкой. В bash без
арифметического контекста `v+=1` ДОПИСЫВАЕТ «1» к строке («2» → «21»), `v=$v+5` даёт строку «30+5»; складывают
числа только `v=$((v + 1))` и `((v += 1))`. В каждом варианте есть хотя бы одно дописывание `+=`. Ключ — независимая
модель в генераторе; проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_plus_equals_append_output"

CTX = ["воркер очереди писем", "обработчик платежей", "индексатор поиска", "сборщик логов", "экспортёр метрик",
       "планировщик резервных копий", "агент выкладки"]
PARAMS = [("retries", 1, 5), ("workers", 2, 8), ("timeout", 10, 60), ("replicas", 2, 6), ("threads", 2, 16),
          ("batch", 10, 50), ("port", 8000, 8090)]
FORMS = ["append", "arith", "arith_cmd", "str_plus"]


def _line(form: str, name: str, d: int) -> str:
    if form == "append":
        return f"{name}+={d}"
    if form == "arith":
        return f"{name}=$(({name} + {d}))"
    if form == "arith_cmd":
        return f"(({name} += {d}))"
    return f"{name}=${name}+{d}"


def _value(form: str, v: int, d: int) -> str:
    if form == "append":
        return f"{v}{d}"
    if form in ("arith", "arith_cmd"):
        return str(v + d)
    return f"{v}+{d}"


def _why(form: str, name: str, v: int, d: int) -> str:
    res = _value(form, v, d)
    if form == "append":
        return f"`{name}+={d}` вне $(( )) дописывает строку: «{v}» + «{d}» = «{res}»"
    if form == "arith":
        return f"`$(( ))` складывает числа: {v} + {d} = {res}"
    if form == "arith_cmd":
        return f"`(( += ))` — арифметический контекст: {v} + {d} = {res}"
    return f"`{name}=${name}+{d}` — просто строка «{res}», знак + не вычисляется"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    params = rng.sample(PARAMS, 3)
    forms = ["append"] + [rng.choice(FORMS) for _ in range(2)]
    if not any(f in ("arith", "arith_cmd") for f in forms):  # для контраста — хотя бы одно настоящее сложение
        forms[rng.randint(1, 2)] = rng.choice(["arith", "arith_cmd"])
    rng.shuffle(forms)
    lines, outs, why = [], [], []
    for (name, lo, hi), form in zip(params, forms):
        v = rng.randint(lo, hi)
        d = rng.randint(1, 9)
        lines.append(f"{name}={v}")
        lines.append(_line(form, name, d))
        outs.append(f"{name}={_value(form, v, d)}")
        why.append(_why(form, name, v, d))
    lines.append('echo "' + " ".join(f"{n}=${n}" for n, _, _ in params) + '"')
    code = "\n".join(lines)
    out = " ".join(outs)
    expl = "; ".join(why) + f". Вывод: «{out}»."
    stem = f"Скрипт запуска ({ctx}) поправляет три параметра перед стартом и печатает их одной строкой."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"forms": forms, "names": [p[0] for p in params]}, language="bash")
