"""Общие помощники семейств Data/ML (только для генераторов этого каталога).

* ``check_lengths`` — защита от подсказки длиной: варианты ответа одного вопроса должны
  быть сопоставимой длины (генератор падает, если разброс слишком велик, и валидатор это
  увидит как ошибку генерации);
* ``sql_py_program`` — обвязка, исполняющая показанный SQL-запрос (дословно, внутри
  строкового литерала Python) в sqlite3 и печатающая RESULT: PASS/FAIL — нужна для
  find_bug/choose_fix на SQL, где валидатор ждёт проверки pass/fail;
* ``fmt`` — единое форматирование чисел в ответах.

Код исполняется в песочнице с ``python -I -S``: numpy там недоступен, поэтому все
проверяемые фрагменты написаны на стандартной библиотеке.
"""
from __future__ import annotations

from typing import Iterable, Sequence


def check_lengths(texts: Sequence[str], max_ratio: float = 1.35, slack: int = 6) -> None:
    """Длины вариантов сопоставимы: max <= min * max_ratio + slack символов."""
    lens = [len(t) for t in texts]
    if max(lens) > min(lens) * max_ratio + slack:
        raise ValueError(f"варианты ответа слишком разной длины: {lens}")


def fmt(x: float, nd: int = 3) -> str:
    return f"{x:.{nd}f}"


def rows_literal(rows: Iterable[Sequence]) -> str:
    return "[" + ", ".join("(" + ", ".join(repr(v) for v in r) + ("," if len(r) == 1 else "") + ")"
                           for r in rows) + "]"


def sql_py_program(query: str, setup: str, expected_rows: list[tuple]) -> str:
    """Программа Python: исполнить запрос (дословно) на setup и сравнить строки с ожидаемыми."""
    if '"""' in query or "\\" in query:
        raise ValueError("запрос нельзя дословно вложить в строковый литерал")
    return ("import sqlite3\n\n"
            f'QUERY = """\n{query}\n"""\n\n'
            f"SETUP = {setup!r}\n"
            f"EXPECTED = {rows_literal(expected_rows)}\n"
            "con = sqlite3.connect(':memory:')\n"
            "con.executescript(SETUP)\n"
            "try:\n"
            "    got = [tuple(r) for r in con.execute(QUERY).fetchall()]\n"
            "except sqlite3.Error as e:\n"
            "    got = ['ERROR', str(e)]\n"
            "def same(a, b):\n"
            "    if isinstance(a, (int, float)) and isinstance(b, (int, float)):\n"
            "        return abs(a - b) < 1e-9\n"
            "    return a == b\n"
            "ok = len(got) == len(EXPECTED) and all(\n"
            "    len(r) == len(e) and all(same(x, y) for x, y in zip(r, e))\n"
            "    for r, e in zip(got, EXPECTED))\n"
            "print('RESULT: PASS' if ok else 'RESULT: FAIL')\n")


def balanced_options(family_id: str, seed: int, rng, correct, distractors, step=None, salt=""):
    """Как gen_utils.make_options, но позиция правильного ответа сбалансирована по блокам из
    len(варианты) подряд идущих seed: в каждом блоке ключ стоит на каждой позиции ровно один раз
    (перестановка блока — от sha256(family_id, номер блока)). Порядок дистракторов — от rng.
    Код банка открыт, поэтому предсказуемость позиции по seed ничего не добавляет к угрозе:
    по seed и так можно сгенерировать вариант вместе с ключом.
    """
    from assessment_bank.gen_utils import LETTERS, make_rng
    from assessment_bank.schema import Option

    items = [correct] + list(distractors)
    if len(set(items)) != len(items):
        raise ValueError("варианты ответа совпадают — генератор должен давать различные")
    n = len(items)
    perm = list(range(n))
    make_rng(family_id, seed // n, "keypos" + salt).shuffle(perm)
    pos = perm[seed % n]
    rest = list(distractors)
    rng.shuffle(rest)
    rest.insert(pos, correct)
    options = [Option(id=LETTERS[i], text=t, code=c, step=step) for i, (t, c) in enumerate(rest)]
    return options, LETTERS[pos]
