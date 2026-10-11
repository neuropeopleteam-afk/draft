"""analyst.api.breaking_change_mcq — mcq_concept: обратная совместимость изменения контракта API.

Показан действующий контракт метода (поля запроса с типами, обязательностью, перечислениями и значениями по
умолчанию; поля ответа с типами и единицами). Клиенты разных версий (мобильные приложения обновляются
месяцами) вызывают метод по контракту и игнорируют незнакомые поля ответа. Подтипы вопроса:
  * breaking — какое из четырёх изменений сломает часть уже работающих клиентов (одно ломает, три — нет);
  * safe — какое изменение можно выпустить в той же версии API (одно безопасно, три ломают, среди них
    всегда хотя бы одно «смысловое» — единицы измерения или значение по умолчанию при том же типе).
Ключ проверяется исполнением: модель на Python перебирает все запросы, которые мог слать старый клиент
(обязательные поля, любые наборы необязательных, все значения перечислений, границы чисел), и проверяет,
что новый контракт их принимает с тем же смыслом, а все поля ответа, которые читает старый клиент, остались
с тем же типом и единицами.
"""
from __future__ import annotations

import copy

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, py_literal_block

FAMILY_ID = "analyst.api.breaking_change_mcq"

# (контекст, путь, поле-идентификатор, целое поле (имя, максимум), перечисление (имя, значения),
#  необязательная строка, статус ответа (имя, значения), величина ответа (имя, единица, другая единица))
CTX = [("заказ в интернет-магазине", "orders", "customer_id", ("quantity", 50),
        ("delivery", ["courier", "pickup", "post"]), "comment", ("status", ["new", "paid"]),
        ("total", "копейках", "рублях")),
       ("бронирование переговорной", "bookings", "room_id", ("attendees", 20),
        ("layout", ["table", "theatre", "classroom"]), "purpose", ("state", ["held", "confirmed"]),
        ("duration", "минутах", "часах")),
       ("отправление в службе доставки", "shipments", "sender_id", ("parcels", 10),
        ("service", ["standard", "express", "economy"]), "note", ("status", ["created", "accepted"]),
        ("weight", "граммах", "килограммах")),
       ("заявка на кредит", "loan-applications", "client_id", ("term_months", 60),
        ("product", ["cash", "car", "refinance"]), "employer", ("decision", ["pending", "approved"]),
        ("amount", "копейках", "рублях")),
       ("поездка в такси", "rides", "passenger_id", ("seats", 4),
        ("tariff", ["economy", "comfort", "business"]), "entrance", ("status", ["searching", "assigned"]),
        ("distance", "метрах", "километрах")),
       ("запись на приём", "appointments", "patient_id", ("visit_no", 30),
        ("channel", ["clinic", "video", "home"]), "complaint", ("status", ["booked", "confirmed"]),
        ("wait_time", "секундах", "минутах")),
       ("тренировка в фитнес-приложении", "workouts", "user_id", ("laps", 100),
        ("kind", ["run", "bike", "swim"]), "title", ("status", ["planned", "done"]),
        ("calories", "килокалориях", "калориях")),
       ("возврат товара", "returns", "order_id", ("items_count", 30),
        ("reason", ["defect", "size", "other"]), "details", ("status", ["requested", "approved"]),
        ("refund", "копейках", "рублях"))]

STRUCT_BREAK = ["remove_resp", "rename_resp", "type_resp", "opt_to_req", "add_req_required", "narrow_enum",
                "lower_max"]
SEMANTIC_BREAK = ["unit_resp", "default"]
SAFE = ["add_resp", "add_req_optional", "req_to_opt", "widen_enum", "raise_max", "add_endpoint"]

