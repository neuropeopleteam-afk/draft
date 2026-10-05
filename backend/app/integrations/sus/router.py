"""Опрос SUS (System Usability Scale, Brooke 1996): 10 стандартных утверждений, шкала 1–5, балл 0–100.

Балл = 2,5 × (Σ(нечётные − 1) + Σ(5 − чётные)). Интерпретация: 68 — средний уровень по отрасли
(Sauro & Lewis), шкала прилагательных — Bangor, Kortum, Miller (2009).

Для страницы /validation (другой модуль): ``GET /api/sus/summary`` — только агрегаты, без ответов отдельных людей.
"""
from __future__ import annotations

import math
import statistics

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import oauth2_scheme, require_role
from app.core.enums import UserRole
from app.core.errors import err
from app.integrations.fsp_id.router import _optional_user
from app.integrations.sus.models import SusResponse
from app.modules.auth.models import User

router = APIRouter(prefix="/api/sus", tags=["sus"])
admin_router = APIRouter(prefix="/api/admin", tags=["sus"])
admin = require_role(UserRole.admin)

QUESTIONS = [
    "Думаю, что я хотел(а) бы пользоваться этой системой регулярно.",
    "Система показалась мне излишне сложной.",
    "Система была простой в использовании.",
    "Думаю, мне понадобится помощь технического специалиста, чтобы пользоваться этой системой.",
    "Разные функции системы хорошо связаны между собой.",
    "В системе слишком много несогласованности.",
    "Думаю, большинство людей очень быстро научатся пользоваться этой системой.",
    "Пользоваться системой было очень неудобно.",
    "Я чувствовал(а) себя уверенно, пользуясь системой.",
    "Мне пришлось многому научиться, прежде чем я смог(ла) начать пользоваться системой.",
]
SCALE = {1: "Полностью не согласен", 2: "Скорее не согласен", 3: "Нейтрально", 4: "Скорее согласен",
         5: "Полностью согласен"}


def sus_score(answers: list[int]) -> float:
    if len(answers) != 10 or any(a not in (1, 2, 3, 4, 5) for a in answers):
        raise ValueError("Нужно 10 ответов от 1 до 5")
    odd = sum(a - 1 for a in answers[0::2])
    even = sum(5 - a for a in answers[1::2])
    return (odd + even) * 2.5


def adjective(score: float) -> str:
    """Шкала прилагательных Bangor et al. (2009), пороги по средним значениям групп."""
    if score >= 85.5:
        return "отлично"
    if score >= 71.4:
        return "хорошо"
    if score >= 50.9:
        return "удовлетворительно"
    if score >= 35.7:
        return "плохо"
    return "очень плохо"


def grade(score: float) -> str:
    """Шкала оценок Sauro & Lewis (curved grading scale)."""
    for g, lo in (("A+", 84.1), ("A", 80.8), ("A−", 78.9), ("B+", 77.2), ("B", 74.1), ("B−", 72.6),
                  ("C+", 71.1), ("C", 65.0), ("C−", 62.7), ("D", 51.7)):
        if score >= lo:
            return g
    return "F"


@router.get("/questions", summary="10 стандартных утверждений SUS (русская версия) и шкала ответов")
def questions() -> dict:
    return {"questions": [{"n": i + 1, "text": q, "positive": i % 2 == 0} for i, q in enumerate(QUESTIONS)],
            "scale": SCALE, "formula": "2,5 × (Σ(ответы на нечётные − 1) + Σ(5 − ответы на чётные))"}


class SusIn(BaseModel):
    answers: list[int] = Field(min_length=10, max_length=10)
    context: str = Field("e2e", pattern="^(e2e|jury|pilot|other)$")
    comment: str | None = Field(None, max_length=2000)

    @field_validator("answers")
    @classmethod
    def _range(cls, v: list[int]) -> list[int]:
        if any(a < 1 or a > 5 for a in v):
            raise ValueError("Ответы — числа от 1 до 5")
        return v


@router.post("", status_code=201, summary="Сохранить анкету SUS (вход не обязателен — для жюри и гостей)",
             responses={422: err("Нужно 10 ответов от 1 до 5")})
