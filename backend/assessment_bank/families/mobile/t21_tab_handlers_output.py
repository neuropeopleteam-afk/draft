"""mobile.ui.t21_tab_handlers_output — predict_output (набор t21, порог Middle): обработчики нажатий на вкладки
нижней панели, созданные в цикле — var и let в замыканиях.

React Native-экран создаёт в циклах обработчики нажатия и долгого нажатия для вкладок нижней панели: один цикл со
счётчиком `var`, другой — с `let`; затем вызываются два обработчика. Неочевидная семантика: `var` — одна
переменная на всю функцию, все замыкания видят её значение после цикла (при `i < tabs.length` это длина массива и
`tabs[i]` — undefined; при `i < tabs.length - 1` — индекс последней вкладки); `let` в заголовке for и `const` в теле
цикла создают новую привязку на каждой итерации. Ключ — независимая модель в генераторе; проверка — исполнение
показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.ui.t21_tab_handlers_output"

CTX = [("приложение доставки", ["home", "search", "orders", "cart", "profile"]),
       ("банковское приложение", ["main", "payments", "cards", "chat", "more"]),
       ("приложение кинотеатра", ["afisha", "cinemas", "tickets", "bonus", "account"]),
       ("приложение фитнес-клуба", ["today", "classes", "trainers", "shop", "me"]),
       ("приложение новостей", ["feed", "topics", "saved", "video", "settings"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    n = rng.randint(3, 5)
    tabs = pool[:n]
    skip_last = rng.random() < 0.4          # var-цикл до length - 1 (последняя вкладка — кнопка «+»)
    with_const = rng.random() < 0.5         # в var-цикле имя берётся в const внутри тела
    templ = rng.random() < 0.5              # шаблонная строка или конкатенация
    var_first = rng.random() < 0.5
    sep = rng.choice(["#", ":", "/"])
    a_name, b_name = rng.choice([("onPress", "onLongPress"), ("tapHandlers", "holdHandlers"),
                                 ("openTab", "previewTab")])
    var_bound = "tabs.length - 1" if skip_last else "tabs.length"
    var_n = n - 1 if skip_last else n
    i_final = var_n

    def body(idx: str, label: str) -> str:
        return f"`${{{label}}}{sep}${{{idx}}}`" if templ else f"{label} + '{sep}' + {idx}"

    var_loop = [f"const {a_name} = [];", f"for (var i = 0; i < {var_bound}; i++) {{"]
    if with_const:
        var_loop += ["  const name = tabs[i];", f"  {a_name}.push(() => {body('i', 'name')});"]
    else:
        var_loop += [f"  {a_name}.push(() => {body('i', 'tabs[i]')});"]
    var_loop.append("}")
    let_loop = [f"const {b_name} = [];", "for (let j = 0; j < tabs.length; j++) {",
                f"  {b_name}.push(() => {body('j', 'tabs[j]')});", "}"]
    k_var = rng.randrange(var_n)
    k_let = rng.randrange(n)
    lines = [f"const tabs = [{', '.join(repr(t) for t in tabs)}];"]
    lines += (var_loop + let_loop) if var_first else (let_loop + var_loop)
    lines += [f"console.log({a_name}[{k_var}]());", f"console.log({b_name}[{k_let}]());"]
    code = "\n".join(lines)
    var_label = tabs[k_var] if with_const else (tabs[i_final] if i_final < n else "undefined")
    out_var = f"{var_label}{sep}{i_final}"
    out_let = f"{tabs[k_let]}{sep}{k_let}"
    out = f"{out_var}\n{out_let}"
    if with_const:
        why = (f"name объявлена через const внутри тела — своя на каждой итерации, поэтому {a_name}[{k_var}] видит "
               f"'{tabs[k_var]}', а i — общая var-переменная, после цикла она равна {i_final}")
    elif i_final < n:
        why = (f"i — одна var-переменная на все замыкания; цикл остановился при i = {i_final} "
               f"({var_bound} = {var_n}), поэтому tabs[i] — последняя вкладка '{tabs[i_final]}'")
    else:
        why = (f"i — одна var-переменная на все замыкания; после цикла i = {i_final}, а tabs[{i_final}] за "
               f"пределами массива — undefined")
    expl = (f"Замыкания вызываются после циклов. {why}: «{out_var}». В цикле с let у каждой итерации своя j, "
            f"{b_name}[{k_let}] видит j = {k_let}: «{out_let}».")
    stem = (f"Нижняя панель вкладок React Native-приложения ({ctx}): обработчики нажатий создаются в циклах и "
            f"вызываются позже, когда пользователь нажимает на вкладку.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"tabs": tabs, "skip_last": skip_last, "with_const": with_const, "k": [k_var, k_let]},
                          language="javascript")
