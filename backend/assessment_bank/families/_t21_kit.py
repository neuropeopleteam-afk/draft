"""Набор t21 (21.10.2026): короткие практические задания у порогов грейдов — по списку А4
(docs/validation/BANK_INFO_CUTS.md, ветка ag/a4-method): «где у порога не хватает информации».

Зачем. Практическое задание без вариантов ответа (a = 1,3 по шкале банка, угадать нельзя) даёт у порога примерно
в 2,7 раза больше информации, чем вопрос с выбором (a = 1,0, угадывание 1/4), а короткое (лимит 120–150 с) — ещё и
вдвое больше на минуту теста. Поэтому точность вердикта у порога определяется числом таких заданий рядом с ним.

Формат — predict_output: кандидат вводит вывод показанной программы (несколько строк — по строкам).
Априорные параметры (до калибровки на людях): a = 1,3; σ варианта 0,3; b — порог грейда с содержательной поправкой
не дальше ±0,3 (Стажёр −1,75, Junior −1,0, Middle 0,0, Senior +1,0, Lead +2,0, Principal +3,0).

Правила набора (общие для всех семейств t21_*):
* ключ считает независимая модель в генераторе (Python); проверка — исполнение ПОКАЗАННОГО кода в песочнице банка
  (python / node / sqlite / bash) и сравнение вывода с ключом (валидатор: checks + embeds_display_code);
* все случайные величины — из rng = make_rng(FAMILY_ID, seed); остатки зерна (seed % n, seed // n) в видимых
  числах и подписях запрещены — по ним открытый код восстанавливает зерно;
* ответ меняется от варианта к варианту; условие не содержит ответа и признаков уровня («для стажёра» и т. п.);
* код короткий (стажёр — 4–8 строк, junior — 5–10, middle — 6–14, senior — 8–18), без внешних пакетов.
"""
from __future__ import annotations

from typing import Any

from assessment_bank.gen_utils import build_variant
from assessment_bank.schema import AnswerKey, Check, Variant

RUNNER = {"python": "python", "javascript": "node", "sql": "sqlite", "bash": "bash"}

STEM_TAIL = {
    "python": "Что выведет программа? Запишите вывод так, как он появится в терминале, — по строкам.",
    "javascript": "Что выведет программа (Node.js)? Запишите вывод так, как он появится в консоли, — по строкам.",
    "sql": ("Что вернёт запрос? Запишите строки результата по порядку, по одной в строке, значения через «|» "
            "(например: `Анна|2`); отсутствующее значение записывайте как NULL."),
    "bash": "Что выведет скрипт (bash)? Запишите вывод так, как он появится в терминале, — по строкам.",
}


def output_variant(family_id: str, seed: int, *, stem: str, code: str, out: str, explanation: str, context: str,
                   params: dict[str, Any], language: str, files: dict[str, str] | None = None,
                   accept: list[str] | None = None, program: str | None = None, tail: bool = True) -> Variant:
    """Вариант predict_output: ключ ``out`` (посчитан моделью генератора) сверяется исполнением кода в песочнице.

    ``program`` — программа проверки (по умолчанию — ровно показанный код; для sql — запрос, данные в files["setup.sql"]).
    ``tail`` — дописать к условию стандартную просьбу о формате ответа для языка."""
    runner = RUNNER[language]
    prog = code if program is None else program
    if tail:
        stem = stem.rstrip() + "\n\n" + STEM_TAIL[language]
    ak = AnswerKey(kind="output", value=out, accept=list(accept or []), explanation=explanation)
    embeds = (prog == code) if runner == "sqlite" else (code in prog)
    checks = [Check(name="stdout", runner=runner, program=prog, files=dict(files or {}), expect="stdout_equals",
                    expected_stdout=out, embeds_display_code=embeds)]
    return build_variant(family_id, seed, stem=stem, code=code, answer_key=ak, context=context,
                         verification="execution", checks=checks, params=params, language=language)
