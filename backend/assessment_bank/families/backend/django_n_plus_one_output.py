"""backend.django.n_plus_one_output — predict_output: число SQL-запросов Django ORM (N+1).

Один подтип: queryset с filter и select_related для одного внешнего ключа, а в цикле читаются оба
внешних ключа. Ловушки: select_related покрывает только указанную связь; Django не делит объекты
между строками — у каждой книги своя загрузка второго ключа, даже если значение одно и то же;
считать надо строки после фильтра. Исполняется настоящий Django (SQLite в памяти), запросы считает
CaptureQueriesContext; ключ — независимая модель (1 + число строк после фильтра).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, text_table
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.django.n_plus_one_output"

# (контекст, главная модель, поле фильтра, связь A (модель, поле), связь B (модель, поле))
CONTEXTS = [("книжный магазин", "Book", "price", ("Author", "author"), ("Publisher", "publisher")),
            ("доставка", "Parcel", "weight", ("Courier", "courier"), ("Depot", "depot")),
            ("поддержка", "Ticket", "priority", ("Agent", "agent"), ("Customer", "customer")),
            ("кинотеатр", "Session", "seats", ("Movie", "movie"), ("Hall", "hall")),
            ("склад", "Batch", "qty", ("Supplier", "supplier"), ("Warehouse", "warehouse"))]
NAMES_A = ["Ivanov", "Petrova", "Smirnov", "Orlova", "Kuznetsov"]
NAMES_B = ["North", "South", "Central", "East"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, main, fld, (ma, fa), (mb, fb) = rng.choice(CONTEXTS)
    n_a, n_b = rng.randint(2, 3), rng.randint(1, 2)
    n_rows = rng.randint(5, 8)
    thr = rng.randint(30, 70)
    rows = []
    for i in range(n_rows):
        rows.append((f"{main[0]}{i + 1}", rng.randint(10, 99), rng.randrange(n_a), rng.randrange(n_b)))
    n_pass = sum(1 for r in rows if r[1] >= thr)
    if n_pass < 2:
        rows[0] = (rows[0][0], thr + 5, rows[0][2], rows[0][3])
        rows[1] = (rows[1][0], thr + 9, rows[1][2], rows[1][3])
        n_pass = sum(1 for r in rows if r[1] >= thr)
    sel = rng.choice(["a", "b"])
    sel_f = fa if sel == "a" else fb
    a_names = NAMES_A[:n_a]
    b_names = NAMES_B[:n_b]
    code = "\n".join([
        "from django.db import connection, models",
        "from django.test.utils import CaptureQueriesContext",
        "",
        "",
        f"class {ma}(models.Model):",
        "    name = models.CharField(max_length=50)",
        "",
        "",
        f"class {mb}(models.Model):",
        "    name = models.CharField(max_length=50)",
        "",
        "",
        f"class {main}(models.Model):",
        "    title = models.CharField(max_length=50)",
        f"    {fld} = models.IntegerField()",
        f"    {fa} = models.ForeignKey({ma}, on_delete=models.CASCADE)",
        f"    {fb} = models.ForeignKey({mb}, on_delete=models.CASCADE)",
        "",
        "",
        "def report():",
        "    lines = []",
        f"    qs = {main}.objects.filter({fld}__gte={thr}).select_related(\"{sel_f}\")",
        "    for obj in qs:",
        f"        lines.append(f\"{{obj.title}}: {{obj.{fa}.name}} / {{obj.{fb}.name}}\")",
        "    return lines",
        "",
        "",
        "load_fixture()  # данные из таблицы в условии",
        "with CaptureQueriesContext(connection) as ctx:",
        "    lines = report()",
        "print(len(lines), len(ctx.captured_queries))",
    ]) + "\n"
    setup = "\n".join([
        "def load_fixture():",
        "    from django.db import connection as _c",
        "    with _c.schema_editor() as se:",
        f"        se.create_model({ma})",
        f"        se.create_model({mb})",
        f"        se.create_model({main})",
        f"    a = [{ma}.objects.create(name=n) for n in {a_names!r}]",
        f"    b = [{mb}.objects.create(name=n) for n in {b_names!r}]",
        f"    for t, v, ia, ib in {rows!r}:",
        f"        {main}.objects.create(title=t, {fld}=v, {fa}=a[ia], {fb}=b[ib])",
        "", ""])
    expected = f"{n_pass} {1 + n_pass}"
    checks = [Check(name="run", runner="django", program=setup + code, expect="stdout_equals",
                    expected_stdout=expected)]
    table = text_table(["title", fld, fa, fb], [(t, v, a_names[ia], b_names[ib]) for t, v, ia, ib in rows])
    stem = (f"Django ORM ({ctx}), SQLite. В таблице `{main}` такие строки:\n\n{table}\n\n"
            f"Функция `load_fixture()` создаёт таблицы и эти строки (её запросы не считаются). Что выведет "
            f"программа: число строк отчёта и число SQL-запросов внутри `report()`? Ответ — два числа через "
            f"пробел, как печатает программа.")
    other = fb if sel == "a" else fa
    why = (f"После фильтра {fld} ≥ {thr} остаётся {n_pass} строк. select_related(\"{sel_f}\") подтягивает "
           f"связь JOIN в том же запросе, а `{other}` загружается отдельным запросом для каждой строки: "
           f"Django не делит объекты между строками, даже если значение совпадает. Итого 1 + {n_pass}.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Перед показанным кодом исполняется load_fixture(): создание "
                                           "таблиц и строк из условия.",
                         params={"n_pass": n_pass, "select": sel_f})
