"""security.input.t21_regex_anchor_output — predict_output (набор t21, порог Senior): `re.match` против
`re.fullmatch` для шаблона разрешённых символов и `$`, который допускает завершающий перевод строки.

Валидация логина тремя способами: `re.match(r"[...]+", s)` — совпадение только с началом («admin;rm» проходит),
`re.match(r"^[...]+$", s)` — `$` совпадает и перед последним «\\n» («backup\\n» проходит), `re.fullmatch` — строка
целиком. Плюс регистр (класс без заглавных) и пустая строка (`+` требует символа). Ключ — независимая
посимвольная модель в генераторе (без re); проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.input.t21_regex_anchor_output"

CTX = ["регистрация пользователей", "имена сервисных учёток", "метки ресурсов в облаке", "имена веток сборки",
       "идентификаторы арендаторов"]
LOWER = "abcdefghijklmnopqrstuvwxyz"
CLASSES = [("[a-z0-9_]", LOWER + "0123456789_"), ("[a-z0-9-]", LOWER + "0123456789-"),
           ("[a-z0-9._]", LOWER + "0123456789._"), ("[a-z]", LOWER)]
WORDS = ["admin", "backup", "deploy", "ops", "report", "guest", "ci", "audit"]


def _model(s: str, allowed: str) -> tuple[bool, bool, bool]:
    ok = lambda x: len(x) > 0 and all(ch in allowed for ch in x)  # noqa: E731
    p1 = len(s) > 0 and s[0] in allowed
    p2 = ok(s) or (s.endswith("\n") and ok(s[:-1]))
    return p1, p2, ok(s)


def _inputs(rng, allowed: str) -> list[str]:
    w, w2 = rng.sample(WORDS, 2)
    digit = "7" if "7" in allowed else ""
    pool = [w + digit,                                  # чистый
            w + rng.choice([";rm", " x", "&id", "|ls"]),  # совпало начало
            w2 + "\n",                                  # завершающий перевод строки
            rng.choice([w.capitalize(), w.upper()]),    # регистр
            rng.choice([";" + w, " " + w]),             # мусор в начале
            w2 + "\nid",                                 # перевод строки в середине
            ""]
    pick = [pool[1], pool[2]] + rng.sample([pool[0], pool[3], pool[4], pool[5], pool[6]], rng.randint(2, 3))
    rng.shuffle(pick)
    return pick


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    cls, allowed = rng.choice(CLASSES)
    inputs = _inputs(rng, allowed)
    lit = ", ".join(repr(s).replace("'", '"') for s in inputs)
    code = ("import re\n"
            f"names = [{lit}]\n"
            "for s in names:\n"
            f'    a = re.match(r"{cls}+", s) is not None\n'
            f'    b = re.match(r"^{cls}+$", s) is not None\n'
            f'    c = re.fullmatch(r"{cls}+", s) is not None\n'
            "    print(a, b, c)")
    rows = [_model(s, allowed) for s in inputs]
    out = "\n".join(" ".join(str(x) for x in r) for r in rows)
    trace = "; ".join(f"{repr(s)} → {' '.join(str(x) for x in r)}" for s, r in zip(inputs, rows))
    expl = ("re.match привязан только к началу строки: достаточно, чтобы первый символ подходил. В ^…$ знак «$» "
            "совпадает в конце строки и перед последним «\\n», поэтому строка с завершающим переводом проходит; "
            "re.fullmatch требует совпадения всей строки. Класс без заглавных букв, «+» требует хотя бы одного "
            f"символа. {trace}. Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Валидация ввода ({ctx}): программа проверяет значения по шаблону разрешённых символов тремя "
            "способами.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"class": cls, "inputs": inputs}, language="python")
