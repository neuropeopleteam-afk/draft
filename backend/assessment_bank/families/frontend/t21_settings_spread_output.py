"""frontend.state.t21_settings_spread_output — predict_output (набор t21, порог Junior): слияние настроек через
spread и деструктуризация с переименованием и значением по умолчанию.

Настройки интерфейса собираются из трёх источников: значения по умолчанию, сохранённые пользователем и явное
переопределение одним ключом; порядок spread в литерале меняется от варианта к варианту (переопределение стоит
до или после spread). Затем деструктуризация берёт два поля (одно с переименованием) и поле, которого нет ни в
одном источнике, со значением по умолчанию. Ловушки: побеждает последний источник ключа; явный ключ ДО spread
перезаписывается; значение по умолчанию при деструктуризации — только для отсутствующего ключа. Ключ — модель
в генераторе (словарь с последним победителем); проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.state.t21_settings_spread_output"

# (контекст, ключ -> (по умолчанию, сохранённое, переопределение)), отсутствующий ключ и его значение по умолчанию
CTX = [("настройки редактора", {"theme": ("\"light\"", "\"dark\"", "\"contrast\""), "fontSize": ("14", "16", "18"),
                                "tabSize": ("2", "4", "8")}, ("wordWrap", "true")),
       ("таблица заказов", {"pageSize": ("20", "50", "100"), "sort": ("\"date\"", "\"price\"", "\"status\""),
                            "density": ("\"normal\"", "\"compact\"", "\"loose\"")}, ("showTotals", "false")),
       ("плеер", {"volume": ("50", "80", "30"), "quality": ("\"auto\"", "\"1080p\"", "\"720p\""),
                  "speed": ("1", "1.5", "2")}, ("subtitles", "\"off\"")),
       ("карта доставки", {"zoom": ("12", "15", "10"), "layer": ("\"scheme\"", "\"satellite\"", "\"hybrid\""),
                           "units": ("\"km\"", "\"mi\"", "\"m\"")}, ("traffic", "true"))]
RENAME = {"theme": "mode", "fontSize": "size", "tabSize": "indent", "pageSize": "limit", "sort": "order",
          "density": "rows", "volume": "level", "quality": "res", "speed": "rate", "zoom": "scale",
          "layer": "view", "units": "unit"}


def _show(lit: str) -> str:
    return lit[1:-1] if lit.startswith("\"") else lit


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, (missing, miss_default) = rng.choice(CTX)
    keys = list(table)
    rng.shuffle(keys)
    # сохранённые пользователем: 1–2 ключа; переопределение: 1 ключ
    saved_keys = rng.sample(keys, rng.randint(1, 2))
    over_key = rng.choice(keys)
    defaults = {k: table[k][0] for k in keys}
    saved = {k: table[k][1] for k in saved_keys}
    over_val = table[over_key][2]
    # порядок частей литерала: варианты расположения переопределения и порядка spread
    order = rng.choice([["defaults", "saved", "over"], ["defaults", "over", "saved"], ["over", "defaults", "saved"],
                        ["saved", "defaults", "over"], ["defaults", "saved", "over"]])
    merged: dict[str, str] = {}
    src: dict[str, str] = {}
    for part in order:
        chunk = defaults if part == "defaults" else saved if part == "saved" else {over_key: over_val}
        for k, v in chunk.items():
            merged[k] = v
            src[k] = part
    names = {"defaults": "defaults", "saved": "saved"}
    lit_parts = [f"...{names[p]}" if p != "over" else f"{over_key}: {over_val}" for p in order]
    pick = rng.sample(keys, 2)
    ren = pick[1]
    alias = RENAME[ren]
    code = "\n".join([
        "const defaults = { " + ", ".join(f"{k}: {defaults[k]}" for k in keys) + " };",
        "const saved = { " + ", ".join(f"{k}: {saved[k]}" for k in saved_keys) + " };",
        "const settings = { " + ", ".join(lit_parts) + " };",
        f"const {{ {pick[0]}, {ren}: {alias}, {missing} = {miss_default} }} = settings;",
        f"console.log({pick[0]}, {alias}, {missing});",
    ])
    vals = [_show(merged[pick[0]]), _show(merged[ren]), _show(miss_default)]
    out = " ".join(vals)
    who = {"defaults": "из defaults", "saved": "из saved", "over": "явное значение в литерале"}

    def why(k: str) -> str:
        cands = [p for p in order if (p == "defaults") or (p == "saved" and k in saved) or
                 (p == "over" and k == over_key)]
        if len(cands) == 1:
            return f"{k} есть только в defaults → {_show(merged[k])}"
        return (f"{k} задан в нескольких местах ({', '.join(who[p] for p in cands)}), побеждает последний — "
                f"{who[src[k]]}: {_show(merged[k])}")
    expl = (f"В литерале {{ {', '.join(lit_parts)} }} ключи записываются слева направо, повторный ключ перезаписывает "
            f"прежнее значение. {why(pick[0])}; {why(ren)} (переименован в {alias}); ключа {missing} нет ни в одном "
            f"источнике, поэтому срабатывает значение по умолчанию {_show(miss_default)}. Вывод: «{out}».")
    stem = (f"Интерфейс ({ctx}): программа собирает итоговые настройки из значений по умолчанию, сохранённых "
            f"пользователем и явного переопределения, а затем достаёт нужные поля.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"order": order, "saved": saved_keys, "override": over_key, "pick": pick},
                          language="javascript")
