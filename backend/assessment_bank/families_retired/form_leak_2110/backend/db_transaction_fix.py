"""backend.db.transaction_fix — choose_fix: атомарный перевод в одной транзакции (sqlite3).

Код с дефектом фиксирует списание отдельным commit до проверок: при нехватке средств или
отсутствии получателя деньги «исчезают». Верно — commit после всех проверок и rollback с повторным
исключением при любой ошибке (как `with con:`). Все варианты — 12 строк одной формы
try/except. Дистракторы: rollback только для sqlite3.Error или только для ValueError (другая
ошибка оставляет открытую транзакцию), commit до проверки получателя, подавление исключения.
"""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, dedent, indent, make_options, make_rng,
                                       py_harness)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.db.transaction_fix"

CONTEXTS = [("transfer", "accounts", "balance", "перевод между счетами", "банк",
             "недостаточно средств", "нет счёта получателя"),
            ("move_points", "bonus_accounts", "points", "перенос баллов между картами",
             "программа лояльности", "недостаточно баллов", "нет карты получателя"),
            ("move_stock", "warehouses", "qty", "перемещение товара между складами", "склад",
             "недостаточно товара", "нет склада получателя"),
            ("pay_out", "wallets", "amount", "выплату с кошелька продавца", "маркетплейс",
             "недостаточно средств", "нет кошелька получателя")]

DEBIT = 'con.execute("UPDATE {t} SET {c} = {c} - ? WHERE id = ?", (amount, src))'
READ = '(left,) = con.execute("SELECT {c} FROM {t} WHERE id = ?", (src,)).fetchone()'
CREDIT = 'cur = con.execute("UPDATE {t} SET {c} = {c} + ? WHERE id = ?", (amount, dst))'
CORE = ["    " + DEBIT, "    " + READ, "    if left < 0:", '        raise ValueError("{e1}")',
        "    " + CREDIT, "    if cur.rowcount != 1:", '        raise LookupError("{e2}")']

# все варианты — 12 строк одной формы try/except; отличаются одной-двумя деталями
BODIES = {
    "good": ["try:"] + CORE + ["except Exception:", "    con.rollback()", "    raise",
                               "con.commit()"],
    "rollback_db_only": ["try:"] + CORE + ["except sqlite3.Error:", "    con.rollback()",
                                           "    raise", "con.commit()"],
    "rollback_value_only": ["try:"] + CORE + ["except ValueError:", "    con.rollback()",
                                              "    raise", "con.commit()"],
    "commit_before_check": ["try:"] + CORE[:5] + ["    con.commit()"] + CORE[5:] + [
        "except Exception:", "    con.rollback()", "    raise"],
    "swallow_errors": ["try:"] + CORE + ["except Exception:", "    con.rollback()", "    return",
                                         "con.commit()"],
}
BUGGY = ["    " + DEBIT, "    con.commit()", "    " + READ, "    if left < 0:",
         '        raise ValueError("{e1}")', "    " + CREDIT, "    if cur.rowcount != 1:",
         '        raise LookupError("{e2}")', "    con.commit()"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, t, c, what, ctx, e1, e2 = rng.choice(CONTEXTS)
    f = dict(t=t, c=c, e1=e1, e2=e2)
    chosen = rng.sample(["rollback_db_only", "rollback_value_only", "commit_before_check",
                         "swallow_errors"], 3)
    a, b = rng.sample(range(1, 50), 2)
    va, vb = rng.randint(3, 9) * 100, rng.randint(1, 5) * 100
    ok_amt = rng.randint(1, va // 100 - 1) * 100
    big = va - ok_amt + rng.randint(1, 5) * 100
    missing = rng.choice([x for x in range(50, 99)])
    back = rng.randint(1, 3) * 50
    code = "\n".join(["import sqlite3", "", "",
                      f"def {fn}(con: sqlite3.Connection, src: int, dst: int, amount: int) -> None:"]
                     + [line.format(**f) for line in BUGGY])
    opt = lambda k: "\n".join(["import sqlite3", "", "",
                               f"def {fn}(con: sqlite3.Connection, src: int, dst: int, amount: int) -> None:"]
                              + [indent(line.format(**f)) for line in BODIES[k]])
    after1 = {a: va - ok_amt, b: vb + ok_amt}
    after2 = {a: after1[a] + back, b: after1[b] - back}
    tests = dedent(f"""
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE {t} (id INTEGER PRIMARY KEY, {c} INTEGER NOT NULL)")
        con.executemany("INSERT INTO {t} VALUES (?, ?)", [({a}, {va}), ({b}, {vb})])
        con.commit()
        state = lambda: dict(con.execute("SELECT id, {c} FROM {t}"))
        {fn}(con, {a}, {b}, {ok_amt})
        assert state() == {after1!r} and not con.in_transaction
        try:
            {fn}(con, {a}, {b}, {big})
            raise AssertionError("нет ValueError")
        except ValueError:
            pass
        assert state() == {after1!r} and not con.in_transaction
        try:
            {fn}(con, {b}, {missing}, {back})
            raise AssertionError("нет LookupError")
        except LookupError:
            pass
        assert state() == {after1!r} and not con.in_transaction
        {fn}(con, {b}, {a}, {back})
        assert state() == {after2!r} and not con.in_transaction
        """)
    opts, key = make_options(rng, ("Заменить функцию на:", opt("good")),
                             [("Заменить функцию на:", opt(k)) for k in chosen])
    checks = [Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False)
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, tests),
                        expect="fail"))
    stem = (f"Функция `{fn}` ({ctx}) выполняет {what} в SQLite через модуль `sqlite3` "
            f"(режим транзакций по умолчанию). Требования: оба изменения применяются вместе или не "
            f"применяются вовсе; при нехватке — `ValueError`, при отсутствии получателя — "
            f"`LookupError`, и в обоих случаях данные в базе не меняются; после вызова не остаётся "
            f"открытой транзакции — соединение используется дальше. Сейчас после "
            f"`{fn}(con, {a}, {b}, {big})` с ошибкой «{e1}» у отправителя всё равно списано "
            f"{big}. Какое исправление выполняет все требования?")
    why = {"rollback_db_only": "rollback только для sqlite3.Error: после ValueError и LookupError "
                               "транзакция со списанием остаётся открытой и попадёт в следующий commit",
           "rollback_value_only": "rollback только для ValueError: после LookupError списание "
                                  "остаётся в открытой транзакции",
           "commit_before_check": "commit стоит до проверки получателя: LookupError возникает, "
                                  "когда списание уже зафиксировано, и rollback ничего не откатывает",
           "swallow_errors": "исключение подавлено: откат есть, но вызывающий код не узнаёт об "
                             "ошибке — ValueError и LookupError не выбрасываются"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: commit после всех проверок, rollback и повторное "
                               "исключение при любой ошибке (то же делает `with con:`). "
                               "Дистракторы: " + "; ".join(why[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="partial_commit", params={"distractors": chosen})
