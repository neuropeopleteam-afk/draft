"""Экран эксперта: развёрнутые ответы «на проверке» и выборочная проверка оценок LLM (роль admin = эксперт)."""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.modules.assessment import review
from app.modules.auth.models import User

router = APIRouter(prefix="/api/expert", tags=["expert"])
# Отдельная роль эксперта (и администратор). Демо-эксперт жюри (is_demo) работает только с демо-кандидатами.
expert = require_role(UserRole.expert, UserRole.admin)


class ReviewIn(BaseModel):
    session_id: uuid.UUID
    token: str = Field(..., max_length=64)
    part: int = Field(..., ge=0, le=2)
    criteria: dict[str, float] = Field(..., description="Оценка по каждому критерию рубрики: 0, 0.5 или 1")
    comment: str | None = Field(None, max_length=2000)


@router.get("/queue", summary="Очередь развёрнутых ответов")
def get_queue(mode: Literal["pending", "llm", "reviewed"] = Query("pending"), db: Session = Depends(get_db),
              user: User = Depends(expert)):
    return review.queue(db, mode, demo_only=user.is_demo)


@router.post("/review", summary="Оценка ответа по рубрике")
def post_review(data: ReviewIn, db: Session = Depends(get_db), user: User = Depends(expert)):
    return review.submit(db, data.session_id, data.token, data.part, data.criteria, data.comment, user.email,
                         demo_only=user.is_demo)


@router.get("/agreement", summary="Согласие LLM и экспертов")
def get_agreement(db: Session = Depends(get_db), user: User = Depends(expert)):
    return review.agreement(db)
