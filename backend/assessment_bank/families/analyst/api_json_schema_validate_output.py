"""analyst.api.json_schema_validate_output — predict_output: какие тела запроса проходят JSON Schema контракта.

Аналитик описал тело запроса API в виде JSON Schema (подмножество: type, required, properties, minimum /
maximum, minLength / maxLength, enum, items, minItems, additionalProperties). Показаны 5 тел запроса; часть
корректна, остальные нарушают ровно одно правило (нет обязательного поля, число строкой, дробное число в
целом поле, значение вне перечисления, лишнее поле при additionalProperties: false, строка длиннее
maxLength, null в обязательном поле, пустой массив при minItems: 1, число ниже minimum). Нужно назвать
номера корректных тел. Варьируются контекст (8 сущностей), набор и ограничения полей, additionalProperties,
нарушения и их число. Ключ проверяется исполнением: программа на Python разбирает показанную схему и тела
(json.loads) и проверяет их минимальным валидатором этого подмножества.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block

FAMILY_ID = "analyst.api.json_schema_validate_output"

# поле: (имя, тип, ограничения, генератор корректного значения по rng)
CTX = {
    "создание заказа (POST /orders)": [
        ("customer_id", "string", {"minLength": 3, "maxLength": 12}, "id"),
        ("quantity", "integer", {"minimum": 1, "maximum": 50}, "int"),
        ("delivery", "string", {"enum": ["courier", "pickup", "post"]}, "enum"),
        ("items", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("comment", "string", {"maxLength": 20}, "text"),
        ("gift", "boolean", {}, "bool")],
    "регистрация пользователя (POST /users)": [
        ("login", "string", {"minLength": 4, "maxLength": 16}, "id"),
        ("age", "integer", {"minimum": 14, "maximum": 120}, "int"),
        ("role", "string", {"enum": ["student", "teacher", "admin"]}, "enum"),
        ("interests", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("about", "string", {"maxLength": 24}, "text"),
        ("newsletter", "boolean", {}, "bool")],
    "платёж (POST /payments)": [
        ("order_id", "string", {"minLength": 6, "maxLength": 20}, "id"),
        ("amount", "number", {"minimum": 1, "maximum": 500000}, "num"),
        ("currency", "string", {"enum": ["RUB", "USD", "EUR"]}, "enum"),
        ("tags", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("purpose", "string", {"maxLength": 30}, "text"),
        ("save_card", "boolean", {}, "bool")],
    "бронирование (POST /bookings)": [
        ("room_code", "string", {"minLength": 3, "maxLength": 8}, "id"),
        ("guests", "integer", {"minimum": 1, "maximum": 6}, "int"),
        ("meal", "string", {"enum": ["none", "breakfast", "full"]}, "enum"),
        ("nights", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("wishes", "string", {"maxLength": 24}, "text"),
        ("late_checkin", "boolean", {}, "bool")],
    "отзыв о товаре (POST /reviews)": [
        ("product_id", "string", {"minLength": 4, "maxLength": 10}, "id"),
        ("rating", "integer", {"minimum": 1, "maximum": 5}, "int"),
        ("source", "string", {"enum": ["app", "web", "email"]}, "enum"),
        ("photos", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("text", "string", {"maxLength": 40}, "text"),
        ("anonymous", "boolean", {}, "bool")],
    "заявка на ремонт (POST /requests)": [
        ("flat_no", "string", {"minLength": 1, "maxLength": 6}, "id"),
        ("floor", "integer", {"minimum": 1, "maximum": 40}, "int"),
        ("urgency", "string", {"enum": ["low", "normal", "high"]}, "enum"),
        ("problems", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("details", "string", {"maxLength": 30}, "text"),
        ("need_call", "boolean", {}, "bool")],
    "карточка товара (POST /products)": [
        ("sku", "string", {"minLength": 5, "maxLength": 14}, "id"),
        ("price", "number", {"minimum": 0.01, "maximum": 1000000}, "num"),
        ("unit", "string", {"enum": ["pcs", "kg", "m"]}, "enum"),
        ("barcodes", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("title", "string", {"maxLength": 28}, "text"),
        ("is_active", "boolean", {}, "bool")],
    "доставка (POST /shipments)": [
        ("tracking", "string", {"minLength": 8, "maxLength": 16}, "id"),
        ("weight_g", "integer", {"minimum": 1, "maximum": 30000}, "int"),
        ("service", "string", {"enum": ["standard", "express"]}, "enum"),
        ("parcels", "array", {"items": {"type": "string"}, "minItems": 1}, "arr"),
        ("note", "string", {"maxLength": 20}, "text"),
        ("fragile", "boolean", {}, "bool")],
}

WORDS = ["срочно", "до обеда", "звонить", "второй подъезд", "без пакета", "с упаковкой", "оставить у двери",
         "после шести"]
CHARS = "abcdefghkmnprstuvwxz0123456789"

VALIDATE = r'''
import json
SCHEMA = json.loads(SCHEMA_TEXT)
TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}
def type_ok(v, t):
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])
def check(v, s):
    if not type_ok(v, s["type"]):
        return False
    if "enum" in s and v not in s["enum"]:
        return False
    if "minimum" in s and v < s["minimum"]:
        return False
    if "maximum" in s and v > s["maximum"]:
        return False
    if "minLength" in s and len(v) < s["minLength"]:
        return False
    if "maxLength" in s and len(v) > s["maxLength"]:
        return False
    if "minItems" in s and len(v) < s["minItems"]:
        return False
    if "items" in s and not all(check(x, s["items"]) for x in v):
        return False
    if s["type"] == "object":
        props = s.get("properties", {})
        if any(k not in v for k in s.get("required", [])):
            return False
        if s.get("additionalProperties", True) is False and any(k not in props for k in v):
            return False
        if not all(check(v[k], props[k]) for k in v if k in props):
            return False
    return True
ok = [str(i) for i, b in enumerate(BODIES, 1) if check(json.loads(b), SCHEMA)]
print(" ".join(ok) if ok else "нет")
'''

VIOLATIONS = ["missing_required", "number_as_string", "fraction_in_integer", "enum", "extra_field",
              "too_long", "null_required", "empty_array", "below_minimum"]


def _value(rng, kind, cons):
    if kind == "id":
        n = rng.randint(cons.get("minLength", 1), min(cons.get("maxLength", 8), cons.get("minLength", 1) + 4))
        return "".join(rng.choice(CHARS) for _ in range(n))
    if kind == "int":
        return rng.randint(cons["minimum"], min(cons["maximum"], cons["minimum"] + 20))
    if kind == "num":
        return rng.choice([round(rng.uniform(1, 900), 2), rng.randint(2, 900)])
    if kind == "enum":
        return rng.choice(cons["enum"])
    if kind == "arr":
        return ["".join(rng.choice(CHARS) for _ in range(4)) for _ in range(rng.randint(1, 3))]
    if kind == "text":
        w = [x for x in WORDS if len(x) <= cons["maxLength"]]
        return rng.choice(w)
    return rng.choice([True, False])


def _mutate(rng, body, viol, fields, required, addl):
    """Нарушить ровно одно правило; вернуть None, если нарушение к этой схеме неприменимо."""
    b = dict(body)
    by = {f[0]: f for f in fields}
    present = [k for k in b if k in by]
    if viol == "missing_required":
        k = rng.choice(required)
        b.pop(k, None)
        return b, f"нет обязательного поля `{k}`"
    if viol == "number_as_string":
        c = [k for k in present if by[k][1] in ("integer", "number")]
        if not c:
            return None
        k = c[0]
        b[k] = str(b[k])
        return b, f"`{k}` передано строкой, а по схеме — число"
    if viol == "fraction_in_integer":
        c = [k for k in present if by[k][1] == "integer"]
        if not c:
            return None
        k = c[0]
        b[k] = b[k] + 0.5
        return b, f"`{k}` дробное, а по схеме — integer"
    if viol == "enum":
        c = [k for k in present if "enum" in by[k][2]]
        if not c:
            return None
        k = c[0]
        b[k] = by[k][2]["enum"][0].upper() if by[k][2]["enum"][0].upper() not in by[k][2]["enum"] else "other"
        return b, f"`{k}` вне перечисления enum"
    if viol == "extra_field":
        if addl:
            return None
        b["source_system"] = "crm"
        return b, "лишнее поле `source_system` при additionalProperties: false"
    if viol == "too_long":
        c = [k for k in present if "maxLength" in by[k][2]]
        if not c:
            return None
        k = rng.choice(c)
        b[k] = (str(b[k]) + "-" + "x" * by[k][2]["maxLength"])[: by[k][2]["maxLength"] + 3]
        return b, f"`{k}` длиннее maxLength = {by[k][2]['maxLength']}"
    if viol == "null_required":
        k = rng.choice(required)
        b[k] = None
        return b, f"`{k}` = null — null не {by[k][1]} (отдельный тип JSON)"
    if viol == "empty_array":
        c = [k for k in present if by[k][1] == "array"]
        if not c:
            return None
        k = c[0]
        b[k] = []
        return b, f"`{k}` — пустой массив при minItems: 1"
    c = [k for k in present if "minimum" in by[k][2]]
    if not c:
        return None
    k = c[0]
    b[k] = 0 if by[k][2]["minimum"] >= 1 else -1
    return b, f"`{k}` меньше minimum = {by[k][2]['minimum']}"


def _schema_text(schema):
    """JSON со свойствами в одну строку каждое (компактнее indent=2, разбирается json.loads)."""
    d = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    props = ",\n".join(f"    {d(k)}: {d(v)}" for k, v in schema["properties"].items())
    return ("{\n  \"type\": \"object\",\n  \"required\": " + d(schema["required"]) + ",\n  \"properties\": {\n"
            + props + "\n  },\n  \"additionalProperties\": " + d(schema["additionalProperties"]) + "\n}")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CTX))
    pool = list(CTX[ctx])
    n_fields = rng.randint(4, 6)
    fields = [pool[0], pool[1], pool[2]] + rng.sample(pool[3:], n_fields - 3)
    req_extra = [f[0] for f in fields[3:] if rng.random() < 0.4]
    required = [fields[0][0], fields[1][0]] + ([fields[2][0]] if rng.random() < 0.6 else []) + req_extra
    addl = rng.random() < 0.4
    props = {}
    for name, typ, cons, _ in fields:
        props[name] = {"type": typ, **cons}
    schema = {"type": "object", "required": required, "properties": props, "additionalProperties": addl}
    schema_text = _schema_text(schema)
    n_valid = rng.choice([1, 2, 2, 3])
    bodies, notes, valid_idx = [], [], []
    viols = list(VIOLATIONS)
    rng.shuffle(viols)
    order = [True] * n_valid + [False] * (5 - n_valid)
    rng.shuffle(order)
    for i, is_valid in enumerate(order, 1):
        body = {}
        for name, typ, cons, kind in fields:
            if name in required or rng.random() < 0.6:
                body[name] = _value(rng, kind, cons)
        if is_valid:
            if addl and rng.random() < 0.5:
                body["client_version"] = "2.4"
            bodies.append(body)
            notes.append("корректно" + (" (лишнее поле допустимо: additionalProperties: true)"
                                        if "client_version" in body else ""))
            valid_idx.append(i)
            continue
        while viols:
            v = viols.pop()
            res = _mutate(rng, body, v, fields, required, addl)
            if res:
                bodies.append(res[0])
                notes.append(res[1])
                break
        else:
            raise RuntimeError("нет нарушения")
    texts = [json.dumps(b, ensure_ascii=False) for b in bodies]
    out_s = " ".join(map(str, valid_idx))
    prog = (py_literal_block("SCHEMA_TEXT", schema_text) + f"BODIES = {texts!r}\n" + VALIDATE)
    checks = [Check(name="mini_validator", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=out_s)]
    listing = "\n".join(f"{i}. `{t}`" for i, t in enumerate(texts, 1))
    stem = (f"Аналитик описал тело запроса «{ctx}» в контракте API схемой JSON Schema (показана). Поля, не "
            f"перечисленные в required, необязательны. Какие из тел запроса ниже проходят проверку по схеме?\n\n"
            f"{listing}\n\nОтвет — номера корректных тел по возрастанию через пробел, например `1 4`.")
    ak = AnswerKey(kind="output", value=out_s,
                   explanation="; ".join(f"{i}: {n}" for i, n in enumerate(notes, 1)) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=schema_text, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         params={"n_fields": n_fields, "addl": addl, "valid": valid_idx,
                                 "violations": [n for n in notes if not n.startswith("корректно")]})
