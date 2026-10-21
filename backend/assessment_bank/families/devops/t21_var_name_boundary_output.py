"""devops.bash.t21_var_name_boundary_output — predict_output (набор t21, порог Стажёра): где кончается имя
переменной при подстановке `$NAME` в bash.

Скрипт выкладки собирает из переменных имена образа и окружения несколькими echo. Имя переменной после `$` — самая
длинная последовательность букв, цифр и `_`: в `"$APP_$ENV"` подставляется незаданная переменная `APP_` (пусто), а
`-`, `.`, `:` имя обрывают; фигурные скобки `${APP}_` задают границу явно. В каждом варианте есть хотя бы одна такая
ловушка. Ключ — независимая модель подстановки в генераторе; проверка — исполнение показанного скрипта в bash.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_var_name_boundary_output"

CTX = [("выкладка биллинга", "billing"), ("релиз каталога", "catalog"), ("выкладка платёжного шлюза", "payments"),
       ("релиз поиска", "search"), ("выкладка личного кабинета", "cabinet"), ("релиз сервиса уведомлений", "notify"),
       ("выкладка CRM", "crm"), ("релиз склада", "stock")]
ENVS = ["prod", "stage", "dev", "test"]
REGIONS = ["msk", "spb", "nsk", "ekb", "kzn"]
# Формы строки echo: (шаблон: @X — `$имя`, @{X} — `${имя}`; A — сервис, E — окружение, V — версия, R — регион;
# ловушка?)
FORMS = [
    ("@A_@E", True), ("@A_v@V", True), ("@E_@R", True), ("@A_@R-@V", True),
    ("@{A}_@E", False), ("@A-@E", False), ("@A.@R", False), ("@{A}_v@V", False), ("@A:@V-@E", False),
    ("@{E}_@R", False),
]


def _expand(tpl: str, names: dict[str, str], vals: dict[str, str]) -> tuple[str, str]:
    """(текст в скрипте, результат подстановки) — модель: имя после $ жадно берёт [A-Za-z0-9_]."""
    shown = tpl
    for k in ("A", "E", "V", "R"):
        shown = shown.replace("@{" + k + "}", "${" + names[k] + "}").replace("@" + k, "$" + names[k])
    env = {names[k]: vals[k] for k in names}
    res, i = [], 0
    while i < len(shown):
        ch = shown[i]
        if ch == "$" and i + 1 < len(shown) and shown[i + 1] == "{":
            j = shown.index("}", i)
            res.append(env.get(shown[i + 2:j], ""))
            i = j + 1
        elif ch == "$":
            j = i + 1
            while j < len(shown) and (shown[j].isalnum() or shown[j] == "_"):
                j += 1
            res.append(env.get(shown[i + 1:j], ""))
            i = j
        else:
            res.append(ch)
            i += 1
    return shown, "".join(res)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, app = rng.choice(CTX)
    names = rng.choice([{"A": "APP", "E": "ENV", "V": "VER", "R": "REGION"},
                        {"A": "SERVICE", "E": "STAGE", "V": "BUILD", "R": "DC"},
                        {"A": "NAME", "E": "TIER", "V": "REV", "R": "ZONE"}])
    vals = {"A": app, "E": rng.choice(ENVS), "V": str(rng.randint(2, 48)), "R": rng.choice(REGIONS)}
    traps = [f for f in FORMS if f[1]]
    plain = [f for f in FORMS if not f[1]]
    n_trap = rng.choice([1, 2])
    forms = rng.sample(traps, n_trap) + rng.sample(plain, rng.randint(3, 4) - n_trap)
    rng.shuffle(forms)
    order = rng.sample(["A", "E", "V", "R"], 4)
    lines = [f"{names[k]}={vals[k]}" for k in order]
    out_lines, notes = [], []
    for tpl, trap in forms:
        shown, res = _expand(tpl, names, vals)
        lines.append(f'echo "{shown}"')
        out_lines.append(res)
        if trap:
            first = shown.split("$")[1]
            j = 0
            while j < len(first) and (first[j].isalnum() or first[j] == "_"):
                j += 1
            notes.append(f"{'в' if notes else 'В'} «{shown}» имя переменной — `{first[:j]}` (буквы, цифры и `_` идут подряд), она не "
                         f"задана и даёт пустую строку → «{res}»")
    code = "\n".join(lines)
    out = "\n".join(out_lines)
    expl = ("После `$` имя переменной продолжается, пока идут буквы, цифры и `_`; `-`, `.`, `:` его обрывают, "
            "а `${...}` задаёт границу явно. " + "; ".join(notes) + ". Остальные строки подставляются как "
            "написано. Вывод по строкам: " + " / ".join(f"«{x}»" for x in out_lines) + ".")
    stem = f"Скрипт ({ctx}) собирает из переменных имена образа и окружения и печатает их."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"forms": [t for t, _ in forms], "names": names["A"]}, language="bash")
