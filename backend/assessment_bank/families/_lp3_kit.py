"""Волна LP-3 (21.10.2026): содержательные расчётные задачи старших грейдов с вводом ответа.

Почему так (после проверки LP-v2): у Lead/Principal было 51 % и 82 % заданий с выбором ответа, а ключ LP-v2 не
менялся от варианта к варианту. Здесь формат ``predict_output``: кандидат вводит число (или короткую строку),
вариантов для угадывания нет, а сам правильный ответ меняется с каждым вариантом (его считает программа-модель
из тех же данных, что показаны кандидату). Данные кандидат видит блоком ``code`` (таблица, журнал, конфигурация),
программа-модель в проверке разбирает именно показанный текст — ключ не может разойтись с условием.

Требования к каждому семейству волны:
- задача — решение старшего инженера (бюджеты, отказоустойчивость, инциденты, компромиссы), а не арифметика
  по формуле из условия: формула не называется, «очевидный» подход (наивная ловушка) даёт другой ответ;
- в условии нет грейда, нет подсказки на ловушку;
- ответ — целое число (или короткая строка), допускаются равноценные записи (``accept``).
"""
from __future__ import annotations

from typing import Any

from assessment_bank.gen_utils import build_variant
from assessment_bank.schema import AnswerKey, Check


def py_block(name: str, text: str) -> str:
    """Присвоение многострочного текста переменной программы-модели (без проблем с кавычками)."""
    return f"{name} = {text!r}\n"


def typed_variant(fid: str, seed: int, *, stem: str, block: str, calc: str, out: str, expl: str, ctx: str,
                  params: dict[str, Any], accept: list[str] | None = None, block_name: str = "DATA",
                  note: str | None = None):
    """Вариант ``predict_output``: показанный блок данных + проверка исполнением модели над этим же блоком."""
    prog = py_block(block_name, block) + calc
    checks = [Check(name="model", runner="python", program=prog, expect="stdout_equals", expected_stdout=out,
                    embeds_display_code=False)]
    acc = sorted({a for a in (accept or []) if a and a != out})
    ak = AnswerKey(kind="output", value=out, accept=acc, explanation=expl)
    return build_variant(fid, seed, stem=stem, code=block, answer_key=ak, context=ctx, verification="execution",
                         checks=checks, language="text",
                         display_code_note=note or "Показаны данные задачи; программа-модель разбирает этот же текст.",
                         params=params)


def num_accept(n: int, unit_forms: tuple[str, ...] = ()) -> list[str]:
    """Равноценные записи целого ответа: с пробелом-разделителем тысяч и с единицей измерения."""
    s = str(n)
    forms = {s, f"{n:,}".replace(",", " ")}
    for u in unit_forms:
        forms |= {f"{f} {u}" for f in list(forms)}
    return sorted(forms)
