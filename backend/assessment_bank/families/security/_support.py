"""Локальные помощники security; не расширяют схему и не меняют ядро банка."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_options, py_harness
from assessment_bank.schema import AnswerKey, Check

CONTEXTS = [
    "учебный сервис заявок", "учебный каталог курсов", "учебный кабинет редактора",
    "учебный архив документов", "учебный сервис бронирований", "учебная служба поддержки",
    "учебный каталог оборудования", "учебный сервис отчётов",
]
SQL_NAMES = ["План 'Весна'", "Отчёт 'Север'", "Курс 'Старт'", "Набор 'Практика'",
             "Папка 'Общее'", "Заказ 'Архив'", "Шаблон 'Зима'", "Пакет 'Задачи'"]
SOURCES = {
    "coding": "https://cheatsheetseries.owasp.org/cheatsheets/Secure_Product_Design_Cheat_Sheet.html",
    "password": "https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html",
    "crypto": "https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html",
    "csrf": "https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html",
    "cvss": "https://www.first.org/cvss/v3.1/specification-document",
    "pickle": "https://docs.python.org/3.12/library/pickle.html",
}


def bug_variant(fid, seed, *, stem, buggy, fixed, test, context, defect, params=None):
    lines = changed_lines(buggy, fixed)
    assert len(lines) == 1, lines
    line = next(iter(lines))
    checks = [
        Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
        Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
              expect="pass", embeds_display_code=False),
    ]
    return build_variant(
        fid, seed, stem=stem, code=buggy, answer_key=AnswerKey(
            kind="line", value=line, explanation=f"Строка {line}. {params['why']}"),
        context=context, verification="execution", checks=checks, defect_type=defect,
        params={**(params or {}), "fixed_code": fixed},
    )


def fix_variant(fid, seed, rng, *, stem, buggy, correct, distractors, test, context,
                defect, why, runner="python", params=None, extra_checks=None):
    opts, key = make_options(
        rng, ("Заменить функцию целиком:", correct),
        [("Заменить функцию целиком:", d) for d in distractors],
    )
    harness = py_harness if runner == "python" else js_harness
    checks = [Check(name="buggy_fails", runner=runner, program=harness(buggy, test), expect="fail")]
    checks += [
        Check(name=f"option:{o.id}", runner=runner, program=harness(o.code, test),
              expect="pass" if o.id == key else "fail", embeds_display_code=False)
        for o in opts
    ]
    checks += extra_checks or []
    return build_variant(
        fid, seed, stem=stem, code=buggy, options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=why),
        context=context, verification="execution", checks=checks, defect_type=defect,
        params=params or {},
    )