PARSE = r'''
import re
OLD = {"req": {}, "resp": {}, "endpoints": []}
sec = None
for l in CONTRACT.strip().splitlines():
    if l.startswith("POST "):
        OLD["endpoints"].append(l.strip())
        continue
    if l.startswith("Есть также "):
        OLD["endpoints"].append(l[len("Есть также "):].split(" — ")[0])
        continue
    if l.startswith("Запрос"):
        sec = "req"
        continue
    if l.startswith("Ответ"):
        sec = "resp"
        continue
    name, spec = l.strip().split(": ", 1)
    if sec == "req":
        required = spec.endswith("обязательное") and "необязательное" not in spec
        m = re.match(r"integer от 1 до (\d+)", spec)
        if spec.startswith("одно из "):
            vals = spec[len("одно из "):].split(";")[0].split(", ")
            f = {"type": "enum", "required": required, "enum": vals, "default": spec.split("по умолчанию ")[1],
                 "max": None}
        elif m:
            f = {"type": "integer", "required": required, "enum": None, "default": None, "max": int(m.group(1))}
        else:
            f = {"type": "string", "required": required, "enum": None, "default": None, "max": None}
        OLD["req"][name] = f
    else:
        if spec.startswith("одно из "):
            f = {"type": "enum", "unit": None}
        elif spec.startswith("integer, в "):
            f = {"type": "integer", "unit": spec[len("integer, в "):]}
        elif "ISO 8601" in spec:
            f = {"type": "string", "unit": "ISO 8601"}
        else:
            f = {"type": spec, "unit": None}
        OLD["resp"][name] = f
'''

MODEL = r'''
import copy, itertools

def apply(c, op):
    c = copy.deepcopy(c)
    k = op[0]
    if k == "remove_resp":
        del c["resp"][op[1]]
    elif k == "rename_resp":
        c["resp"][op[2]] = c["resp"].pop(op[1])
    elif k == "type_resp":
        c["resp"][op[1]] = dict(c["resp"][op[1]], type=op[2])
    elif k == "unit_resp":
        c["resp"][op[1]] = dict(c["resp"][op[1]], unit=op[2])
    elif k == "add_resp":
        c["resp"][op[1]] = {"type": "string", "unit": None}
    elif k == "opt_to_req":
        c["req"][op[1]]["required"] = True
    elif k == "req_to_opt":
        c["req"][op[1]]["required"] = False
        c["req"][op[1]]["default"] = op[2]
    elif k == "add_req":
        c["req"][op[1]] = {"type": "string", "required": op[2], "enum": None, "default": op[3], "max": None}
    elif k == "narrow_enum":
        c["req"][op[1]]["enum"] = [v for v in c["req"][op[1]]["enum"] if v != op[2]]
    elif k == "widen_enum":
        c["req"][op[1]]["enum"] = c["req"][op[1]]["enum"] + [op[2]]
    elif k == "default":
        c["req"][op[1]]["default"] = op[2]
    elif k == "max":
        c["req"][op[1]]["max"] = op[2]
    elif k == "add_endpoint":
        c["endpoints"] = c["endpoints"] + [op[1]]
    return c

def values(f):
    if f["enum"]:
        return list(f["enum"])
    if f["type"] == "integer":
        return [1, f["max"]]
    return ["x"]

def old_requests(c):
    req = [n for n, f in c["req"].items() if f["required"]]
    opt = [n for n, f in c["req"].items() if not f["required"]]
    for r in range(len(opt) + 1):
        for sub in itertools.combinations(opt, r):
            names = req + list(sub)
            for vals in itertools.product(*[values(c["req"][n]) for n in names]):
                yield dict(zip(names, vals))

def accepts(c, p):
    for n, f in c["req"].items():
        if f["required"] and n not in p:
            return False
        if n in p:
            v = p[n]
            if f["enum"] and v not in f["enum"]:
                return False
            if f["type"] == "integer" and f["max"] is not None and v > f["max"]:
                return False
    return True

def effective(c, p, names):
    return {n: p.get(n, c["req"][n]["default"]) for n in names}

def compatible(old, new):
    if not set(old["endpoints"]) <= set(new["endpoints"]):
        return False
    for n, f in old["resp"].items():
        if new["resp"].get(n) != f:
            return False
    names = list(old["req"])
    for p in old_requests(old):
        if not accepts(new, p) or effective(new, p, names) != effective(old, p, names):
            return False
        for n, f in new["req"].items():
            if n not in old["req"] and n not in p and f["required"]:
                return False
    return True

hits = [k for k, op in OPS.items() if compatible(OLD, apply(OLD, op)) == (MODE == "safe")]
print(hits[0] if len(hits) == 1 else "AMBIGUOUS")
'''


