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


class ItemOut(BaseModel):
    item_id: str
    position: int
    total: int
    format: str
    stem: str
    options: list[str] | None = None
    code: str | None = None
    code_language: str | None = None
    time_limit_s: int
    skills: list[str]


class SessionOut(BaseModel):
    session_id: uuid.UUID
    status: str
    direction: str
    claimed_grade: str
    engine: str
    is_sandbox: bool
    deadline_at: str | None
    item: ItemOut | None = Field(None, description="Следующее задание; null — все задания отвечены, вызовите finish")
    answered: int
    total: int


class AnswerIn(BaseModel):
    item_id: str
    answer: Any = Field(description="Для закрытых форматов — индекс показанного варианта (0..n-1)")
    time_spent_ms: int | None = Field(None, ge=0, le=3_600_000)


def _session_out(ts) -> SessionOut:
    item = service.next_item(ts)
    st = ts.result.get("state", {})
    total = len(st.get("item_ids", [])) or (item.total if item else 0)
    return SessionOut(
        session_id=ts.id, status=ts.status.value, direction=ts.direction_id, claimed_grade=ts.claimed_grade_id,
        engine=ts.result.get("engine", "?"), is_sandbox=ts.is_sandbox,
        deadline_at=ts.deadline_at.isoformat() if ts.deadline_at else None,
        item=ItemOut(**item.__dict__) if item else None, answered=len(st.get("answers", {})), total=total,
    )


@router.get("/status", summary="Категория и грейд: статус, история опроса и тестов, правило 90 дней",
            responses=AUTH)
def get_status(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.status(db, user.id)


@router.post(
    "/sessions", response_model=SessionOut, status_code=201,
    summary="Начать тест на выбранный грейд",
    description="Требует пройденного опроса. Смена подтверждённого грейда — не чаще раза в 90 дней "
                "(демо-режим жюри снимает ограничение). Если активная сессия на тот же грейд уже есть — вернётся она.",
    responses={**AUTH, 409: err("onboarding_required — нет опроса; grade_locked — действует правило 90 дней"),
               422: err("Неизвестный грейд")},
)
def start(data: StartIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> SessionOut:
    survey = service.latest_survey(db, user.id)
    if survey is not None and survey.claimed_grade_id != data.claimed_grade:
        survey.claimed_grade_id = data.claimed_grade
    return _session_out(service.start_session(db, user.id, data.claimed_grade))


@router.get("/sessions/{session_id}", response_model=SessionOut, summary="Сессия теста и следующее задание",
            responses={**AUTH, 404: err("Сессия не найдена или чужая")})
def get_session(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> SessionOut:
    return _session_out(service.get_own_session(db, user.id, session_id))


@router.post("/sessions/{session_id}/answers", response_model=SessionOut, summary="Ответ на задание",
             responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Сессия закрыта или время истекло"),
                        422: err("Ответ не принят")})
def answer(session_id: uuid.UUID, data: AnswerIn, user: User = Depends(candidate),
           db: Session = Depends(get_db)) -> SessionOut:
    ts = service.get_own_session(db, user.id, session_id)
    service.submit_answer(db, ts, data.item_id, data.answer, data.time_spent_ms)
    return _session_out(ts)


@router.post("/sessions/{session_id}/finish", summary="Завершить тест: θ, SE, решение по грейду, категория",
             responses={**AUTH, 404: err("Сессия не найдена"), 409: err("Сессия уже закрыта")})
def finish(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return service.finish_session(db, service.get_own_session(db, user.id, session_id))
