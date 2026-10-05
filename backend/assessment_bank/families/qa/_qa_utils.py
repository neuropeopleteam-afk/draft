"""Общие помощники семейств QA (только для генераторов этого каталога).

Повторно используем проверенные помощники Data/ML: ``balanced_options`` (позиция
правильного ответа сбалансирована по блокам seed), ``check_lengths`` (варианты ответа
сопоставимой длины — нет подсказки длиной) и ``sql_py_program`` (показанный SQL-запрос
исполняется дословно в sqlite3 и сверяется с ожидаемыми строками, печатает RESULT).
"""
from __future__ import annotations

from assessment_bank.families.data_ml._dm_utils import (  # noqa: F401
    balanced_options, check_lengths, rows_literal, sql_py_program)


def ru_num(x) -> str:
    """Число по-русски: десятичная запятая, пробел между тысячами."""
    if isinstance(x, int):
        return f"{x:,}".replace(",", " ")
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s
