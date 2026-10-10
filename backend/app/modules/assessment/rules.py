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
from app.modules.catalog.seed_data import GRADE_LEVEL, GRADES

GRADE_RU = GRADES  # шкала платформы со Стажёром (intern) — названия из каталога


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


ACCEPT_LOWER_LEVEL = 0.8


def proved_lower(probabilities: dict[str, float] | None, claimed_grade: str, level: float = ACCEPT_LOWER_LEVEL) -> str | None:
    """Самый высокий грейд ниже заявленного, уровень которого тест доказал уверенно: P(θ ≥ порог) ≥ level.
    probabilities — {none, intern, junior, middle, senior} из результата движка (вероятности точечного грейда)."""
    if not probabilities or claimed_grade not in GRADE_LEVEL:
        return None
    for g in sorted(GRADE_LEVEL, key=GRADE_LEVEL.get, reverse=True):
        if GRADE_LEVEL[g] >= GRADE_LEVEL[claimed_grade]:
            continue
        # «none» (ниже всех порогов, в том числе Стажёра) в «не ниже g» не входит
        p_at_least = sum(float(v) for k, v in probabilities.items() if GRADE_LEVEL.get(k, -1) >= GRADE_LEVEL[g])
        if p_at_least >= level:
            return g
    return None


def accept_lower_allowed(current_grade: str | None, claimed_grade: str, confirmed: bool,
                         probabilities: dict[str, float] | None, *, provisional: bool = False,
                         level: float = ACCEPT_LOWER_LEVEL) -> tuple[str | None, str | None]:
    """Можно ли принять уровень ниже по этому тесту: тест не подтвердил заявленный грейд, но уверенно доказал
    уровень ниже (P ≥ 0,8), и этот уровень выше текущего подтверждённого (или категории ещё нет).
    Предварительный грейд (provisional, консилиум 07.10 п. 7.3в) — не подтверждённый: сравнение идёт как при
    отсутствии категории, поэтому у «Junior (предварительно)» доказанный Стажёр принимается.
    Возвращает (доказанный грейд или None, причина отказа)."""
    if confirmed:
        return None, "confirmed"
    lower = proved_lower(probabilities, claimed_grade, level)
    if lower is None:
        return None, "no_lower_proved"
    if provisional:
        current_grade = None
    if current_grade is not None and GRADE_LEVEL[lower] <= GRADE_LEVEL[current_grade]:
        return None, "not_above_current"
    return lower, None
