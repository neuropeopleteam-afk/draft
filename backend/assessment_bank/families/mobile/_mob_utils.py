"""Общие помощники семейств «Мобильная разработка» (только для генераторов этого каталога).

* ``balanced_options``, ``check_lengths``, ``sql_py_program`` — проверенные помощники Data/ML (позиция ключа
  сбалансирована по блокам seed; варианты сопоставимой длины; показанный SQL исполняется дословно в sqlite3);
* ``py_literal_block`` — вложить показанный кандидату код (Kotlin, Swift) дословно в программу-модель на Python:
  модель разбирает именно показанный текст, поэтому ключ проверяется по тому, что видит кандидат.
"""
from __future__ import annotations

from assessment_bank.families.data_ml._dm_utils import (  # noqa: F401
    balanced_options, check_lengths, rows_literal, sql_py_program)


def py_literal_block(name: str, text: str) -> str:
    """`NAME = r'''…'''` — дословная вставка показанного кода в программу Python."""
    if "'''" in text or text.endswith("\\"):
        raise ValueError("код нельзя дословно вложить в строковый литерал")
    return f"{name} = r'''\n{text}\n'''\n"
