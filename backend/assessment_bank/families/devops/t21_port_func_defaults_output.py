"""devops.net.t21_port_func_defaults_output — predict_output (набор t21, порог Стажёра): простая функция с
параметрами по умолчанию, позиционные и именованные аргументы в Python.

Функция выдаёт порт экземпляру сервиса: `base + step * index`. Её вызывают три раза разными способами. Ловушки
чтения: второй позиционный аргумент попадает в `base`, а не в `step`; именованный аргумент меняет только свой
параметр (порядок именованных не важен); умножение выполняется раньше сложения. Ключ — независимый расчёт в
генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.net.t21_port_func_defaults_output"

CTX = ["экспортёры метрик", "воркеры очереди", "реплики API", "агенты сбора логов", "узлы кэша",
       "шлюзы вебхуков", "инстансы поиска"]
FUNCS = [("port_for", "index"), ("node_port", "n"), ("metrics_port", "replica"), ("listen_port", "slot")]
BASES = [8000, 9000, 9100, 3000, 5000, 7000, 8080]
STEPS = [10, 100, 5, 20, 2]
CALLS = ["pos1", "pos2", "kw_step", "kw_base", "kw_both", "pos3"]


def _call(form, fn, i, b2, s2):
    """(текст вызова, base, step)."""
    if form == "pos1":
        return f"{fn}({i})", None, None
    if form == "pos2":
        return f"{fn}({i}, {b2})", b2, None
    if form == "kw_step":
        return f"{fn}({i}, step={s2})", None, s2
    if form == "kw_base":
        return f"{fn}({i}, base={b2})", b2, None
    if form == "kw_both":
        return f"{fn}({i}, step={s2}, base={b2})", b2, s2
    return f"{fn}({i}, {b2}, {s2})", b2, s2


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn, iv = rng.choice(FUNCS)
    base = rng.choice(BASES)
    step = rng.choice(STEPS)
    forms = ["pos2", rng.choice(["kw_step", "kw_both"])] + rng.sample(["pos1", "kw_base", "pos3"], 1)
    rng.shuffle(forms)
    lines = [f"def {fn}({iv}, base={base}, step={step}):",
             f"    return base + step * {iv}",
             ""]
    out_lines, notes = [], []
    for form in forms:
        i = rng.randint(1, 9)
        b2 = rng.choice([b for b in BASES if b != base])
        s2 = rng.choice([s for s in STEPS if s != step])
        text, bb, ss = _call(form, fn, i, b2, s2)
        b_eff = base if bb is None else bb
        s_eff = step if ss is None else ss
        res = b_eff + s_eff * i
        lines.append(f"print({text})")
        out_lines.append(str(res))
        notes.append(f"{text}: base = {b_eff}, step = {s_eff} → {b_eff} + {s_eff} × {i} = {res}")
    code = "\n".join(lines)
    out = "\n".join(out_lines)
    expl = ("Позиционные аргументы заполняют параметры по порядку (второй — это base), именованные меняют только "
            "свой параметр, остальные берутся по умолчанию; умножение раньше сложения. " + "; ".join(notes) + ".")
    stem = f"Функция выдаёт номер порта каждому экземпляру ({ctx}); её вызывают с разными аргументами."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"forms": forms, "base": base, "step": step}, language="python")
