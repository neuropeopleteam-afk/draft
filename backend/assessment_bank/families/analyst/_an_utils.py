"""Общие помощники семейств «Аналитик» (только для генераторов этого каталога).

* ``balanced_options``, ``check_lengths``, ``sql_py_program``, ``rows_literal`` — проверенные помощники Data/ML
  (позиция ключа сбалансирована по блокам seed; варианты сопоставимой длины; показанный SQL исполняется дословно);
* ``run_sql`` — исполнить запрос в sqlite3 при генерации, чтобы подобрать данные, на которых дистракторы
  действительно расходятся с эталоном (сама проверка ключа — в песочнице валидатора);
* ``py_literal_block`` — вложить показанную текстовую модель (BPMN, UML, контракт) дословно в программу-модель
  на Python: модель разбирает именно показанный текст;
* ``cap`` — первая буква заглавная, остальное без изменений.
"""
from __future__ import annotations

import sqlite3

from assessment_bank.families.data_ml._dm_utils import (  # noqa: F401
    balanced_options, check_lengths, rows_literal, sql_py_program)


def run_sql(setup: str, query: str) -> str:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(setup)
        rows = con.execute(query).fetchall()
    except sqlite3.Error as exc:
        return f"ERROR: {exc}"
    finally:
        pass
    con.close()
    return "\n".join("|".join("NULL" if v is None else str(v) for v in r) for r in rows)


def py_literal_block(name: str, text: str) -> str:
    """`NAME = r'''…'''` — дословная вставка показанного текста в программу Python."""
    if "'''" in text or text.endswith("\\"):
        raise ValueError("текст нельзя дословно вложить в строковый литерал")
    return f"{name} = r'''\n{text}\n'''\n"


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]
