"""devops.bash.t21_local_masks_status_output — predict_output (набор t21, порог Senior): `local v=$(cmd)` и
`export V=$(cmd)` скрывают код возврата подстановки команды.

Функция получения версии печатает тег и завершается с ненулевым кодом. Три функции сохраняют результат по-разному и
печатают `$?`. Правило bash: у `local` / `declare` / `export` собственный статус (0 при успешном объявлении) — он и
попадает в `$?`, а статус `$(...)` теряется; у простого присваивания `v=$(cmd)` (в том числе после отдельного
`local v`) статус — статус подстановки. Ключ — независимая модель в генераторе; проверка — исполнение показанного
скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_local_masks_status_output"

CTX = ["выкладка биллинга", "релиз каталога", "обновление платёжного шлюза", "выкладка поиска",
       "релиз личного кабинета", "обновление CRM", "выкладка сервиса уведомлений"]
FETCH = ["fetch_tag", "get_version", "read_release", "latest_tag"]
FUNCS = ["prep", "check", "plan", "apply", "verify", "notify"]
FORMS = ["local_inline", "local_split", "global", "export_inline", "declare_inline"]


def _body(form: str, var: str, fetch: str) -> list[str]:
    if form == "local_inline":
        return [f"  local {var}=$({fetch})"]
    if form == "local_split":
        return [f"  local {var}", f"  {var}=$({fetch})"]
    if form == "global":
        return [f"  {var}=$({fetch})"]
    if form == "export_inline":
        return [f"  export {var.upper()}=$({fetch})"]
    return [f"  declare {var}=$({fetch})"]


def _why(form: str, rc: int) -> str:
    return {"local_inline": "`local v=$(...)` — в $? статус самой команды local (0)",
            "local_split": f"`local v` отдельно, затем `v=$(...)` — в $? статус подстановки ({rc})",
            "global": f"простое присваивание `v=$(...)` — в $? статус подстановки ({rc})",
            "export_inline": "`export V=$(...)` — в $? статус export (0)",
            "declare_inline": "`declare v=$(...)` — в $? статус declare (0)"}[form]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fetch = rng.choice(FETCH)
    tag = f"v{rng.randint(1, 4)}.{rng.randint(0, 19)}.{rng.randint(0, 9)}"
    rc = rng.randint(1, 9)
    for _ in range(100):
        forms = ["local_inline"] + rng.sample([f for f in FORMS if f != "local_inline"], 2)
        if any(f in ("local_split", "global") for f in forms):
            break
    rng.shuffle(forms)
    names = rng.sample(FUNCS, 3)
    vars_ = rng.sample(["tag", "ver", "rel", "out", "value"], 3)
    lines = [f'{fetch}() {{ echo "{tag}"; return {rc}; }}']
    outs, notes = [], []
    for fname, form, var in zip(names, forms, vars_):
        shown_var = var.upper() if form == "export_inline" else var
        lines.append(f"{fname}() {{")
        lines += _body(form, var, fetch)
        lines.append(f'  echo "{fname}: rc=$? {shown_var}=${shown_var}"')
        lines.append("}")
        st = 0 if form in ("local_inline", "export_inline", "declare_inline") else rc
        outs.append(f"{fname}: rc={st} {shown_var}={tag}")
        notes.append(f"{fname}: {_why(form, rc)}")
    order = names[:]
    rng.shuffle(order)
    lines.append("; ".join(order))
    by_name = dict(zip(names, outs))
    out_lines = [by_name[n] for n in order]
    code = "\n".join(lines)
    out = "\n".join(out_lines)
    expl = (f"{fetch} печатает «{tag}» и возвращает {rc}; значение переменной во всех функциях — «{tag}». "
            + "; ".join(notes) + ". Функции вызываются в порядке " + ", ".join(order) + ". Вывод по строкам: "
            + " / ".join(f"«{x}»" for x in out_lines) + ".")
    stem = (f"Скрипт ({ctx}) получает тег релиза функцией {fetch} и проверяет её код возврата в трёх "
            f"вспомогательных функциях.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"forms": forms, "rc": rc, "order": order}, language="bash")
