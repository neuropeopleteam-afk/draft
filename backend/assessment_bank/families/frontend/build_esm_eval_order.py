"""frontend.build.esm_eval_order — predict_output: порядок выполнения ES-модулей.

Семантика ESM для ациклического графа: объявления import всплывают (выполняются до кода
модуля, где бы ни стояли), зависимости выполняются в глубину в порядке объявлений import,
каждый модуль — один раз. Ключ считает модель в генераторе; проверка исполняет в Node.js
эквивалентную программу (модули — функции, загрузчик с кэшем), так как vm-песочница не
поддерживает import.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.build.esm_eval_order"

POOL = [("config", "config", "{ apiBase: '/api' }"), ("api", "api", "{ get: () => null }"),
        ("logger", "log", "(m) => m"), ("store", "store", "{ state: {} }"),
        ("i18n", "t", "(k) => k"), ("analytics", "track", "() => {}"),
        ("theme", "theme", "{ dark: false }"), ("router", "router", "{ routes: [] }")]
CTX = ["админ-панель", "личный кабинет", "лендинг", "дашборд аналитики", "PWA-приложение"]


def _evaluate(mods, entry):
    done, out = set(), []

    def run(m):
        if m in done:
            return
        done.add(m)
        for d in mods[m]["deps"]:
            run(d)
        out.extend(mods[m]["logs"])
    run(entry)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(200):
        chosen = rng.sample(POOL, rng.randint(3, 4))
        names = [c[0] for c in chosen]
        mods = {}
        for i, (name, exp, val) in enumerate(chosen):
            later = names[i + 1:]
            deps = rng.sample(later, min(len(later), rng.randint(0, 2)))
            mods[name] = {"deps": deps, "exp": exp, "val": val,
                          "early": bool(deps) and rng.random() < 0.45,
                          "side_only": False}
        entry_deps = rng.sample(names, rng.randint(2, min(3, len(names))))
        mods["main"] = {"deps": entry_deps, "exp": None, "val": None, "early": rng.random() < 0.7,
                        "side_only": False}
        # все модули должны быть достижимы из main
        reach, stack = set(), ["main"]
        while stack:
            m = stack.pop()
            if m in reach:
                continue
            reach.add(m)
            stack.extend(mods[m]["deps"])
        if len(reach) != len(mods):
            continue
        # хотя бы один модуль импортируют дважды или есть ранний вывод — иначе слишком просто
        imported = [d for m in mods.values() for d in m["deps"]]
        if len(imported) == len(set(imported)) and not any(m["early"] for m in mods.values()):
            continue
        break
    else:
        raise RuntimeError("не собрался граф")
    side_dep = rng.random() < 0.4
    file_order = ["main"] + rng.sample(names, len(names))
    blocks, js_mods = [], []
    for name in file_order:
        m = mods[name]
        lines, logs = [f"// {name}.js"], []
        early_txt = f"{name}: начало" if name != "main" else "main: старт"
        late_txt = name if name != "main" else "main: готово"
        if m["early"]:
            lines.append(f"console.log('{early_txt}');")
            logs.append(early_txt)
        for d in m["deps"]:
            de = mods[d]["exp"]
            if name == "main" and side_dep and d == m["deps"][-1]:
                lines.append(f"import './{d}.js';")
            else:
                lines.append(f"import {{ {de} }} from './{d}.js';")
        lines.append(f"console.log('{late_txt}');")
        logs.append(late_txt)
        if m["exp"]:
            lines.append(f"export const {m['exp']} = {m['val']};")
        m["logs"] = logs
        blocks.append("\n".join(lines))
        body = " ".join(f"console.log({json.dumps(t, ensure_ascii=False)});" for t in logs)
        js_mods.append(f"__mods[{json.dumps(name)}] = {{ deps: {json.dumps(m['deps'])}, "
                       f"run() {{ {body} }} }};")
    code = "\n\n".join(blocks)
    out = "\n".join(_evaluate(mods, "main"))
    program = ("const __mods = {};\nconst __done = new Set();\n"
               "function __load(name) {\n  if (__done.has(name)) return;\n  __done.add(name);\n"
               "  for (const d of __mods[name].deps) __load(d);\n  __mods[name].run();\n}\n" +
               "\n".join(js_mods) + "\n__load('main');\n")
    ctx = rng.choice(CTX)
    stem = (f"Приложение ({ctx}) собрано из ES-модулей; точка входа — `main.js`, циклических "
            f"импортов нет, сборщик сохраняет семантику ESM. Что будет выведено в консоль при "
            f"загрузке приложения? Запишите строки вывода по порядку.")
    ak = AnswerKey(kind="output", value=out,
                   explanation="Объявления import всплывают: все зависимости модуля выполняются "
                               "до его кода, даже если console.log стоит выше import. Обход — в "
                               "глубину в порядке объявлений import, каждый модуль выполняется "
                               "один раз, повторный импорт берёт уже выполненный модуль.")
    checks = [Check(name="stdout", runner="node", program=program, expect="stdout_equals",
                    expected_stdout=out, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="vm-песочница не исполняет import: проверка запускает "
                                           "эквивалентную программу (модуль — функция, загрузчик "
                                           "с кэшем, зависимости до кода модуля).",
                         params={"graph": {k: v["deps"] for k, v in mods.items()}})
