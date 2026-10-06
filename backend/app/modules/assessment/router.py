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

router = APIRouter(prefix="/api/assessment", tags=["assessment"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
candidate = require_role(UserRole.candidate)


class StartIn(BaseModel):
    claimed_grade: Literal["junior", "middle", "senior"] = Field(description="Предполагаемый грейд, выбранный кандидатом")
    integrity_ack: bool = Field(False, description="Кандидат прочитал, что отслеживается во время теста (потеря фокуса, "
                                                   "вставка текста, скорость, канарейки) и что сигналы только снижают "
                                                   "«достоверность результата». Сохраняется в сессии")


class OptionOut(BaseModel):
    id: str = Field(description="Идентификатор варианта (A–F); его и нужно прислать в ответе")
    text: str
    code: str | None = Field(None, description="Фрагмент кода варианта (для choose_fix и шагов open_book_3step)")


class ItemOut(BaseModel):
    """Задание без ключа, рубрики, семейства и seed. item_id — непрозрачный токен сессии."""

    item_id: str
    position: int = Field(description="Номер задания в сессии (с канарейками)")
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


class AnswerIn(BaseModel):
    item_id: str
    answer: Any = Field(description="option — id варианта (A–F); line — номер строки (с 1); text — строка ответа")
    step: int | None = Field(None, ge=1, le=3, description="Шаг open_book_3step (защита от двойной отправки)")
    time_spent_ms: int | None = Field(None, ge=0, le=7_200_000, description="Время по часам клиента (справочно)")
    signals: dict[str, int] | None = Field(
        None, description="Сигналы интерфейса теста за время задания (античит): focus_lost — потерь фокуса / "
                          "переключений вкладки, hidden_ms — время вне вкладки, paste — вставок текста, "
                          "paste_chars — вставлено символов. Влияют только на «достоверность результата»")


def _session_out(db, ts) -> SessionOut:
    item = service.next_item(db, ts)
    answered, total, can_finish = service.progress(ts)
    return SessionOut(
        session_id=ts.id, status=ts.status.value, direction=ts.direction_id, claimed_grade=ts.claimed_grade_id,
        engine=ts.result.get("engine", "?"), is_sandbox=ts.is_sandbox,
        deadline_at=ts.deadline_at.isoformat() if ts.deadline_at else None,
        item=ItemOut(**item.__dict__) if item else None, answered=answered, total=total,
        can_finish=can_finish or (item is None and ts.status.value == "in_progress"),
    )


@router.get("/status", summary="Категория и грейд: статус, история опроса и тестов, правило 90 дней",
            responses=AUTH)
def get_status(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.status(db, user.id)


@router.post(
    "/sessions", response_model=SessionOut, status_code=201,
    summary="Начать тест на выбранный грейд",
    description="Требует пройденного опроса. Адаптивный тест банка заданий: общий блок + блок направления, "
                "8–16 заданий (остановка по SE ≤ 0,35), до 60 минут, не больше 2 заданий open_book_3step; у порога грейда — ещё 3 задания. "
                "Смена подтверждённого грейда — не чаще раза в 90 дней (демо-режим жюри снимает ограничение, но число "
                "новых сессий в демо-режиме ограничено: JURY_MAX_TEST_STARTS_PER_DAY за 24 часа на учётку). "
                "Если активная сессия на тот же грейд уже есть — вернётся она.",
    responses={**AUTH, 409: err("onboarding_required — нет опроса; grade_locked — действует правило 90 дней"),
               422: err("Неизвестный грейд"), 429: err("sandbox_restarts_exhausted — лимит перезапусков в демо-режиме")},
)
def start(data: StartIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> SessionOut:
    survey = service.latest_survey(db, user.id)
    if survey is not None and survey.claimed_grade_id != data.claimed_grade:
        survey.claimed_grade_id = data.claimed_grade
    return _session_out(db, service.start_session(db, user.id, data.claimed_grade, integrity_ack=data.integrity_ack,
                                                  enforce_sandbox_quota=True))


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


@router.get("/feedback", summary="Обратная связь после теста: карта навыков, спрос работодателей, маршрут роста",
            description="Карта навыков по темам банка (без заданий и ключей), разрыв с требованиями активных потребностей "
                        "и вакансий в категории кандидата, маршрут роста и рекомендованные дисциплины ФСП. По умолчанию — "
                        "последний завершённый тест; session_id — конкретный.",
            responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Тест ещё не завершён")})
def get_feedback(session_id: uuid.UUID | None = None, user: User = Depends(candidate),
                 db: Session = Depends(get_db)) -> dict:
    from app.modules.assessment.feedback import build

    return build(db, user.id, session_id)
