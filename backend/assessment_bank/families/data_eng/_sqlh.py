"""Общие помощники семейств data_eng: исполнение SQL в sqlite3 и обвязка проверки «найди ошибку»."""
from __future__ import annotations

import sqlite3


def rows(setup: str, query: str) -> str:
    """Вывод запроса в формате раннера sqlite: строки «a|b», NULL для пустых значений."""
    con = sqlite3.connect(":memory:")
    con.executescript(setup)
    out = ["|".join("NULL" if v is None else str(v) for v in r) for r in con.execute(query).fetchall()]
    con.close()
    return "\n".join(out)


def insert(table: str, cols: list[str], data: list[tuple]) -> str:
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, str):
            return "'" + v.replace("'", "''") + "'"
        return str(v)
    vals = ",\n  ".join("(" + ", ".join(lit(v) for v in r) + ")" for r in data)
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n  {vals};"


HARNESS = '''import sqlite3

SETUP = {setup!r}
EXPECTED = {expected!r}
QUERY = r"""
{query}
"""
con = sqlite3.connect(":memory:")
con.executescript(SETUP)
got = "\\n".join("|".join("NULL" if v is None else str(v) for v in r) for r in con.execute(QUERY).fetchall())
print("RESULT: PASS" if got == EXPECTED else "RESULT: FAIL")
'''


def harness(setup: str, query: str, expected: str) -> str:
    """Программа на Python: исполняет показанный запрос (вставлен дословно) и сверяет с ожидаемым выводом."""
    return HARNESS.format(setup=setup, query=query, expected=expected)
