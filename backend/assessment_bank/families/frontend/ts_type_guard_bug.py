"""frontend.ts.type_guard_bug — find_bug: пользовательский type guard для данных из API.

Показывается TypeScript; для проверки ключа тот же код без аннотаций типов (построчное
соответствие) исполняется в Node.js на «грязном» ответе сервера.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.ts.type_guard_bug"

# (тип, guard, parse, поле-статус, значения, поле-список, тип элементов, контекст)
TYPES = [("Order", "isOrder", "parseOrders", "status", ["new", "paid", "shipped"], "items", "string", "заказы"),
         ("Ticket", "isTicket", "parseTickets", "priority", ["low", "high", "urgent"], "tags", "string", "служба поддержки"),
         ("Vacancy", "isVacancy", "parseVacancies", "grade", ["junior", "middle", "senior"], "skills", "string", "вакансии"),
         ("Message", "isMessage", "parseMessages", "state", ["sent", "delivered", "read"], "attachments", "string", "мессенджер"),
         ("Invoice", "isInvoice", "parseInvoices", "currency", ["RUB", "USD", "EUR"], "lines", "string", "счета"),
         ("Candidate", "isCandidate", "parseCandidates", "direction", ["backend", "frontend", "qa"], "badges", "string", "кандидаты")]
SYMPTOM = {
    "null_check": "если в массиве из API встречается элемент null (в последнем инциденте — "
                  "{pos}-й элемент из {total}), разбор падает с TypeError",
    "array_check": "проходят записи вида `{{\"id\": {i3}, \"{st}\": \"{v1}\", \"{lst}\": {bad}}}`, и "
                   "интерфейс падает при `.{lst}.map(...)`",
    "id_check": "проходят записи с id-строкой (например, `\"id\": \"{i1}\"`), и сравнение id в "
                "интерфейсе работает неправильно",
    "enum_check": "проходят записи с неизвестным значением `{st}` (например, `{{\"id\": {i2}, \"{st}\": \"{unk}\"}}`), и "
                  "интерфейс не может их отобразить",
}


# Калибровка 05.10: подтипы null_check выделены в frontend.ts.typeof_null_guard_bug (варианты были неизоморфны).
SUBTYPES_HERE = ('array_check', 'id_check', 'enum_check')


def _generate(seed: int, family_id: str, subtypes):
    rng = make_rng(family_id, seed)
    T, guard, parse, st, vals, lst, el, ctx = rng.choice(TYPES)
    const = rng.choice(["ALLOWED", "KNOWN_VALUES", st.upper() + "_VALUES"])
    vname = rng.choice(["v", "rec", "obj"])
    subtype = rng.choice(list(subtypes))
    lit = " | ".join(f"'{x}'" for x in vals)
    arr = ", ".join(f"'{x}'" for x in vals)
    L = {  # ключ: (TS, JS)
        "null": ("  if (typeof value !== 'object' || value === null) return false;",
                 "  if (typeof value !== 'object' || value === null) return false;"),
        "id": (f"  return typeof {vname}.id === 'number' &&", f"  return typeof {vname}.id === 'number' &&"),
        "enum": (f"    typeof {vname}.{st} === 'string' && {const}.includes({vname}.{st}) &&",
                 f"    typeof {vname}.{st} === 'string' && {const}.includes({vname}.{st}) &&"),
        "arr": (f"    Array.isArray({vname}.{lst});", f"    Array.isArray({vname}.{lst});"),
    }
    B = dict(L)
    if subtype == "null_check":
        B["null"] = ("  if (typeof value !== 'object') return false;",) * 2
    elif subtype == "id_check":
        B["id"] = (f"  return 'id' in {vname} &&",) * 2
    elif subtype == "enum_check":
        B["enum"] = (f"    typeof {vname}.{st} === 'string' &&",) * 2
    else:
        B["arr"] = (f"    typeof {vname}.{lst} === 'object';",) * 2

    def lines(g, js):
        k = 1 if js else 0
        out = [] if js else [f"interface {T} {{", "  id: number;", f"  {st}: {lit};",
                             f"  {lst}: {el}[];", "}", ""]
        out += [(f"const {const}: readonly string[] = [{arr}];" if not js else f"const {const} = [{arr}];"), "",
                (f"function {guard}(value: unknown): value is {T} {{" if not js else f"function {guard}(value) {{"),
                g["null"][k],
                (f"  const {vname} = value as Record<string, unknown>;" if not js else f"  const {vname} = value;"),
                g["id"][k], g["enum"][k], g["arr"][k], "}", "",
                (f"function {parse}(json: string): {T}[] {{" if not js else f"function {parse}(json) {{"),
                ("  const data: unknown = JSON.parse(json);" if not js else "  const data = JSON.parse(json);"),
                f"  return Array.isArray(data) ? data.filter({guard}) : [];", "}"]
        return "\n".join(out)
    buggy, fixed = lines(B, False), lines(L, False)
    # 0–2 строки нейтрального комментария сверху: номер строки дефекта не постоянен
    # (после разделения подтипов у typeof null ключ иначе был бы одним и тем же)
    hdr = rng.choice(["", "// Типы и разбор ответа API.\n",
                      "// Модуль разбора ответа сервиса.\n// Используется на экране списка.\n"])
    buggy, fixed = hdr + buggy, hdr + fixed
    buggy_js, fixed_js = lines(B, True), lines(L, True)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    ids = rng.sample(range(1, 90), 6)
    unk = rng.choice(["archived", "deleted", "draft", "unknown", "spam"])
    bad_list = rng.choice([None, {"0": "a"}])
    good = lambda i: {"id": i, st: rng.choice(vals), lst: [f"x{i}"]}  # noqa: E731
    dirty = [good(ids[0]), None, {"id": str(ids[1]), st: vals[0], lst: []},
             {"id": ids[2], st: unk, lst: []}, {"id": ids[3], st: vals[1], lst: bad_list},
             good(ids[4]), [1, 2], "строка", {"id": ids[5], st: vals[2], lst: {"0": "a"}}]
    rng.shuffle(dirty)
    pos = dirty.index(None)
    expected = [d["id"] for d in dirty if isinstance(d, dict) and d["id"] in (ids[0], ids[4])]
    sep = (",", ":")
    payload = json.dumps(json.dumps(dirty, ensure_ascii=False), ensure_ascii=False)
    test = (f"const res = {parse}({payload});\n"
            f"__assert(JSON.stringify(res.map((x) => x.id)) === {json.dumps(json.dumps(expected, separators=sep))}, "
            f"'прошли: ' + JSON.stringify(res.map((x) => x.id)));")
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy_js, test),
                    expect="fail", embeds_display_code=False),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed_js, test),
                    expect="pass", embeds_display_code=False)]
    total = rng.randint(20, 240)
    symptom = SYMPTOM[subtype].format(lst=lst, st=st, pos=rng.randint(2, total), total=total,
                                      i2=ids[2], i1=ids[1], i3=ids[3], v1=vals[1],
                                      unk=unk, bad=json.dumps(bad_list, ensure_ascii=False))
    stem = (f"Функция `{parse}` ({ctx}) разбирает ответ API, а type guard `{guard}` должен "
            f"пропускать только значения, полностью соответствующие интерфейсу `{T}`. Код "
            f"компилируется в strict-режиме без ошибок, но в продакшене {symptom}. Укажите "
            f"номер строки с ошибкой.")
    why = {"null_check": "typeof null === 'object', поэтому без проверки на null дальше читается "
                         "поле у null",
           "array_check": "typeof и для null, и для объекта даёт 'object' — массив проверяется "
                          "только Array.isArray",
           "id_check": "'id' in проверяет наличие поля, но не его тип",
           "enum_check": "проверка typeof string не ограничивает значение допустимым набором"}
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {why[subtype]}. Type guard — обещание "
                               f"компилятору: TypeScript верит `value is {T}` и не проверяет "
                               f"тело функции, поэтому ошибка в нём не ловится при компиляции.")
    return build_variant(family_id, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="unsound_type_guard",
                         display_code_note="Для проверки ключа аннотации типов удалены (построчно), "
                                           "код исполняется как JavaScript в Node.js.",
                         params={"fixed_code": fixed, "subtype": subtype})



def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES_HERE)