def _contract(ctx):
    _, path, idf, (intf, mx), (enf, vals), optf, (stf, stv), (qf, unit, _) = ctx
    return {"req": {idf: {"type": "string", "required": True, "enum": None, "default": None, "max": None},
                    intf: {"type": "integer", "required": True, "enum": None, "default": None, "max": mx},
                    enf: {"type": "enum", "required": False, "enum": list(vals), "default": vals[0], "max": None},
                    optf: {"type": "string", "required": False, "enum": None, "default": None, "max": None}},
            "resp": {"id": {"type": "string", "unit": None},
                     stf: {"type": "enum", "unit": None},
                     qf: {"type": "integer", "unit": unit},
                     "created_at": {"type": "string", "unit": "ISO 8601"}},
            "endpoints": [f"POST /v1/{path}", f"GET /v1/{path}/{{id}}"]}


def _render(ctx, c):
    _, path, idf, (intf, mx), (enf, vals), optf, (stf, stv), (qf, unit, _) = ctx
    lines = [f"POST /v1/{path}", "Запрос (JSON):",
             f"  {idf}: string, обязательное",
             f"  {intf}: integer от 1 до {mx}, обязательное",
             f"  {enf}: одно из {', '.join(vals)}; необязательное, по умолчанию {vals[0]}",
             f"  {optf}: string, необязательное",
             "Ответ 201 (JSON):",
             "  id: string",
             f"  {stf}: одно из {', '.join(stv)}",
             f"  {qf}: integer, в {unit}",
             "  created_at: string, дата-время ISO 8601",
             f"Есть также GET /v1/{path}/{{id}} — тот же объект, что в ответе 201."]
    return "\n".join(lines)