def submit(data: SusIn, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    user = _optional_user(token, db)
    role = user.role.value if user else ("jury" if data.context == "jury" else "guest")
    if user and data.context == "jury":
        role = "jury"
    score = sus_score(data.answers)
    r = SusResponse(user_id=user.id if user else None, role=role, context=data.context, answers=data.answers,
                    score=score, comment=(data.comment or "").strip() or None, is_demo=bool(user and user.is_demo))
    db.add(r)
    db.commit()
    return {"id": str(r.id), "score": score, "adjective": adjective(score), "grade": grade(score),
            "benchmark": 68.0, "above_benchmark": score >= 68}


@router.get("/mine", summary="Отвечал ли текущий пользователь (чтобы не спрашивать повторно)")
def mine(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    user = _optional_user(token, db)
    if user is None:
        return {"answered": False}
    last = db.scalar(select(SusResponse).where(SusResponse.user_id == user.id).order_by(SusResponse.created_at.desc()))
    return {"answered": last is not None, "score": last.score if last else None,
            "at": last.created_at.isoformat() if last else None}


def _stats(scores: list[float]) -> dict:
    n = len(scores)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "sd": None, "ci95": None}
    mean = statistics.fmean(scores)
    sd = statistics.stdev(scores) if n > 1 else 0.0
    # t-квантиль для малых выборок (двусторонний 95 %), дальше — нормальное приближение
    t = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23, 15: 2.13,
         20: 2.09, 30: 2.04}
    df = n - 1
    tq = t.get(df) or next((v for k, v in sorted(t.items()) if k >= df), 1.96) if df > 0 else None
    half = tq * sd / math.sqrt(n) if tq else None
    return {"n": n, "mean": round(mean, 1), "median": round(statistics.median(scores), 1), "sd": round(sd, 1),
            "ci95": [round(max(0, mean - half), 1), round(min(100, mean + half), 1)] if half is not None else None}


@router.get("/summary", summary="Агрегаты SUS для /validation: среднее, медиана, ДИ 95 %, разрезы по ролям и контексту",
            description="Публичный эндпоинт без персональных данных. include_demo=false исключает ответы демо-учёток.")
def summary(include_demo: bool = Query(True), db: Session = Depends(get_db)) -> dict:
    stmt = select(SusResponse)
    if not include_demo:
        stmt = stmt.where(SusResponse.is_demo.is_(False))
    rows = db.scalars(stmt).all()
    scores = [r.score for r in rows]
    overall = _stats(scores)
    by = lambda attr: {k: _stats([r.score for r in rows if getattr(r, attr) == k])  # noqa: E731
                       for k in sorted({getattr(r, attr) for r in rows})}
    items = [round(statistics.fmean(r.answers[i] for r in rows), 2) if rows else None for i in range(10)]
    bins = [0] * 10
    for s in scores:
        bins[min(9, int(s // 10))] += 1
    return {**overall, "adjective": adjective(overall["mean"]) if overall["mean"] is not None else None,
            "grade": grade(overall["mean"]) if overall["mean"] is not None else None,
            "benchmark": 68.0, "by_role": by("role"), "by_context": by("context"), "items_mean": items,
            "histogram": [{"from": i * 10, "to": i * 10 + 10, "n": b} for i, b in enumerate(bins)],
            "updated_at": max((r.created_at.isoformat() for r in rows), default=None),
            "method": "SUS (Brooke, 1996); среднее по отрасли 68 (Sauro & Lewis); прилагательные — Bangor et al. (2009)"}


@admin_router.get("/sus", summary="Админка: все анкеты SUS (без ПДн: роль, контекст, ответы, балл, комментарий)",
                  responses={401: err("Не выполнен вход"), 403: err("Только для администратора")})
def admin_list(user: User = Depends(admin), db: Session = Depends(get_db),
               limit: int = Query(500, ge=1, le=2000)) -> dict:
    rows = db.scalars(select(SusResponse).order_by(SusResponse.created_at.desc()).limit(limit)).all()
    total = db.scalar(select(func.count()).select_from(SusResponse)) or 0
    return {"total": total, "summary": summary(True, db),
            "items": [{"id": str(r.id), "role": r.role, "context": r.context, "answers": r.answers, "score": r.score,
                       "comment": r.comment, "is_demo": r.is_demo, "created_at": r.created_at.isoformat()}
                      for r in rows]}
