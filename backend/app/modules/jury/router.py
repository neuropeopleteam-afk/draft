"""Режим жюри: вход в один клик под демо-персоной и сброс демо в исходное состояние (см. seed.py)."""
from __future__ import annotations

import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import api_error
from app.modules.auth.models import User
from app.modules.auth.service import issue_token
from app.modules.jury import seed

router = APIRouter(prefix="/api/jury", tags=["jury"])
_state = {"last_reset": 0.0}
_mx = threading.Lock()
LANDING = {"candidate": "/candidate", "candidate_nofsp": "/candidate", "employer": "/employer", "expert": "/expert",
           "fsp": "/fsp"}


class LoginIn(BaseModel):
    persona: Literal["candidate", "candidate_nofsp", "employer", "expert", "fsp"]


def _available() -> None:
    if not get_settings().jury_mode_available:
        raise api_error(404, "jury_disabled", "Режим жюри выключен")


@router.get("/status", summary="Персоны режима жюри")
def status(db: Session = Depends(get_db)):
    s = get_settings()
    have = set(db.scalars(select(User.email).where(User.email.in_(list(seed.EMAILS.values())))).all())
    return {"available": s.jury_mode_available,
            "personas": [{**p, "email": seed.EMAILS[p["id"]], "ready": seed.EMAILS[p["id"]] in have,
                          "landing": LANDING[p["id"]]} for p in seed.PERSONAS],
            "reset_cooldown_s": s.jury_reset_cooldown_s}


@router.post("/login", summary="Вход в один клик под демо-персоной жюри")
def login(data: LoginIn, db: Session = Depends(get_db)):
    _available()
    created = seed.ensure(db)
    user = db.scalar(select(User).where(User.email == seed.EMAILS[data.persona]))
    if user is None:
        raise api_error(503, "jury_not_ready", "Демо-учётки жюри ещё создаются, повторите через несколько секунд")
    tok = issue_token(user)
    return {**tok.model_dump(), "persona": data.persona, "landing": LANDING[data.persona], "created": created}


@router.post("/reset", summary="Сбросить демо жюри в исходное состояние")
def reset(db: Session = Depends(get_db)):
    _available()
    cd = get_settings().jury_reset_cooldown_s
    with _mx:
        left = cd - (time.time() - _state["last_reset"])
        if left > 0:
            raise api_error(429, "jury_reset_cooldown", f"Демо уже сбрасывали только что, повторите через {int(left) + 1} с")
        _state["last_reset"] = time.time()
    out = seed.reset(db)
    return {"ok": True, **out}
