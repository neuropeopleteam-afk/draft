"""analyst.bpmn.gateway_trace_output — predict_output: путь экземпляра процесса через исключающие шлюзы.

Процесс задан текстовой моделью (задачи с кодами, поток управления, исключающие шлюзы XOR с условиями на
данных экземпляра) — это текстовая запись BPMN-схемы. По данным экземпляра нужно назвать выполненные задачи
по порядку. Варьируются контекст, число шлюзов (3–4), пороги и их строгость, запись условия (на ветвь или на
основной путь), данные; ветви — обход с возвратом на основной путь или выход в конец. Ключ проверяется исполнением: интерпретатор на Python разбирает показанную модель дословно.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block

FAMILY_ID = "analyst.bpmn.gateway_trace_output"

INTERP = r'''
import re
lines = [l.rstrip() for l in MODEL.strip().splitlines()]
sec = None
flow, data = {}, {}
for l in lines:
    s = l.strip()
    if s in ("задачи:", "поток:"):
        sec = s
        continue
    if s.startswith("данные:"):
        for part in s[len("данные:"):].split(","):
            k, v = [x.strip() for x in part.split("=")]
            data[k] = int(v) if v.lstrip("-").isdigit() else v
        continue
    if sec == "поток:" and s:
        m = re.match(r"(\S+) \(XOR\): (.+) -> (\S+); иначе -> (\S+)$", s)
        if m:
            flow[m.group(1)] = ("xor", m.group(2), m.group(3), m.group(4))
        else:
            a, b = [x.strip() for x in s.split("->")]
            flow[a] = ("seq", b)

def holds(cond):
    var, op, val = re.match(r"(\S+) (>=|<=|>|<|=) (\S+)$", cond).groups()
    x = data[var]
    if op == "=":
        return str(x) == val
    y = int(val)
    return {">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y}[op]

node, trace, steps = "СТАРТ", [], 0
while node != "КОНЕЦ" and steps < 100:
    steps += 1
    f = flow[node]
    if f[0] == "xor":
        node = f[2] if holds(f[1]) else f[3]
    else:
        node = f[1]
    if node.startswith("T"):
        trace.append(node)
print(" ".join(trace))
'''

# побочная ветвь: (переменная, тип, диапазон порога | значение, ведущее в ветвь, задача ветви, вид, позиция:
# шлюз стоит после основной задачи с этим номером)
CTX = {
    "закупка": dict(
        main=["Зарегистрировать заявку", "Проверить бюджет", "Выбрать поставщика", "Оформить договор",
              "Оплатить счёт"],
        side=[("сумма", "num", (50000, 300000), "Согласовать с финансовым директором", "detour", 0),
              ("бюджет_есть", "bool", "нет", "Отклонить заявку", "exit", 1),
              ("поставщик_новый", "bool", "да", "Проверить поставщика службой безопасности", "detour", 2),
              ("срочно", "bool", "да", "Запросить ускоренную доставку", "detour", 3)]),
    "заказ": dict(
        main=["Принять заказ", "Проверить наличие", "Собрать заказ", "Передать в доставку", "Закрыть заказ"],
        side=[("скидка", "num", (5, 30), "Согласовать скидку с менеджером", "detour", 0),
              ("в_наличии", "bool", "нет", "Сообщить клиенту о сроке поставки", "exit", 1),
              ("вес", "num", (10, 60), "Заказать грузовое такси", "detour", 2),
              ("оплачен", "bool", "нет", "Отправить ссылку на оплату", "detour", 3)]),
    "кредит": dict(
        main=["Принять заявку", "Проверить документы", "Оценить скоринг", "Подписать договор", "Выдать кредит"],
        side=[("клиент_банка", "bool", "нет", "Провести идентификацию в отделении", "detour", 0),
              ("документы_полные", "bool", "нет", "Запросить недостающие документы", "detour", 1),
              ("скоринг", "low", (400, 800), "Отказать в кредите", "exit", 2),
              ("сумма", "num", (300000, 3000000), "Согласовать с кредитным комитетом", "detour", 3)]),
    "отпуск": dict(
        main=["Подать заявление", "Проверить остаток дней", "Согласовать с руководителем", "Издать приказ",
              "Начислить отпускные"],
        side=[("за_свой_счёт", "bool", "да", "Оформить отпуск без сохранения оплаты", "detour", 0),
              ("остаток_достаточен", "bool", "нет", "Вернуть заявление сотруднику", "exit", 1),
              ("дней", "num", (7, 28), "Согласовать с директором по персоналу", "detour", 2),
              ("пересечение_с_коллегой", "bool", "да", "Согласовать график с отделом", "detour", 3)]),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CTX))
    C = CTX[ctx]
    k = rng.choice([3, 4])
    side = sorted(rng.sample(C["side"], k), key=lambda e: e[5])
    main = C["main"]
    tasks, flow, data = [], [], {}
    code_of = {}

    def task(name):
        if name not in code_of:
            code_of[name] = f"T{len(code_of) + 1}"
            tasks.append((code_of[name], name))
        return code_of[name]
    flow.append(f"СТАРТ -> {task(main[0])}")
    prev = code_of[main[0]]
    by_pos = {e[5]: e for e in side}
    gi = 0
    for pos in range(4):
        nxt_main = None
        if pos in by_pos:
            var, typ, arg, sname, kind, _ = by_pos[pos]
            gi += 1
            g = f"G{gi}"
            flow.append(f"{prev} -> {g}")
            st = task(sname)
            nxt_main = task(main[pos + 1])
            positive = rng.random() < 0.6
            if typ in ("num", "low"):
                step = max(1, 10 ** (len(str(arg[1])) - 2))
                thr = rng.randint(arg[0] // step, arg[1] // step) * step
                data[var] = rng.choice([thr, thr + rng.randint(1, 3) * step, thr - rng.randint(1, 3) * step])
                strict = rng.random() < 0.5
                if typ == "num":  # ветвь при значении выше порога
                    cond_side, cond_main = (f"{var} > {thr}", f"{var} <= {thr}") if strict else \
                        (f"{var} >= {thr}", f"{var} < {thr}")
                else:  # ветвь при значении ниже порога
                    cond_side, cond_main = (f"{var} < {thr}", f"{var} >= {thr}") if strict else \
                        (f"{var} <= {thr}", f"{var} > {thr}")
            else:
                data[var] = rng.choice(["да", "нет"])
                other = "нет" if arg == "да" else "да"
                cond_side, cond_main = f"{var} = {arg}", f"{var} = {other}"
            if positive:
                flow.append(f"{g} (XOR): {cond_side} -> {st}; иначе -> {nxt_main}")
            else:
                flow.append(f"{g} (XOR): {cond_main} -> {nxt_main}; иначе -> {st}")
            flow.append(f"{st} -> {'КОНЕЦ' if kind == 'exit' else nxt_main}")
        else:
            nxt_main = task(main[pos + 1])
            flow.append(f"{prev} -> {nxt_main}")
        prev = nxt_main
    flow.append(f"{prev} -> КОНЕЦ")
    body = flow
    model = ("задачи:\n" + "\n".join(f"  {c}  {n}" for c, n in tasks) + "\nпоток:\n" +
             "\n".join(f"  {l}" for l in body) + "\nданные: " + ", ".join(f"{k} = {v}" for k, v in data.items()))
    ns: dict = {"MODEL": model}
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(INTERP, ns)  # noqa: S102 — тот же интерпретатор исполняется в проверке
    out = buf.getvalue().strip()
    prog = py_literal_block("MODEL", model) + INTERP
    checks = [Check(name="interpret", runner="python", program=prog, expect="stdout_equals", expected_stdout=out)]
    stem = (f"Аналитик описал процесс «{ctx}» текстовой моделью BPMN: задачи с кодами, поток управления и "
            f"исключающие шлюзы (XOR: выполняется ровно одна ветвь — первая, если условие истинно, иначе вторая). "
            f"Какие задачи выполнятся для экземпляра с указанными данными и в каком порядке? Ответ — коды задач "
            f"через пробел, например `T1 T3 T4`.")
    ak = AnswerKey(kind="output", value=out,
                   explanation=(f"Идём от СТАРТ по стрелкам; на каждом шлюзе проверяем условие по данным экземпляра. "
                                f"Путь: {out}. Задачи из невыбранных ветвей не выполняются."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=model, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         params={"gateways": k, "data": data})
