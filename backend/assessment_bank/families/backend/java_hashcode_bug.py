"""backend.java.hashcode_bug — find_bug: hashCode не согласован с equals.

Класс-значение сравнивается в equals по ключевым полям, а hashCode включает ещё и неключевое поле
(время изменения, количество, комментарий). Два «равных» объекта получают разные хэши: HashSet
не убирает дубль, HashMap не находит запись по равному ключу. Один подтип дефекта; варьируются
контекст, имена, порядок методов и служебные строки (toString, конструктор), строка дефекта не постоянна.
Проверка исполнением (javac + JVM): дубль в HashSet и поиск в HashMap по равному ключу.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.hashcode_bug"

# (контекст, классы, ключевые поля [(тип, [имена], шаблон значения)], неключевые [(тип, имя, шаблон)])
CONTEXTS = [("корзина магазина", ["CartLine", "BasketItem"],
             [("String", ["sku", "article"], '"SKU-{n}"'), ("int", ["warehouse", "storeId"], "{m}")],
             [("int", "quantity", "{q}"), ("long", "addedAt", "{q}000L"), ("String", "promo", '"p{q}"')]),
            ("бронирование", ["SeatKey", "SeatHold"],
             [("String", ["flight", "flightNo"], '"SU{n}"'), ("String", ["seat", "seatNo"], '"{m}A"')],
             [("long", "heldUntil", "{q}L"), ("String", "passenger", '"pax{q}"'), ("int", "attempts", "{q}")]),
            ("биллинг", ["InvoiceId", "BillKey"],
             [("String", ["account", "accountId"], '"ACC-{n}"'), ("int", ["period", "month"], "2026{m:02d}")],
             [("String", "comment", '"note {q}"'), ("double", "amount", "{q}.5"), ("long", "issuedAt", "{q}L")]),
            ("каталог", ["ProductRef", "OfferKey"],
             [("String", ["vendor", "brand"], '"v{n}"'), ("String", ["code", "model"], '"c{m}"')],
             [("double", "price", "{q}.5"), ("int", "stock", "{q}"), ("String", "title", '"t{q}"')]),
            ("доставка", ["ParcelKey", "Shipment"],
             [("String", ["route", "routeId"], '"R{n}"'), ("int", ["slot", "window"], "{m}")],
             [("long", "updatedAt", "{q}000L"), ("String", "courier", '"c{q}"'), ("int", "weight", "{q}")])]


def _code(c, buggy: bool, methods_order: list[str], with_tostring: bool, getter: bool,
          eq_style: str, note: str) -> tuple[str, int]:
    cls, keys, (xt, xn) = c
    (t1, f1), (t2, f2) = keys
    fields = [f"    private final {t1} {f1};", f"    private final {t2} {f2};", f"    private final {xt} {xn};", ""]
    ctor = [f"    {cls}({t1} {f1}, {t2} {f2}, {xt} {xn}) {{", f"        this.{f1} = {f1};",
            f"        this.{f2} = {f2};", f"        this.{xn} = {xn};", "    }", ""]
    eq1 = f"Objects.equals({f1}, o.{f1})" if t1 == "String" else f"{f1} == o.{f1}"
    eq2 = f"Objects.equals({f2}, o.{f2})" if t2 == "String" else f"{f2} == o.{f2}"
    equals = ["    @Override", "    public boolean equals(Object other) {",
              "        if (this == other) return true;",
              ("        if (!(other instanceof " + cls + " o)) return false;" if eq_style == "pattern" else
               "        if (other == null || getClass() != other.getClass()) return false;"),
              *([] if eq_style == "pattern" else [f"        {cls} o = ({cls}) other;"]),
              f"        return {eq1} && {eq2};", "    }", ""]
    hargs = f"{f1}, {f2}, {xn}" if buggy else f"{f1}, {f2}"
    hashcode = ["    @Override", "    public int hashCode() {", f"        return Objects.hash({hargs});", "    }", ""]
    extra = []
    if getter:
        extra = [f"    {xt} {xn}() {{", f"        return {xn};", "    }", ""]
    tostring = []
    if with_tostring:
        tostring = ["    @Override", "    public String toString() {",
                    f'        return "{cls}[" + {f1} + ", " + {f2} + "]";', "    }", ""]
    blocks = {"equals": equals, "hashCode": hashcode, "toString": tostring, "getter": extra}
    body = fields + ctor
    for m in methods_order:
        body += blocks[m]
    while body and body[-1] == "":
        body.pop()
    lines = ["import java.util.Objects;", ""] + ([note] if note else []) + [f"final class {cls} {{"] + body + ["}"]
    key = next(i for i, l in enumerate(lines, 1) if "return Objects.hash(" in l)
    return "\n".join(lines) + "\n", key


def _harness(code: str, cls: str, a: str, b: str) -> str:
    imports = "import java.util.*;\n"
    return (imports + code.replace("import java.util.Objects;\n", "", 1) + "\n"
            "public class Main {\n    public static void main(String[] args) {\n"
            f"        {cls} x = new {cls}({a});\n        {cls} y = new {cls}({b});\n"
            f"        Set<{cls}> set = new HashSet<>();\n        set.add(x);\n        set.add(y);\n"
            f"        Map<{cls}, String> map = new HashMap<>();\n        map.put(x, \"ok\");\n"
            "        boolean pass = x.equals(y) && set.size() == 1 && \"ok\".equals(map.get(y));\n"
            "        System.out.println(pass ? \"RESULT: PASS\" : \"RESULT: FAIL set=\" + set.size());\n"
            "    }\n}\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, classes, key_defs, extras = rng.choice(CONTEXTS)
    cls = rng.choice(classes)
    keys = [(t, rng.choice(names)) for t, names, _v in key_defs]
    xt, xn, xv = rng.choice(extras)
    vals = [v for _t, _n, v in key_defs] + [xv]
    c = (cls, keys, (xt, xn))
    eq_style = rng.choice(["pattern", "getclass"])
    order = ["equals", "hashCode", "toString", "getter"]
    rng.shuffle(order)
    with_tostring = rng.random() < 0.5
    getter = rng.random() < 0.5
    order = [m for m in order if (m != "toString" or with_tostring) and (m != "getter" or getter)]
    note = rng.choice(["", f"// Ключ {ctx}: используется в HashMap и HashSet",
                       "// Значимый объект: сравнивается по ключевым полям", "// Создаётся при каждом запросе",
                       "// Неизменяемый класс"])
    buggy, key = _code(c, True, order, with_tostring, getter, eq_style, note)
    fixed, _ = _code(c, False, order, with_tostring, getter, eq_style, note)
    assert changed_lines(buggy, fixed) == {key}
    n, m = rng.randint(10, 99), rng.randint(1, 12)
    q1, q2 = rng.sample(range(1, 90), 2)
    v1 = ", ".join(v.format(n=n, m=m, q=q1) for v in vals)
    v2 = ", ".join(v.format(n=n, m=m, q=q2) for v in vals)
    checks = [Check(name="buggy_fails", runner="java", program=_harness(buggy, cls, v1, v2), expect="fail",
                    embeds_display_code=False),
              Check(name="fixed_passes", runner="java", program=_harness(fixed, cls, v1, v2), expect="pass",
                    embeds_display_code=False)]
    (t1, f1), (t2, f2) = keys
    stem = (f"Класс `{cls}` ({ctx}) — ключ: объекты с одинаковыми `{f1}` и `{f2}` считаются одним и тем же, "
            f"`{xn}` — изменяемая характеристика. После добавления в `HashSet` двух объектов с одинаковыми "
            f"`{f1}`/`{f2}` и разным `{xn}` в наборе оказывается два элемента, а `map.get(...)` по равному "
            f"ключу возвращает null. Укажите номер строки с ошибкой.")
    why = (f"Строка {key}: hashCode включает поле {xn}, которого нет в equals. Равные по equals объекты "
           f"обязаны иметь одинаковый hashCode, иначе попадают в разные корзины HashSet/HashMap. "
           f"Исправление — Objects.hash({f1}, {f2}).")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="hashcode_inconsistent",
                         display_code_note="Показанный класс исполняется с импортом java.util.* вместо "
                                           "java.util.Objects и классом Main с тестом.",
                         params={"fixed_code": fixed, "order": order, "eq_style": eq_style})
