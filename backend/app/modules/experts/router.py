"""API экспертной разметки (/api/expert-panel/*): вход по ссылке, назначение, объекты, сохранение по ходу.

Эксперт панели — роль expert; демо-эксперт жюри получает демо-назначение (оценки в метрики не входят).
Администратор создаёт приглашения (или координатор — командой `python -m app.modules.experts invite E1`).
"""
from __future__ import annotations

from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error
from app.modules.auth.models import User
from app.modules.auth import twofa
from app.modules.auth.service import issue_token
from app.modules.experts import service

router = APIRouter(prefix="/api/expert-panel", tags=["expert-panel"])
expert = require_role(UserRole.expert, UserRole.admin)
admin = require_role(UserRole.admin)


class EnterIn(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)


class LabelIn(BaseModel):
    item_id: uuid.UUID
    value: dict[str, Any]
    comment: str | None = Field(None, max_length=2000)
    seconds: int | None = Field(None, ge=0, le=36000)


class InviteIn(BaseModel):
    code: str = Field(..., pattern=r"^E[1-9]$")
    slot: Literal["E1", "E2", "E3"] | None = None
    team_size: int = Field(3, ge=2, le=3)
    name: str | None = Field(None, max_length=120)
    profile: str | None = Field(None, max_length=255)
    rotate: bool = False


def _panelist(db: Session, user: User):
    pan = service.panelist_for(db, user)
    if pan is None:
        raise api_error(404, "not_in_panel", "Вы не в панели экспертной разметки: войдите по персональной ссылке")
    return pan


@router.post("/enter", summary="Вход эксперта по персональной ссылке (без регистрации)")
def enter(data: EnterIn, db: Session = Depends(get_db)):
    user, pan = service.enter(db, data.token)
    if twofa.enabled(db, user):  # эксперт по желанию подключил приложение: ссылка + код
        return twofa.challenge(user, None, code=pan.code, landing="/expert").model_dump()
    tok = issue_token(user)
    return {**tok.model_dump(), "code": pan.code, "landing": "/expert"}


@router.get("/me", summary="Эксперт панели: код, прогресс по блокам A, B, C")
def me(db: Session = Depends(get_db), user: User = Depends(expert)):
    pan = service.panelist_for(db, user)
    if pan is None:
        return {"in_panel": False}
    return {"in_panel": True, **service.me(db, pan)}


@router.post("/ack", summary="Инструкция прочитана")
def ack(db: Session = Depends(get_db), user: User = Depends(expert)):
    return service.ack_instructions(db, _panelist(db, user))


@router.get("/items/{kind}", summary="Объекты назначения (вслепую) с сохранёнными оценками")
def items(kind: Literal["A", "B", "C"], db: Session = Depends(get_db), user: User = Depends(expert)):
    return service.items_for(db, _panelist(db, user), kind)


@router.post("/labels", summary="Сохранить оценку (перезаписывается при правке)")
def label(data: LabelIn, db: Session = Depends(get_db), user: User = Depends(expert)):
    return service.save_label(db, _panelist(db, user), data.item_id, data.value, data.comment, data.seconds)


@router.post("/invites", summary="Создать приглашение эксперту (администратор)")
def invite(data: InviteIn, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.create_invite(db, data.code, slot=data.slot, team_size=data.team_size, name=data.name,
                                 profile=data.profile, rotate=data.rotate)


@router.get("/status", summary="Статус панели (администратор)")
def status(db: Session = Depends(get_db), user: User = Depends(admin)):
    return {"panel": service.panel_status(db)}
