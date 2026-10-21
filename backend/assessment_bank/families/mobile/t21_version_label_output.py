"""mobile.release.t21_version_label_output — predict_output (набор t21, порог Стажёра): подпись версии
приложения — конкатенация строк и чисел слева направо.

Программа на JavaScript (экран «О приложении» в React Native) собирает две подписи из чисел major / minor / patch.
`+` выполняется слева направо: пока слева числа — складываются, как только слева строка — дальнейшие числа
приписываются как текст (`'v' + 3 + '.' + 7 + 1` → `v3.71`); скобки возвращают сложение чисел. Ключ — независимая
модель «плюса» JS в генераторе (свёртка слева направо); проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.release.t21_version_label_output"

CTX = ["экран «О приложении»", "подвал экрана настроек", "окно «Что нового»", "отчёт об ошибке из приложения",
       "экран обязательного обновления"]

# Формы выражений: токены — имена переменных, строковые литералы и группы в скобках (сумма чисел).
# trap=True — форма, где числа после строки приписываются, либо числа до строки складываются.
SHAPES = [
    ("tail_one", ["'v'", "major", "'.'", "minor", "'.'", "patch", "1"], True),
    ("head_sum", ["major", "minor", "'.'", "patch"], True),
    ("mid_concat", ["major", "'.'", "minor", "patch"], True),
    ("paren_next", ["'v'", "major", "'.'", "(minor + 1)", "'.0'"], False),
    ("paren_patch", ["'v'", "major", "'.'", "minor", "'.'", "(patch + 1)"], False),
    ("head_sum_v", ["major", "1", "'.'", "minor"], True),
]


def _val(tok: str, env: dict[str, int]):
    if tok.startswith("'"):
        return tok[1:-1]
    if tok.startswith("("):
        a, _plus, b = tok[1:-1].split()
        return env[a] + int(b)
    if tok.isdigit():
        return int(tok)
    return env[tok]


def _js_plus(tokens: list[str], env: dict[str, int]) -> tuple[str, list[str]]:
    """Свёртка a + b + c … слева направо по правилам JS: строка + что угодно → строка, число + число → число."""
    acc = _val(tokens[0], env)
    steps = []
    for tok in tokens[1:]:
        v = _val(tok, env)
        if isinstance(acc, str) or isinstance(v, str):
            acc = f"{acc}{v}"
        else:
            acc = acc + v
        steps.append(repr(acc) if isinstance(acc, str) else str(acc))
    return str(acc), steps


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    env = {"major": rng.randint(1, 9), "minor": rng.randint(2, 19), "patch": rng.randint(1, 9)}
    traps = [s for s in SHAPES if s[2]]
    first = rng.choice(traps)
    second = rng.choice([s for s in SHAPES if s[0] != first[0]])
    pair = [first, second]
    rng.shuffle(pair)
    names = rng.sample(["label", "title", "caption", "footer", "badge"], 2)
    lines = [f"const {k} = {env[k]};" for k in ("major", "minor", "patch")]
    outs, traces = [], []
    for name, (_sid, toks, _trap) in zip(names, pair):
        lines.append(f"const {name} = {' + '.join(toks)};")
        res, steps = _js_plus(toks, env)
        outs.append(res)
        traces.append(f"{name}: " + " → ".join(steps))
    lines += [f"console.log({names[0]});", f"console.log({names[1]});"]
    code = "\n".join(lines)
    out = "\n".join(outs)
    expl = ("Оператор + выполняется слева направо: число + число — сложение, а как только слева строка, следующие "
            "числа приписываются как текст; выражение в скобках вычисляется раньше. " + "; ".join(traces) +
            f". Вывод — две строки: «{outs[0]}» и «{outs[1]}».")
    stem = (f"React Native-приложение, {ctx}: программа собирает подписи версии из чисел major, minor и patch "
            f"(версия {env['major']}.{env['minor']}.{env['patch']}).")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"env": env, "shapes": [p[0] for p in pair]}, language="javascript")
