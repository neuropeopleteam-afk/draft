"""Правила смены грейда (чистые функции — покрыты тестами).

* Грейд не понижается принудительно: несданный тест не меняет подтверждённый грейд.
* Первое присвоение категории — без ограничений.
* Смена подтверждённого грейда (выше или ниже) — не чаще раза в 90 дней: после присвоения или смены
  ставится locked_until = now + 90 дней; до этой даты новый тест не начинается.
* «Демо-режим жюри» (настройка кандидата) или глобальная песочница DEMO_SANDBOX снимают ограничение,
  а запись в истории получает причину sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.db import as_aware
from app.modules.catalog.seed_data import GRADE_LEVEL, GRADES


@dataclass
class StartCheck:
    allowed: bool
    code: str | None = None
    message: str | None = None
    available_at: datetime | None = None


def check_can_start(current_grade: str | None, locked_until: datetime | None, target_grade: str, now: datetime,
                    sandbox: bool) -> StartCheck:
    if target_grade not in GRADE_LEVEL:
        return StartCheck(False, "unknown_grade", "Неизвестный грейд")
    if current_grade is None:
        return StartCheck(True)
    lock = as_aware(locked_until)
    if lock and now < lock and not sandbox:
        return StartCheck(False, "grade_locked",
                          f"Сменить грейд можно не чаще раза в 90 дней. Следующая попытка — с {lock:%d.%m.%Y}.", lock)
    return StartCheck(True)


@dataclass
class GradeOutcome:
    changed: bool
    new_grade: str | None
    reason: str | None  # initial | retest_up | retest_down | sandbox | None
    locked_until: datetime | None
    message: str


def apply_result(current_grade: str | None, claimed_grade: str, confirmed: bool, now: datetime, sandbox: bool,
                 interval_days: int = 90, current_lock: datetime | None = None) -> GradeOutcome:
    lock = now + timedelta(days=interval_days)
    if not confirmed:
        if current_grade:
            return GradeOutcome(False, current_grade, None, current_lock,
                                f"Подтверждённый грейд {GRADES.get(current_grade, current_grade)} сохранён: принудительного понижения нет.")
        return GradeOutcome(False, None, None, None, "Категория пока не присвоена — можно пройти тест на грейд ниже.")
    if current_grade is None:
        return GradeOutcome(True, claimed_grade, "sandbox" if sandbox else "initial", lock,
                            f"Присвоен грейд {GRADES.get(claimed_grade, claimed_grade)}.")
    if current_grade == claimed_grade:
        return GradeOutcome(False, current_grade, None, current_lock,
                            f"Грейд {GRADES.get(claimed_grade, claimed_grade)} подтверждён повторно, результат обновлён.")
    up = GRADE_LEVEL[claimed_grade] > GRADE_LEVEL[current_grade]
    reason = "sandbox" if sandbox else ("retest_up" if up else "retest_down")
    return GradeOutcome(True, claimed_grade, reason, lock,
                        f"Грейд изменён: {GRADES.get(current_grade, current_grade)} → {GRADES.get(claimed_grade, claimed_grade)}.")
