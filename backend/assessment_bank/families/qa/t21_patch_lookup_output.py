"""qa.mock.t21_patch_lookup_output — predict_output (набор t21, порог Senior): подмена зависимости «не там, где
ищут» — mock.patch.object на исходном модуле против модуля, который взял ссылку при импорте.

Модули показаны объектами SimpleNamespace: модуль-источник держит функцию, модуль-потребитель при «импорте»
скопировал ссылку на неё (как `from src import fn`), вторая функция обращается через модуль-источник (как
`import src; src.fn(...)`). Тест подменяет атрибут через `mock.patch.object` и печатает результаты обеих функций до,
внутри и после каждой подмены. Ловушки: подмена атрибута источника не видна потребителю (у него своя ссылка),
подмена атрибута потребителя не видна прямому вызову; после выхода из with атрибут восстанавливается. Вариант
«импорт внутри подмены»: потребитель создан, пока источник подменён, — он навсегда держит подделку, а patch на нём
при выходе восстанавливает именно её. Ключ — независимая модель привязок в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.mock.t21_patch_lookup_output"

# (сюжет, источник, функция, параметр, справочник, потребитель, функция потребителя, прямая функция,
#  аргумент (имя, значения), формула)
DOMAINS = [
    ("отчёт о выручке в рублях", "rates", "get_rate", "cur", {"USD": 90, "EUR": 100, "CNY": 12},
     "report", "total", "billing_total", ("amount", [2, 3, 4, 5, 6, 7]), "{a} * {call}"),
    ("остаток квоты тарифа", "config", "get_limit", "plan", {"free": 3, "team": 20, "pro": 10},
     "quota", "left", "admin_left", ("used", [1, 2, 3]), "{call} - {a}"),
    ("цена корзины со скидкой", "pricing", "discount", "code", {"SALE": 15, "VIP": 30, "NEW": 5},
     "cart", "price", "checkout_price", ("base", [100, 120, 150, 200, 250, 300]), "{a} - {call}"),
    ("НДС в счёте", "tax", "rate", "region", {"msk": 20, "spb": 18, "kzn": 10},
     "invoice", "vat", "audit_vat", ("amount", [200, 300, 400, 500, 700, 900]), "{a} * {call} // 100"),
    ("дедлайн запроса клиента", "settings", "timeout", "env", {"dev": 5, "stage": 30, "prod": 60},
     "client", "deadline", "probe_deadline", ("start", [100, 120, 150, 180, 200]), "{a} + {call}"),
]
FAKES = [0, 1, 2, 4, 7, 50, 99]


def _calc(formula: str, a: int, v: int) -> int:
    if formula == "{a} * {call}":
        return a * v
    if formula == "{call} - {a}":
        return v - a
    if formula == "{a} - {call}":
        return a - v
    if formula == "{a} * {call} // 100":
        return a * v // 100
    return a + v


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, src, fn, prm, table, cons, cfn, dfn, (aname, avals), formula = rng.choice(DOMAINS)
    key = rng.choice(sorted(table))
    a = rng.choice(avals)
    k1, k2 = rng.sample([k for k in FAKES if k != table[key]], 2)
    mode = rng.choice(["early", "early", "late"])
    order = rng.choice([[src, cons], [cons, src]]) if mode == "early" else [src, cons]
    fake = {src: k1, cons: k2}
    mapping = "{" + ", ".join(f'"{k}": {v}' for k, v in table.items()) + "}"
    call_c, call_d = f"{cons}.{fn}({prm})", f"{src}.{fn}({prm})"
    pr = f'    print({cfn}({a}, "{key}"), {dfn}({a}, "{key}"))'
    lines = ["from types import SimpleNamespace", "from unittest import mock", "",
             f"def {fn}({prm}):", f"    return {mapping}[{prm}]", "",
             f"{src} = SimpleNamespace({fn}={fn})"]
    if mode == "early":
        lines.append(f"{cons} = SimpleNamespace({fn}={src}.{fn})")
    lines += ["", f"def {cfn}({aname}, {prm}):", f"    return {formula.format(a=aname, call=call_c)}",
              f"def {dfn}({aname}, {prm}):", f"    return {formula.format(a=aname, call=call_d)}", ""]
    # модель: что лежит в атрибутах источника и потребителя ("real" или число подделки)
    attr = {src: "real", cons: "real" if mode == "early" else None}
    val = lambda x: table[key] if x == "real" else x  # noqa: E731
    outs, trace = [], []

    def snap(where: str):
        c, d = _calc(formula, a, val(attr[cons])), _calc(formula, a, val(attr[src]))
        outs.append(f"{c} {d}")
        who = lambda x: "настоящую" if x == "real" else f"подделку ({x})"  # noqa: E731
        trace.append(f"{where}: {cfn} берёт {cons}.{fn} — {who(attr[cons])}, {dfn} берёт {src}.{fn} — "
                     f"{who(attr[src])} → «{c} {d}»")

    if mode == "early":
        lines.append(pr[4:])
        snap("до подмен")
    for i, tgt in enumerate(order):
        lines.append(f'with mock.patch.object({tgt}, "{fn}", lambda {prm}: {fake[tgt]}):')
        saved = attr[tgt]
        attr[tgt] = fake[tgt]
        if mode == "late" and i == 0:
            lines.append(f"    {cons} = SimpleNamespace({fn}={src}.{fn})")
            attr[cons] = attr[src]
        lines.append(pr)
        snap(f"внутри patch {tgt}.{fn}" + (f" ({cons} создан внутри и скопировал подделку)"
                                           if mode == "late" and i == 0 else ""))
        attr[tgt] = saved
        if mode == "late":
            lines.append(pr[4:])
            snap(f"после выхода из patch {tgt}.{fn} (восстановлено значение на входе)")
    if mode == "early":
        lines.append(pr[4:])
        snap("после обеих подмен (атрибуты восстановлены)")
    code = "\n".join(lines)
    out = "\n".join(outs)
    expl = (f"{cons} = SimpleNamespace({fn}={src}.{fn}) копирует ссылку на функцию в момент выполнения строки, как "
            f"from-импорт; mock.patch.object меняет атрибут только у указанного объекта и при выходе из with "
            f"возвращает значение, которое было на входе. " + "; ".join(trace)[:1].upper() + "; ".join(trace)[1:]
            + ".")
    stem = (f"Автотест ({plot}): модули показаны объектами SimpleNamespace, тест подменяет зависимость {fn} через "
            f"mock.patch.object.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"mode": mode, "order": order, "key": key, "a": a, "fakes": [k1, k2]},
                          language="python")
