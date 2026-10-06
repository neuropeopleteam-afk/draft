"""Правила смены грейда (чистые функции — покрыты тестами).

* Грейд не понижается принудительно: несданный тест не меняет подтверждённый грейд.
* Первое присвоение категории — без ограничений.
* Смена подтверждённого грейда (выше или ниже) — не чаще раза в 90 дней: после присвоения или смены
  ставится locked_until = now + 90 дней; до этой даты новый тест не начинается.
* «Демо-режим жюри» (настройка кандидата) или глобальная песочница DEMO_SANDBOX снимают ограничение,
  а запись в истории получает причину sandbox.
* «Junior (предварительно)» (решение владельца 06.10): тест на Junior не подтвердил грейд, но уровень ниже порога
  не доказан. Если подтверждённой категории нет — присваивается категория Junior со статусом «предварительно»
  (причина provisional). Это не подтверждённый грейд: правило 90 дней на него не ставится, любые тесты доступны.
  Подтверждение (дотестирование, повторный тест на Junior, зонд или кубок) — не смена грейда: причина confirmed,
  период 90 дней отсчитывается от даты, когда кандидат попал в категорию (новый период не начинается).
  Предварительный статус можно только подтвердить: неудачный тест его не снимает (принудительного понижения нет),
  а подтверждённую категорию предварительный результат не заменяет.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.db import as_aware

GRADE_LEVEL = {"junior": 1, "middle": 2, "senior": 3}


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
    reason: str | None  # initial | retest_up | retest_down | sandbox | provisional | confirmed | None
    locked_until: datetime | None
    message: str
    provisional: bool = False  # после результата категория — «предварительно»
    status_changed: bool = False  # предварительный → подтверждён (грейд тот же) или впервые «предварительно»


def confirmation_lock(since: datetime | None, now: datetime, interval_days: int = 90) -> datetime | None:
    """Период 90 дней после подтверждения предварительного Junior — от даты попадания в категорию."""
    start = as_aware(since) or now
    lock = start + timedelta(days=interval_days)
    return lock if lock > now else None


def apply_result(current_grade: str | None, claimed_grade: str, confirmed: bool, now: datetime, sandbox: bool,
                 interval_days: int = 90, current_lock: datetime | None = None, *, provisional: bool = False,
                 current_provisional: bool = False, provisional_since: datetime | None = None,
                 confirmed_elsewhere: str | None = None) -> GradeOutcome:
    """current_provisional — текущая категория (того же направления) «предварительно»; confirmed_elsewhere —
    подтверждённая категория другого направления (её предварительный результат не заменяет)."""
    lock = now + timedelta(days=interval_days)
    if current_provisional and current_grade:
        if confirmed and claimed_grade == current_grade:
            until = None if sandbox else confirmation_lock(provisional_since, now, interval_days)
            return GradeOutcome(False, current_grade, "sandbox" if sandbox else "confirmed", until,
                                f"Грейд {current_grade.capitalize()} подтверждён. Это не смена грейда: "
                                "новый период 90 дней не начинается.", status_changed=True)
        if confirmed:  # предварительный Junior → подтверждённый грейд выше: первое подтверждённое присвоение
            return GradeOutcome(True, claimed_grade, "sandbox" if sandbox else "initial", lock,
                                f"Присвоен грейд {claimed_grade.capitalize()}.", status_changed=True)
        return GradeOutcome(False, current_grade, None, current_lock,
                            f"Категория {current_grade.capitalize()} (предварительно) сохранена: результат её не "
                            "подтвердил, но и не снимает — принудительного понижения нет.", provisional=True)
    if not confirmed and provisional and not current_grade and not confirmed_elsewhere:
        return GradeOutcome(True, claimed_grade, "provisional", None,
                            f"Присвоена категория {claimed_grade.capitalize()} (предварительно): уровень ниже порога "
                            "не доказан. Подтвердите её коротким дотестированием у порога, зондом работодателя или "
                            "кубком — это не смена грейда.", provisional=True, status_changed=True)
    if not confirmed and provisional and confirmed_elsewhere:
        return GradeOutcome(False, None, None, current_lock,
                            f"Подтверждённая категория {confirmed_elsewhere} сохранена: предварительный результат "
                            "её не заменяет.")
    if not confirmed:
        if current_grade:
            return GradeOutcome(False, current_grade, None, current_lock,
                                f"Подтверждённый грейд {current_grade.capitalize()} сохранён: принудительного понижения нет.")
        return GradeOutcome(False, None, None, None, "Категория пока не присвоена — можно пройти тест на грейд ниже.")
    if current_grade is None:
        return GradeOutcome(True, claimed_grade, "sandbox" if sandbox else "initial", lock,
                            f"Присвоен грейд {claimed_grade.capitalize()}.")
    if current_grade == claimed_grade:
        return GradeOutcome(False, current_grade, None, current_lock,
                            f"Грейд {claimed_grade.capitalize()} подтверждён повторно, результат обновлён.")
    up = GRADE_LEVEL[claimed_grade] > GRADE_LEVEL[current_grade]
    reason = "sandbox" if sandbox else ("retest_up" if up else "retest_down")
    return GradeOutcome(True, claimed_grade, reason, lock,
                        f"Грейд изменён: {current_grade.capitalize()} → {claimed_grade.capitalize()}.")
