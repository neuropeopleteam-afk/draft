"""Правила смены грейда (чистые функции — покрыты тестами).

* Грейд не понижается принудительно: несданный тест не меняет подтверждённый грейд.
* Первое присвоение категории — без ограничений.
* Смена подтверждённого грейда (выше или ниже) — не чаще раза в 90 дней: после присвоения или смены
  ставится locked_until = now + 90 дней; до этой даты новый тест не начинается.
* Неподтверждённая попытка на грейд G: повтор теста на G и выше — не раньше чем через ``retake_days`` (30) дней
  (против «сегодня Junior, завтра Senior», видео организаторов №7, №20); тест на грейд ниже — сразу, без зачёта
  попыток. Если тест не подтвердил G, но уверенно (P ≥ 0,8) доказал уровень ниже, кандидат может принять его без
  нового теста (``accept_lower``) — принудительно уровень не понижается.
* «Демо-режим жюри» (настройка кандидата) или глобальная песочница DEMO_SANDBOX снимают ограничения,
  а запись в истории получает причину sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.db import as_aware

GRADE_LEVEL = {"junior": 1, "middle": 2, "senior": 3}
GRADE_RU = {"junior": "Junior", "middle": "Middle", "senior": "Senior"}


@dataclass
class StartCheck:
    allowed: bool
    code: str | None = None
    message: str | None = None
    available_at: datetime | None = None


def retake_locks(failed: dict[str, datetime] | None, now: datetime, retake_days: int) -> dict[str, datetime]:
    """Грейды, на которые сейчас нельзя начать тест из-за недавней неподтверждённой попытки → когда можно.

    failed — {грейд: время последней неподтверждённой попытки}. Попытка на G закрывает G и все грейды выше
    (тест на грейд ниже — сразу)."""
    out: dict[str, datetime] = {}
    for g, at in (failed or {}).items():
        at = as_aware(at)
        if g not in GRADE_LEVEL or at is None:
            continue
        until = at + timedelta(days=retake_days)
        if until <= now:
            continue
        for other, lvl in GRADE_LEVEL.items():
            if lvl >= GRADE_LEVEL[g] and (other not in out or out[other] < until):
                out[other] = until
    return out


def check_can_start(current_grade: str | None, locked_until: datetime | None, target_grade: str, now: datetime,
                    sandbox: bool, failed: dict[str, datetime] | None = None, retake_days: int = 30) -> StartCheck:
    if target_grade not in GRADE_LEVEL:
        return StartCheck(False, "unknown_grade", "Неизвестный грейд")
    if sandbox:
        return StartCheck(True)
    if current_grade is not None:
        lock = as_aware(locked_until)
        if lock and now < lock:
            return StartCheck(False, "grade_locked",
                              f"Сменить грейд можно не чаще раза в 90 дней. Следующая попытка — с {lock:%d.%m.%Y}.", lock)
    locks = retake_locks(failed, now, retake_days)
    if target_grade in locks:
        until = locks[target_grade]
        lower = [g for g, lvl in GRADE_LEVEL.items() if lvl < GRADE_LEVEL[target_grade] and g not in locks]
        hint = (f" Тест на {GRADE_RU[lower[-1]]} можно пройти сразу." if lower else "")
        return StartCheck(False, "retake_cooldown",
                          f"Повторить тест на {GRADE_RU[target_grade]} можно не раньше чем через {retake_days} дней "
                          f"после неподтверждённой попытки — с {until:%d.%m.%Y}.{hint}", until)
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


ACCEPT_LOWER_LEVEL = 0.8


def proved_lower(probabilities: dict[str, float] | None, claimed_grade: str, level: float = ACCEPT_LOWER_LEVEL) -> str | None:
    """Самый высокий грейд ниже заявленного, уровень которого тест доказал уверенно: P(θ ≥ порог) ≥ level.
    probabilities — {none, junior, middle, senior} из результата движка (вероятности точечного грейда)."""
    if not probabilities or claimed_grade not in GRADE_LEVEL:
        return None
    for g in sorted(GRADE_LEVEL, key=GRADE_LEVEL.get, reverse=True):
        if GRADE_LEVEL[g] >= GRADE_LEVEL[claimed_grade]:
            continue
        p_at_least = sum(float(v) for k, v in probabilities.items() if GRADE_LEVEL.get(k, 0) >= GRADE_LEVEL[g])
        if p_at_least >= level:
            return g
    return None


def accept_lower_allowed(current_grade: str | None, claimed_grade: str, confirmed: bool,
                         probabilities: dict[str, float] | None) -> tuple[str | None, str | None]:
    """Можно ли принять уровень ниже по этому тесту: тест не подтвердил заявленный грейд, но уверенно доказал
    уровень ниже (P ≥ 0,8), и этот уровень выше текущего подтверждённого (или категории ещё нет).
    Возвращает (доказанный грейд или None, причина отказа)."""
    if confirmed:
        return None, "confirmed"
    lower = proved_lower(probabilities, claimed_grade)
    if lower is None:
        return None, "no_lower_proved"
    if current_grade is not None and GRADE_LEVEL[lower] <= GRADE_LEVEL[current_grade]:
        return None, "not_above_current"
    return lower, None