def _op(rng, kind, ctx):
    _, path, idf, (intf, mx), (enf, vals), optf, (stf, stv), (qf, unit, unit2) = ctx
    if kind == "remove_resp":
        return ("remove_resp", stf), (f"Убрать из ответа поле `{stf}` — статус можно получить через "
                                      f"GET /v1/{path}/{{id}}")
    if kind == "rename_resp":
        return ("rename_resp", qf, qf + "_value"), (f"Переименовать в ответе поле `{qf}` в `{qf}_value` — "
                                                     f"значение и тип прежние")
    if kind == "type_resp":
        return ("type_resp", "created_at", "integer"), ("Отдавать в ответе `created_at` числом — секундами "
                                                        "Unix вместо строки ISO 8601")
    if kind == "opt_to_req":
        return ("opt_to_req", optf), f"Сделать поле запроса `{optf}` обязательным — без него заявки неполные"
    if kind == "add_req_required":
        return ("add_req", "source", True, None), ("Добавить в запрос обязательное поле `source` — канал, из "
                                                   "которого пришёл вызов")
    if kind == "narrow_enum":
        v = vals[-1]
        return ("narrow_enum", enf, v), f"Убрать из допустимых значений `{enf}` значение `{v}` — его выбирают редко"
    if kind == "lower_max":
        m2 = max(2, mx // 2)
        return ("max", intf, m2), f"Снизить максимум `{intf}` в запросе с {mx} до {m2} по новому правилу"
    if kind == "unit_resp":
        return ("unit_resp", qf, unit2), (f"Отдавать `{qf}` в {unit2} вместо {unit} — тип integer и имя поля "
                                          f"те же")
    if kind == "default":
        return ("default", enf, vals[1]), (f"Сменить значение `{enf}` по умолчанию с `{vals[0]}` на "
                                           f"`{vals[1]}` — его выбирают чаще")
    if kind == "add_resp":
        return ("add_resp", "updated_at"), "Добавить в ответ поле `updated_at` (string, дата-время ISO 8601)"
    if kind == "add_req_optional":
        return ("add_req", "promo_code", False, None), ("Добавить в запрос необязательное поле `promo_code`; "
                                                        "без него всё работает как раньше")
    if kind == "req_to_opt":
        return ("req_to_opt", intf, 1), f"Сделать поле запроса `{intf}` необязательным, по умолчанию 1"
    if kind == "widen_enum":
        return ("widen_enum", enf, "other"), f"Разрешить в `{enf}` новое значение `other`"
    if kind == "raise_max":
        return ("max", intf, mx * 2), f"Повысить максимум `{intf}` в запросе с {mx} до {mx * 2}"
    return ("add_endpoint", f"GET /v1/{path}/{{id}}/history"), (f"Добавить новый метод GET /v1/{path}/{{id}}/history "
                                                                 f"— история изменений")


WHY = {"remove_resp": "клиенты читают это поле из ответа 201 — у них его не станет",
       "rename_resp": "старые клиенты ищут поле под прежним именем — для них оно пропало",
       "type_resp": "клиенты разбирают created_at как строку даты — число сломает разбор",
       "opt_to_req": "старые клиенты не всегда шлют это поле — их запросы начнут отклоняться",
       "add_req_required": "старые клиенты не знают о новом поле — все их запросы начнут отклоняться",
       "narrow_enum": "клиенты, которые шлют это значение, получат ошибку",
       "lower_max": "запросы со значениями выше нового максимума, допустимые раньше, начнут отклоняться",
       "unit_resp": "тип тот же, но смысл другой: старый клиент покажет величину в прежних единицах — в разы "
                    "неверно, и ошибки разбора не будет",
       "default": "клиенты, которые не передают поле, молча получат другое поведение",
       "add_resp": "незнакомое поле ответа клиенты игнорируют",
       "add_req_optional": "старые клиенты его не шлют, а без него поведение прежнее",
       "req_to_opt": "старые клиенты по-прежнему шлют поле — для них ничего не меняется",
       "widen_enum": "это значение запроса шлют только новые клиенты; старые значения принимаются",
       "raise_max": "все прежние значения по-прежнему допустимы",
       "add_endpoint": "существующие методы не меняются"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    mode = "breaking" if seed % 2 else "safe"
    old = _contract(ctx)
    if mode == "breaking":
        key_kind = rng.choice(STRUCT_BREAK + SEMANTIC_BREAK)
        dist_kinds = rng.sample(SAFE, 3)
        q = "Какое из изменений сломает часть уже работающих клиентов?"
    else:
        key_kind = rng.choice(SAFE)
        dist_kinds = [rng.choice(SEMANTIC_BREAK)] + rng.sample(STRUCT_BREAK, 2)
        q = "Какое из изменений можно выпустить в той же версии v1, не сломав ни одного работающего клиента?"
    key_op, key_text = _op(rng, key_kind, ctx)
    dist = [_op(rng, k, ctx) for k in dist_kinds]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (key_text, None), [(t, None) for _, t in dist])
    text2op = {key_text: key_op, **{t: o for o, t in dist}}
    text2kind = {key_text: key_kind, **{_op(rng, k, ctx)[1]: k for k in dist_kinds}}
    ops = {o.id: text2op[o.text] for o in opts}
    shown = _render(ctx, old)
    prog = (py_literal_block("CONTRACT", shown) + PARSE + f"assert OLD == {copy.deepcopy(old)!r}, 'разбор'\n"
            + f"OPS = {ops!r}\nMODE = {mode!r}\n" + MODEL)
    checks = [Check(name="compat_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=key)]
    stem = (f"Действующий контракт метода API («{ctx[0]}») показан ниже. Его вызывают клиенты разных версий, в "
            f"том числе мобильные приложения, которые пользователи обновляют месяцами. Клиенты вызывают метод "
            f"строго по контракту и игнорируют незнакомые поля ответа. {q}")
    expl = (f"Верно: «{key_text}» — {WHY[key_kind]}. Остальные: " +
            "; ".join(f"«{o.text}» — {WHY[text2kind[o.text]]}" for o in opts if o.id != key) + ".")
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=shown, options=opts, answer_key=ak,
                         context=ctx[0], verification="execution", checks=checks, language="text",
                         display_code_note=("Ответ проверяется моделью совместимости на Python: перебор запросов "
                                            "старого клиента и полей ответа, которые он читает."),
                         params={"mode": mode, "key_kind": key_kind, "dist": dist_kinds})
