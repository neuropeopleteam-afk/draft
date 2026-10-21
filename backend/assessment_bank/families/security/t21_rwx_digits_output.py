"""security.perm.t21_rwx_digits_output — predict_output (набор t21, порог Стажёра): права файла из строк вида
«rw-» / «r--» / «---» в цифровую запись: цикл по символам со словарём весов и склейка цифр в строку.

Скрипт аудита прав переводит три тройки прав (владелец, группа, остальные) в цифры: для каждой тройки складывает
веса символов `{"r": 4, "w": 2, "x": 1}` («-» даёт 0 — через `.get(ch, 0)` или ключ `"-": 0` в словаре), цифру
приписывает к строке `mode += str(n)` и сравнивает результат с требуемым режимом (например, «600» для приватного
ключа). Ловушки чтения: внутри тройки веса СКЛАДЫВАЮТСЯ, а цифры троек СКЛЕИВАЮТСЯ строкой (не сумма 4 + 4 + 0);
«-» не добавляет ничего; сравнение строк — точное. Ключ — независимая модель (таблица тройка → цифра) в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.perm.t21_rwx_digits_output"

# независимая модель: тройка прав → цифра (таблица, без словаря весов)
DIGIT = {"---": 0, "--x": 1, "-w-": 2, "-wx": 3, "r--": 4, "r-x": 5, "rw-": 6, "rwx": 7}

# (контекст, условие, требуемый режим, варианты троек владельца / группы / остальных)
CTX = [("приватный ключ SSH",
        "Перед запуском деплоя скрипт аудита проверяет права на приватный ключ SSH: тройки прав из вывода ls "
        "переводятся в цифровую запись и сравниваются с требуемой.",
        "600", ["rw-", "rw-", "r--", "rwx"], ["---", "---", "r--", "rw-"], ["---", "---", "r--"]),
       ("файл с секретами",
        "Сканер конфигурации сервера проверяет права на файл с паролями к базе: тройки прав переводятся в цифровую "
        "запись и сравниваются с политикой.",
        "640", ["rw-", "rw-", "rwx"], ["r--", "r--", "rw-", "---"], ["---", "---", "r--"]),
       ("скрипт в cron",
        "Аудит планировщика проверяет права на скрипт, который cron запускает от root: тройки прав переводятся в "
        "цифровую запись и сравниваются с требуемой.",
        "750", ["rwx", "rwx", "rw-"], ["r-x", "r-x", "rwx", "r--"], ["---", "---", "r-x"]),
       ("публичный файл сайта",
        "Перед выкладкой сайта скрипт проверяет права на статические файлы: тройки прав переводятся в цифровую "
        "запись и сравниваются с эталоном.",
        "644", ["rw-", "rw-", "rwx"], ["r--", "r--", "rw-"], ["r--", "r--", "rw-", "---"]),
       ("каталог с журналами",
        "Проверка соответствия политике сравнивает права на каталог с журналами аудита с требуемыми: тройки прав "
        "переводятся в цифровую запись.",
        "700", ["rwx", "rwx", "rw-"], ["---", "---", "r-x"], ["---", "---", "r-x"])]
NAMES = [("bits", "mode", "part", "ch", "n"), ("weight", "octal", "triple", "c", "d"),
         ("value", "digits", "group", "sym", "total"), ("bits", "perm", "chunk", "ch", "acc"),
         ("weights", "code", "rwx", "ch", "s"), ("w", "result", "p", "letter", "num")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem, need, owners, groups, others = rng.choice(CTX)
    match = rng.random() < 0.35
    for _ in range(200):
        triples = [rng.choice(owners), rng.choice(groups), rng.choice(others)]
        got = "".join(str(DIGIT[t]) for t in triples)
        if (got == need) == match:
            break
    else:
        raise RuntimeError("t21_rwx_digits: не собрались права")
    bv, mv, pv, cv, nv = rng.choice(NAMES)
    dash_key = rng.random() < 0.5
    mode_first = rng.random() < 0.7
    dct = '{"r": 4, "w": 2, "x": 1, "-": 0}' if dash_key else '{"r": 4, "w": 2, "x": 1}'
    add = f"{bv}[{cv}]" if dash_key else f"{bv}.get({cv}, 0)"
    lst = "[" + ", ".join(f'"{t}"' for t in triples) + "]"
    lines = [f"{bv} = {dct}",
             f'{mv} = ""',
             f"for {pv} in {lst}:",
             f"    {nv} = 0",
             f"    for {cv} in {pv}:",
             f"        {nv} += {add}",
             f"    {mv} += str({nv})",
             (f'print({mv}, {mv} == "{need}")' if mode_first else f'print({mv} == "{need}", {mv})')]
    code = "\n".join(lines)
    out = f"{got} {got == need}" if mode_first else f"{got == need} {got}"
    trace = ", ".join(f"«{t}» → {' + '.join(str({'r': 4, 'w': 2, 'x': 1}.get(ch, 0)) for ch in t)} = {DIGIT[t]}"
                      for t in triples)
    s = sum(DIGIT[t] for t in triples)
    expl = (f"Внутри каждой тройки веса складываются: {trace} («-» даёт 0). Цифры не суммируются (было бы {s}), "
            f"а приписываются к строке через str(): {mv} = \"{got}\". Сравнение строк с \"{need}\" — "
            f"{got == need}. Вывод: «{out}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"triples": triples, "need": need, "dash_key": dash_key, "mode_first": mode_first}, language="python")
