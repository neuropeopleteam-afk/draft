"""Помощники семейств добора 10.10 (ветка feat/bank-core-plus): ядро банка не меняют.

* ``fix_options_variant`` — choose_fix: показан код с дефектом, 4 варианта замены функции; каждый вариант
  исполняется на одних тестах (верен ровно один), показанный код с дефектом исполняется дословно и падает;
* ``line_bug_variant`` — find_bug: исправление меняет ровно одну строку, дефектный код падает, исправленный проходит;
* ``output_variant`` — predict_output: показанный код исполняется дословно, ключ — независимая модель в генераторе.

``prelude`` — общий для всех вариантов код (импорт, константы, подменные объекты), который в варианты ответа не
повторяется; в проверке показанного кода он не дублируется (показанный код уже содержит его).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_options, py_harness
from assessment_bank.schema import AnswerKey, Check


def _harness(runner: str, code: str, test: str) -> str:
    return py_harness(code, test) if runner == "python" else js_harness(code, test)


def fix_options_variant(fid, seed, rng, *, stem, buggy, correct, distractors, test, context, defect, why,
                        prelude="", runner="python", label="Заменить функцию на:", params=None, display_note=None):
    opts, key = make_options(rng, (label, correct), [(label, d) for d in distractors])
    joiner = "\n\n" if prelude else ""
    checks = [Check(name="buggy_fails", runner=runner, program=_harness(runner, buggy, test), expect="fail")]
    checks += [Check(name=f"option:{o.id}", runner=runner, expect="pass" if o.id == key else "fail",
                     program=_harness(runner, prelude + joiner + o.code, test), embeds_display_code=False)
               for o in opts]
    return build_variant(fid, seed, stem=stem, code=buggy, options=opts,
                         answer_key=AnswerKey(kind="option", value=key, explanation=why),
                         context=context, verification="execution", checks=checks, defect_type=defect,
                         display_code_note=display_note, params=params or {})


def line_bug_variant(fid, seed, *, stem, buggy, fixed, test, context, defect, why, runner="python",
                     params=None, display_note=None, extra_checks=None):
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1, ch
    line = next(iter(ch))
    checks = [Check(name="buggy_fails", runner=runner, program=_harness(runner, buggy, test), expect="fail"),
              Check(name="fixed_passes", runner=runner, program=_harness(runner, fixed, test), expect="pass",
                    embeds_display_code=False)]
    checks += extra_checks or []
    return build_variant(fid, seed, stem=stem, code=buggy,
                         answer_key=AnswerKey(kind="line", value=line, explanation=f"Строка {line}. {why}"),
                         context=context, verification="execution", checks=checks, defect_type=defect,
                         display_code_note=display_note, params={**(params or {}), "fixed_code": fixed})


def output_variant(fid, seed, *, stem, code, expected, context, why, runner="python", params=None,
                   display_note=None, defect=None):
    checks = [Check(name="run", runner=runner, program=code, expect="stdout_equals", expected_stdout=expected)]
    return build_variant(fid, seed, stem=stem, code=code,
                         answer_key=AnswerKey(kind="output", value=expected, explanation=why),
                         context=context, verification="execution", checks=checks, defect_type=defect,
                         display_code_note=display_note, params=params or {})
