"""backend.db.t21_tx_exit_suppress_output — predict_output (набор t21, порог Senior): __exit__, который подавляет
исключение, вместе с try / except / finally.

Обработчик пишет в БД внутри «транзакции» — контекстного менеджера, __exit__ которого печатает commit/rollback и
возвращает `exc_type is <класс>`. Ловушки: истинный результат __exit__ глотает исключение — выполнение идёт дальше
после with, и функция возвращает «ok», хотя запись не сделана; другое исключение уходит в except; finally
печатает до того, как вызывающий напечатает возвращённое значение; строка внутри with после исключения не
выполняется. Ключ — независимая модель по ветвям в генераторе; проверка — исполнение показанного кода в
песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.db.t21_tx_exit_suppress_output"

CTX = [("склад", ["tea", "cup", "box", "jar", "mug", "lid"]), ("биллинг", ["basic", "pro", "team", "trial", "max"]),
       ("доставка", ["msk", "spb", "kzn", "ekb", "nsk"]), ("каталог", ["sofa", "lamp", "desk", "rug", "shelf"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    k_ok, k_zero, k_missing = rng.sample(pool, 3)
    total = rng.choice([60, 90, 100, 120, 240])
    ok_val = rng.choice([d for d in (2, 3, 4, 5, 6, 8) if total % d == 0])
    table = {k_ok: ok_val, k_zero: 0}
    items = list(table.items())
    rng.shuffle(items)
    swallow = rng.choice(["KeyError", "ZeroDivisionError"])
    sw_kind = "missing" if swallow == "KeyError" else "zero"
    other_kind = rng.choice(["ok", "zero" if sw_kind == "missing" else "missing"])
    kinds = [sw_kind, other_kind]
    rng.shuffle(kinds)  # в каждом варианте есть вызов с подавленным исключением
    calls = [{"ok": k_ok, "zero": k_zero, "missing": k_missing}[k] for k in kinds]
    var = rng.choice(["stock", "prices", "limits"])
    cls = rng.choice(["Tx", "Atomic", "UnitOfWork"])
    fn = rng.choice(["handle", "save", "apply"])
    lit = "{" + ", ".join(f'"{k}": {v}' for k, v in items) + "}"
    code = (f"{var} = {lit}\n"
            f"class {cls}:\n"
            "    def __enter__(self):\n"
            "        return self\n"
            "    def __exit__(self, exc_type, exc, tb):\n"
            '        print("rollback" if exc_type else "commit")\n'
            f"        return exc_type is {swallow}\n"
            f"def {fn}(sku):\n"
            "    try:\n"
            f"        with {cls}():\n"
            f'            print("per_unit", {total} // {var}[sku])\n'
            '        return "ok"\n'
            "    except Exception as e:\n"
            "        return type(e).__name__\n"
            "    finally:\n"
            '        print("audit", sku)\n'
            f"for sku in {calls!r}:\n"
            f"    print({fn}(sku))").replace("'", '"')
    lines: list[str] = []
    notes: list[str] = []
    for kind, sku in zip(kinds, calls):
        if kind == "ok":
            lines += [f"per_unit {total // ok_val}", "commit", f"audit {sku}", "ok"]
            notes.append(f"{sku}: исключения нет — per_unit {total // ok_val}, commit, audit, return «ok»")
            continue
        exc = "ZeroDivisionError" if kind == "zero" else "KeyError"
        lines.append("rollback")
        if exc == swallow:
            ret = "ok"
            notes.append(f"{sku}: {exc} внутри with, __exit__ печатает rollback и возвращает True — исключение "
                         "подавлено, print внутри with не выполнился, функция доходит до return «ok»")
        else:
            ret = exc
            notes.append(f"{sku}: {exc}, __exit__ возвращает False — исключение уходит в except, return «{exc}»")
        lines += [f"audit {sku}", ret]
    out = "\n".join(lines)
    expl = ("; ".join(notes) + ". В каждом вызове finally печатает audit до того, как цикл напечатает возвращённое "
            "значение.")
    stem = (f"Сервис «{ctx}»: обработчик пересчитывает показатель внутри транзакции — контекстного менеджера, который "
            "печатает commit или rollback.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"calls": calls, "swallow": swallow, "kinds": kinds}, language="python")
