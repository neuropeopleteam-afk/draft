"""backend.django.signals_output — predict_output: какие операции ORM посылают сигнал post_save.

Один подтип: приёмник `post_save` для одной модели пишет в журнал «номер:new|upd»; затем выполняется
последовательность операций ORM. Ловушки: `QuerySet.update()` и `bulk_create()` сигналов не посылают,
`get_or_create()` существующей записи — тоже, а `save(update_fields=...)` и `save()` после
`get_or_create()` — посылают (created=False). Исполняется настоящий Django (SQLite в памяти); ключ —
независимая модель операций.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.django.signals_output"

# (контекст, модель, поле номера, числовое поле, префикс номеров)
CONTEXTS = [("интернет-магазин", "Order", "number", "total", "A"), ("поддержка", "Ticket", "code", "priority", "T"),
            ("библиотека", "Loan", "ref", "days", "L"), ("склад", "Shipment", "track", "weight", "S"),
            ("клиника", "Visit", "slot", "minutes", "V")]
# операции: (имя, строки кода (шаблон), сигналы)
# переменные: o1 — создан через create(); o2 — через save(); num — следующий номер
OPS = {
    "save_new": ('{v} = {M}({num}="{P}{n}", {fld}={x})\n{v}.save()', ["{P}{n}:new"]),
    "update_fields": ('{v}.{fld} = {x}\n{v}.save(update_fields=["{fld}"])', ["{Pv}:upd"]),
    "qs_update": ('{M}.objects.filter({num}="{Pv}").update({fld}={x})', []),
    "bulk_create": ('{M}.objects.bulk_create([{M}({num}="{P}{n}"), {M}({num}="{P}{n1}")])', []),
    "get_or_create_existing": ('{g}, made = {M}.objects.get_or_create({num}="{Pv}", defaults={{"{fld}": {x}}})',
                               []),
    "get_or_create_new": ('{g}, made = {M}.objects.get_or_create({num}="{P}{n}", defaults={{"{fld}": {x}}})',
                          ["{P}{n}:new"]),
    "get_save": ('{M}.objects.get({num}="{Pv}").save()', ["{Pv}:upd"]),
    "delete": ('{M}.objects.filter({num}="{Pv}").delete()', []),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, M, num, fld, P = rng.choice(CONTEXTS)
    first = rng.choice([1, 10, 100])
    n = first
    code_ops: list[str] = []
    expected: list[str] = []
    live: list[str] = []  # номера существующих записей
    vars_: list[str] = []
    # первая запись всегда через create()
    code_ops.append(f'o1 = {M}.objects.create({num}="{P}{n}", {fld}={rng.randint(1, 9) * 10})')
    expected.append(f"{P}{n}:new")
    live.append(f"{P}{n}")
    vars_.append("o1")
    n += 1
    names = list(OPS)
    k = rng.randint(4, 6)
    chosen = []
    while len(chosen) < k:
        op = rng.choice(names)
        if op in ("bulk_create", "delete", "qs_update") and op in chosen:
            continue
        chosen.append(op)
    gi = 0
    for op in chosen:
        tmpl, sigs = OPS[op]
        v = rng.choice([x for x in vars_ if x != "deleted"]) if vars_ else "o1"
        Pv = live[vars_.index(v)] if v in vars_ else live[0]
        x = rng.randint(1, 9) * 10
        if op == "save_new":
            newv = f"o{len(vars_) + 1}"
            code_ops.append(tmpl.format(v=newv, M=M, num=num, P=P, n=n, fld=fld, x=x))
            expected += [s.format(P=P, n=n) for s in sigs]
            vars_.append(newv)
            live.append(f"{P}{n}")
            n += 1
        elif op == "bulk_create":
            code_ops.append(tmpl.format(M=M, num=num, P=P, n=n, n1=n + 1))
            n += 2
        elif op == "get_or_create_new":
            gi += 1
            code_ops.append(tmpl.format(g=f"g{gi}", M=M, num=num, P=P, n=n, fld=fld, x=x))
            expected += [s.format(P=P, n=n) for s in sigs]
            vars_.append(f"g{gi}")
            live.append(f"{P}{n}")
            n += 1
        elif op == "get_or_create_existing":
            gi += 1
            code_ops.append(tmpl.format(g=f"g{gi}", M=M, num=num, Pv=Pv, fld=fld, x=x))
        elif op == "delete":
            if len(vars_) < 2:
                continue  # удалять единственную запись не будем: дальше операции над ней
            code_ops.append(tmpl.format(M=M, num=num, Pv=Pv))
            idx = vars_.index(v)
            vars_.pop(idx)
            live.pop(idx)
        else:
            code_ops.append(tmpl.format(v=v, M=M, num=num, Pv=Pv, fld=fld, x=x))
            expected += [s.format(Pv=Pv) for s in sigs]
    out = f"{len(expected)} " + " ".join(expected)
    code = "\n".join([
        "from django.db import models",
        "from django.db.models.signals import post_save",
        "from django.dispatch import receiver",
        "",
        "",
        f"class {M}(models.Model):",
        f"    {num} = models.CharField(max_length=20)",
        f"    {fld} = models.IntegerField(default=0)",
        "",
        "",
        "log = []",
        "",
        "",
        f"@receiver(post_save, sender={M})",
        "def on_saved(sender, instance, created, **kwargs):",
        f'    log.append(f"{{instance.{num}}}:{{\'new\' if created else \'upd\'}}")',
        "",
        "",
        "create_tables()",
    ] + code_ops + ['print(len(log), " ".join(log))']) + "\n"
    setup = "\n".join(["def create_tables():", "    from django.db import connection as _c",
                       "    with _c.schema_editor() as se:", f"        se.create_model({M})", "", ""])
    checks = [Check(name="run", runner="django", program=setup + code, expect="stdout_equals", expected_stdout=out)]
    stem = (f"Django ORM ({ctx}), SQLite. Функция `create_tables()` создаёт таблицу (сигналов не посылает). "
            f"Что выведет программа: число записей в `log` и сами записи через пробел, как печатает `print`?")
    why = ("post_save посылают `create()`, `save()` (в том числе с update_fields) и `get_or_create()`, когда запись "
           "создана. `QuerySet.update()`, `bulk_create()` и `delete()` сигнал post_save не посылают, "
           "`get_or_create()` существующей записи — тоже. Поэтому в журнале ровно эти строки, по порядку.")
    ak = AnswerKey(kind="output", value=out, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         display_code_note="Перед показанным кодом исполняется create_tables(): создание таблицы.",
                         params={"ops": chosen, "n_signals": len(expected)})
