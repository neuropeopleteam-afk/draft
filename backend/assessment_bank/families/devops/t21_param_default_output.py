"""devops.bash.t21_param_default_output — predict_output (набор t21, порог Middle): значения по умолчанию при
раскрытии параметров bash — `${v:-d}`, `${v-d}`, `${v:=d}` для пустой и для неустановленной переменной.

Скрипт выкладки читает настройки: одна задана пустой строкой (`X=""`), другая снята (`unset Y`), третья задана
значением. Строки echo печатают раскрытия в квадратных скобках, чтобы пустая строка была видна (`[]`). Ловушки:
`:-` подставляет значение и для пустой, и для неустановленной переменной, но НЕ присваивает его; `-` (без двоеточия)
срабатывает только для неустановленной — пустая остаётся пустой; `:=` присваивает, и следующие раскрытия (даже в той
же строке, раскрытие идёт слева направо) видят новое значение; `: "${Y:=d}"` — то же присваивание без вывода. Ключ —
независимая модель состояния переменных в генераторе; проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_param_default_output"

CTX = ["выкладка биллинга", "релиз платёжного шлюза", "обновление каталога", "перезапуск поиска",
       "выкладка личного кабинета", "обновление очереди уведомлений", "релиз CRM", "миграция базы отчётов"]
# имя настройки, значение «заданной» настройки, пул значений по умолчанию
SETTINGS = [("REGION", "ru-2", ["eu-1", "us-3", "ap-1", "ru-1"]),
            ("TIMEOUT", "20", ["30", "45", "60", "90"]),
            ("REPLICAS", "4", ["1", "2", "3", "6"]),
            ("LOG_LEVEL", "warn", ["info", "debug", "error"]),
            ("PORT", "8443", ["8080", "8000", "9090"]),
            ("TAG", "v7", ["latest", "stable", "v1"]),
            ("CHANNEL", "beta", ["stable", "edge", "nightly"]),
            ("POOL", "16", ["8", "10", "32"])]
OPS = [":-", "-", ":=", "$"]
STATE_RU = {None: "не установлена", "": "пустая"}


def _expand(state: dict, var: str, op: str, d: str) -> tuple[str, str]:
    """Возвращает (результат раскрытия, пояснение); меняет state для :=."""
    cur = state[var]
    if op == "$":
        return ("" if cur is None else cur), f"${var} — текущее значение"
    if op == ":-":
        if cur is None or cur == "":
            return d, f"«:-»: {var} {STATE_RU[cur]} — подставляется {d}, но не присваивается"
        return cur, f"«:-»: {var} задана — её значение"
    if op == "-":
        if cur is None:
            return d, f"«-»: {var} не установлена — подставляется {d}"
        if cur == "":
            return "", f"«-» без двоеточия: {var} установлена, хоть и пустая — пустая строка"
        return cur, f"«-»: {var} задана — её значение"
    # :=
    if cur is None or cur == "":
        state[var] = d
        return d, f"«:=»: {var} {STATE_RU[cur]} — ей присваивается {d}"
    return cur, f"«:=»: {var} задана — значение не меняется"


def _show(var: str, op: str, d: str) -> str:
    return f"${var}" if op == "$" else f"${{{var}{op}{d}}}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    for _ in range(500):
        chosen = rng.sample(SETTINGS, 3)
        states = [""] + [None] + ["set"]
        rng.shuffle(states)
        init = {}
        for (name, val, _pool), st in zip(chosen, states):
            init[name] = val if st == "set" else st
        names = [c[0] for c in chosen]
        pools = {c[0]: c[2] for c in chosen}
        n_lines = rng.choice([3, 3, 4])
        lines_exp = [[(rng.choice(names), rng.choice(OPS)) for _ in range(2)] for _ in range(n_lines)]
        colon_at = rng.randint(0, n_lines - 1) if rng.random() < 0.4 else None
        colon_var = rng.choice([n for n in names if init[n] in (None, "")]) if colon_at is not None else None
        # раскрытие по порядку + проверки содержательности
        state = dict(init)
        outs, trace, code_body, flat = [], [], [], []
        ok_dash_empty, assign_seen, used_after_assign = False, set(), False
        soft = set()        # переменные, к которым применили «:-» при пустом / неустановленном значении
        soft_shown = False  # после такого «:-» переменная показана снова и всё ещё пустая / не установлена
        for li, pair in enumerate(lines_exp):
            if colon_at == li:
                d = rng.choice(pools[colon_var])
                if state[colon_var] in (None, ""):
                    assign_seen.add(colon_var)
                _res, note = _expand(state, colon_var, ":=", d)
                code_body.append(f': "${{{colon_var}:={d}}}"')
                trace.append(f': "${{{colon_var}:={d}}}" — {note}, вывода нет')
            parts, shown = [], []
            for var, op in pair:
                d = rng.choice(pools[var])
                if var in assign_seen:
                    used_after_assign = True
                before = state[var]
                if var in soft and op in ("$", "-") and before in (None, ""):
                    soft_shown = True
                if op == ":-" and before in (None, ""):
                    soft.add(var)
                res, note = _expand(state, var, op, d)
                if op == "-" and before == "":
                    ok_dash_empty = True
                if op == ":=" and before in (None, ""):
                    assign_seen.add(var)
                parts.append(f"[{res}]")
                shown.append(_show(var, op, d))
                flat.append((var, op))
                trace.append(f"{_show(var, op, d)} → [{res}] ({note})")
            code_body.append('echo "' + " ".join(f"[{s}]" for s in shown) + '"')
            outs.append(" ".join(parts))
        ops_used = {op for _v, op in flat}
        set_name = names[states.index("set")]
        if not {":-", "-", ":="} <= ops_used:
            continue
        if not (ok_dash_empty and assign_seen and used_after_assign):
            continue
        if not 1 <= sum(1 for v, _o in flat if v == set_name) <= 2:
            continue
        if not soft_shown:
            continue
        if any(a == b for a, b in lines_exp):
            continue
        if sum(1 for _v, op in flat if op == "$") > 2:
            continue
        if len(set(outs)) < len(outs) - 1:
            continue
        break
    else:
        raise RuntimeError("t21_param_default: не собран вариант")
    decl = []
    for (name, val, _pool), st in zip(chosen, states):
        decl.append(f'{name}=""' if st == "" else (f"unset {name}" if st is None else f"{name}={val}"))
    code = "\n".join(decl + code_body)
    out = "\n".join(outs)
    expl = ("Раскрытия выполняются по порядку, слева направо: " + "; ".join(trace) + ". Ловушки: «:-» не присваивает "
            "значение, «-» без двоеточия не срабатывает для пустой строки, «:=» присваивает, и дальше переменная "
            "уже задана. Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = f"Скрипт ({ctx}) читает настройки и подставляет для них значения по умолчанию."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"init": {k: v for k, v in init.items()}, "lines": [[list(p) for p in pr]
                                                                                  for pr in lines_exp]},
                          language="bash")
