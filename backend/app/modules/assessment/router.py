"""API теста и экрана «Категория и грейд» (кабинет кандидата)."""
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import err
from app.modules.assessment import service
from app.modules.auth.models import User
from app.modules.catalog.seed_data import GRADE_ORDER as _GRADE_ORDER

# уровни платформы: 4 (Стажёр–Senior), с флагом GRADES_EXT_ENABLED — 6 (+ Lead, Principal; catalog.levels)
GradeId = Literal[_GRADE_ORDER]  # type: ignore[valid-type]

router = APIRouter(prefix="/api/assessment", tags=["assessment"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
candidate = require_role(UserRole.candidate)


class StartIn(BaseModel):
    direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = Field(
        None, description="Направление опроса; без параметра — основное")
    claimed_grade: GradeId = Field(
        description="Предполагаемый грейд, выбранный кандидатом (intern — Стажёр, ниже Junior)")
    integrity_ack: bool = Field(False, description="Кандидат согласился с проверкой самостоятельности выполнения: "
                                                   "результат может получить пометку «достоверность результата». "
                                                   "Сохраняется в сессии с версией текста")
    mode: Literal["full", "express", "confirm"] = Field(
        "full", description="full — обычный адаптивный тест (8–16 заданий); "
                            "express — экспресс-тест для жюри: 5–7 коротких заданий, ≈ 5 минут "
                            "(за Senior — 8–12 заданий с лимитом до 6 мин), интервал θ шире, только в демо-режиме жюри; "
                            "confirm — короткое дотестирование у порога Junior для подтверждения категории "
                            "«Junior (предварительно)»: ответы прошлой попытки учитываются, добавляется до 6 коротких "
                            "заданий (до 20 минут), не больше 2 попыток")


class OptionOut(BaseModel):
    id: str = Field(description="Идентификатор варианта (A–F); его и нужно прислать в ответе")
    text: str
    code: str | None = Field(None, description="Фрагмент кода варианта (для choose_fix и шагов open_book_3step)")


class ItemOut(BaseModel):
    """Задание без ключа, рубрики, семейства и seed. item_id — непрозрачный токен сессии."""

    item_id: str
    position: int = Field(description="Номер задания в сессии")
    total: int = Field(description="Ориентир общего числа заданий (адаптивный тест может закончиться раньше)")
    format: str = Field(description="find_bug | predict_output | choose_fix | open_book_3step | mcq_concept | open_answer")
    stem: str
    options: list[OptionOut] | None = None
    code: str | None = None
    code_language: str | None = None
    time_limit_s: int = Field(description="Рекомендуемое время на задание; время ответа фиксирует сервер")
    skills: list[str]
    answer_kind: Literal["option", "line", "text"] = Field(
        "option", description="option — id варианта; line — номер строки кода с дефектом; text — текст ответа")
    step: int | None = Field(None, description="open_book_3step: текущий шаг 1–3 (шаги открываются по очереди)")
    steps_total: int | None = None
    step_prompt: str | None = None
    elapsed_s: int = Field(0, description="Сколько секунд прошло с момента показа задания (по часам сервера)")
    block: str = Field("direction", description="common — общий блок; direction — блок направления")
    adaptive: bool = False
    min_items: int | None = None
    max_items: int | None = None
    answered: int = 0
    extension: bool = Field(False, description="Задание дотестирования: результат у порога грейда")


class SessionOut(BaseModel):
    session_id: uuid.UUID
    status: str
    direction: str
    claimed_grade: str
    engine: str
    is_sandbox: bool
    deadline_at: str | None
    item: ItemOut | None = Field(None, description="Следующее задание; null — тест окончен, вызовите finish")
    answered: int
    total: int
    can_finish: bool = Field(False, description="Тест окончен по правилам движка (SE, лимит заданий/времени)")
    mode: str = Field("full", description="full — полный тест; express — экспресс-тест жюри; confirm — дотестирование "
                                          "для подтверждения «Junior (предварительно)»")


class AnswerIn(BaseModel):
    item_id: str
    answer: Any = Field(description="option — id варианта (A–F); line — номер строки (с 1); text — строка ответа")
    step: int | None = Field(None, ge=1, le=3, description="Шаг open_book_3step (защита от двойной отправки)")
    time_spent_ms: int | None = Field(None, ge=0, le=7_200_000, description="Время по часам клиента (справочно)")
    signals: dict[str, int] | None = Field(
        None, description="Служебные счётчики интерфейса теста за время задания. Влияют только на «достоверность "
                          "результата», не на оценку")


def _session_out(db, ts) -> SessionOut:
    item = service.next_item(db, ts)
    answered, total, can_finish = service.progress(ts)
    return SessionOut(
        session_id=ts.id, status=ts.status.value, direction=ts.direction_id, claimed_grade=ts.claimed_grade_id,
        engine=ts.result.get("engine", "?"), is_sandbox=ts.is_sandbox,
        deadline_at=ts.deadline_at.isoformat() if ts.deadline_at else None,
        item=ItemOut(**item.__dict__) if item else None, answered=answered, total=total,
        can_finish=can_finish or (item is None and ts.status.value == "in_progress"),
        mode=service._mode(ts),
    )


@router.get("/status", summary="Категория и грейд: статус, история опроса и тестов, правило 90 дней",
            responses=AUTH)
def get_status(direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = None,
               user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.status(db, user.id, direction)


@router.post(
    "/sessions", response_model=SessionOut, status_code=201,
    summary="Начать тест на выбранный грейд",
    description="Требует пройденного опроса. Адаптивный тест банка заданий: общий блок + блок направления, "
                "8–16 заданий (остановка по SE ≤ 0,35), до 60 минут, не больше 2 заданий open_book_3step; у порога грейда — ещё 3 задания. "
                "Смена подтверждённого грейда — не чаще раза в 90 дней; повтор после неподтверждённой попытки на тот же "
                "грейд и выше — не раньше чем через RETAKE_SAME_GRADE_DAYS (30) дней, на грейд ниже — сразу. Демо-режим "
                "жюри снимает ограничения, но число новых сессий в нём ограничено: JURY_MAX_TEST_STARTS_PER_DAY за 24 часа "
                "на учётку. mode=express (только демо-режим) — экспресс-тест 5–7 коротких заданий (за Senior — 8–12); "
                "mode=confirm — дотестирование «Junior (предварительно)». "
                "Если активная сессия на тот же грейд и режим уже есть — вернётся она.",
    responses={**AUTH, 409: err("onboarding_required — нет опроса; grade_locked — правило 90 дней; retake_cooldown — "
                                "повтор на тот же грейд раньше 30 дней; express_sandbox_only — экспресс вне демо-режима; "
                                "not_provisional / confirm_unavailable — дотестирование недоступно"),
               422: err("Неизвестный грейд"), 429: err("sandbox_restarts_exhausted — лимит перезапусков в демо-режиме")},
)
def start(data: StartIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> SessionOut:
    survey = service.latest_survey(db, user.id, data.direction)
    if survey is not None and survey.claimed_grade_id != data.claimed_grade:
        survey.claimed_grade_id = data.claimed_grade
    return _session_out(db, service.start_session(db, user.id, data.claimed_grade, integrity_ack=data.integrity_ack,
                                                  enforce_sandbox_quota=True, direction=data.direction,
                                                  mode=data.mode))


@router.get("/grade-hint", summary="Подсказка грейда по опросу, резюме и паспорту ФСП (необязательная, по правилам)",
            description="Каждый сигнал — отдельно, с источником и объяснением; итог — предполагаемый грейд и уверенность. "
                        "Без LLM. Выбор грейда остаётся за кандидатом, категорию присваивает только тест.",
            responses=AUTH)
def get_grade_hint(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    from app.modules.assessment.grade_hint import grade_hint

    return grade_hint(db, user.id)


@router.get("/sessions/{session_id}", response_model=SessionOut, summary="Сессия теста и следующее задание",
            responses={**AUTH, 404: err("Сессия не найдена или чужая")})
def get_session(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> SessionOut:
    return _session_out(db, service.get_own_session(db, user.id, session_id, lock=True))


@router.post("/sessions/{session_id}/answers", response_model=SessionOut, summary="Ответ на задание",
             responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Сессия закрыта или время истекло"),
                        422: err("Ответ не принят")})
def answer(session_id: uuid.UUID, data: AnswerIn, user: User = Depends(candidate),
           db: Session = Depends(get_db)) -> SessionOut:
    ts = service.get_own_session(db, user.id, session_id, lock=True)
    service.submit_answer(db, ts, data.item_id, data.answer, data.time_spent_ms, data.step, data.signals)
    return _session_out(db, ts)


@router.post("/sessions/{session_id}/finish", summary="Завершить тест: θ, SE, решение по грейду, категория",
             description="Доступно, когда движок закончил тест (item = null). Открытые ответы, которые не удалось "
                         "оценить LLM, остаются «на проверке» и в θ пока не входят.",
             responses={**AUTH, 404: err("Сессия не найдена"),
                        409: err("session_closed — сессия закрыта; test_not_complete — тест ещё не окончен")})
def finish(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.finish_session(db, service.get_own_session(db, user.id, session_id, lock=True))


@router.get("/sessions/{session_id}/result", summary="Итог завершённого теста (как после finish)",
            responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Тест ещё не завершён")})
def get_result(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.result(db, service.get_own_session(db, user.id, session_id))


@router.post("/sessions/{session_id}/accept-lower",
             summary="Принять уровень ниже по этому тесту (заявленный грейд не подтверждён, уровень ниже доказан с P ≥ 0,8)",
             description="Одно действие кандидата вместо нового теста (видео организаторов №7). Категория присваивается "
                         "по доказанному уровню; принудительно уровень не понижается — только по этому запросу. "
                         "Повторный вызов — 409 already_accepted.",
             responses={**AUTH, 404: err("Сессия не найдена"),
                        409: err("test_not_finished | already_accepted | accept_lower_unavailable")})
def accept_lower(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.accept_lower_grade(db, service.get_own_session(db, user.id, session_id, lock=True))


@router.get("/feedback", summary="Обратная связь после теста: карта навыков, спрос работодателей, маршрут роста",
            description="Карта навыков по темам банка (без заданий и ключей), разрыв с требованиями активных потребностей "
                        "и вакансий в категории кандидата, маршрут роста и рекомендованные дисциплины ФСП. По умолчанию — "
                        "последний завершённый тест основного направления; session_id — конкретный тест любого направления.",
            responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Тест ещё не завершён")})
def get_feedback(session_id: uuid.UUID | None = None, user: User = Depends(candidate),
                 db: Session = Depends(get_db)) -> dict:
    from app.modules.assessment.feedback import build

    return build(db, user.id, session_id)


# --- И26: две попытки теста рядом (логика — attempts.py; работодателю — attempts.employer_router) ---
@router.get("/attempts", summary="Две попытки теста рядом: θ ± погрешность, статус, время, повторы заданий, что изменилось",
            description="По умолчанию — две последние завершённые попытки направления (без параметра — основного); "
                        "a и b — конкретные попытки (только свои: чужая — 404). Повторы — по новым оценённым "
                        "заданиям без контрольных. В демо-режиме жюри повтор доступен сразу (can_retake_now).",
            responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Попытка ещё не завершена"),
                       422: err("different_directions / same_attempt / pair_required")})
def get_attempts(direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = None,
                 a: uuid.UUID | None = None, b: uuid.UUID | None = None,
                 user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    from app.modules.assessment.attempts import for_candidate

    return for_candidate(db, user.id, direction, a, b)
