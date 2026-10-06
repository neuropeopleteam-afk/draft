"""Страница /validation («Как мы проверяем себя») и «Красная кнопка жюри».

Отчёт — публичный. Атаки — только после входа (любая роль; в режиме жюри фронтенд сам входит под демо-персоной
своей песочницы — кнопка остаётся «в один клик»), с лимитом частоты на пользователя и общим лимитом;
need_id — только потребность своей компании; симуляция утечки — из кэша (attacks.leak_cached).
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.enums import TestSessionStatus, UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, hit
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import EmployerProfile
from app.modules.validation import attacks

router = APIRouter(prefix="/api/validation", tags=["validation"])
REPORT = Path(__file__).resolve().parent / "data" / "report.json"
# Лимиты «Красной кнопки» (на воркер): 12 атак в минуту на пользователя, 90 в минуту всего
_per_user = SlidingWindow(12, 60)
_global = SlidingWindow(90, 60)


@lru_cache(maxsize=1)
def _report() -> dict:
    if not REPORT.exists():
        return {"missing": True}
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _live(db: Session) -> dict:
    from app.modules.assessment.exposure import exposure_table
    from app.modules.assessment.review import agreement

    rows = db.scalars(select(TestSession).where(TestSession.status == TestSessionStatus.finished)
                      .order_by(TestSession.created_at.desc()).limit(2000)).all()
    bank = [t for t in rows if str((t.result or {}).get("engine", "")).startswith("bank")]
    levels = {"high": 0, "medium": 0, "low": 0}
    flagged = 0
    for t in bank:
        d = ((t.result or {}).get("engine_result") or {}).get("details") or {}
        lv = (d.get("integrity") or {}).get("level")
        if lv in levels:
            levels[lv] += 1
        flagged += 1 if (d.get("preknowledge") or {}).get("flagged") else 0
    total = db.scalar(select(func.count()).select_from(TestSession)) or 0
    exp = exposure_table() or {}
    return {"sessions_total": total, "bank_sessions_finished": len(bank), "integrity": levels,
            "preknowledge_flagged": flagged, "expert_llm_agreement": agreement(db),
            "exposure_k": {"generated_at": exp.get("generated_at"), "r_max": exp.get("r_max"),
                           "families_limited": {d: len(v) for d, v in (exp.get("k") or {}).items()}}}


@router.get("/report", summary="Метрики валидации (пересчёт: make validate)")
def report(db: Session = Depends(get_db)):
    return {**_report(), "live": _live(db), "attacks": attacks.ATTACKS}


class AttackIn(BaseModel):
    need_id: uuid.UUID | None = None
    leak_share: float = Field(0.3, ge=0.1, le=0.8)
    direction: str | None = None


def _own_need(db: Session, user: User, need_id: uuid.UUID) -> uuid.UUID:
    """need_id — только потребность компании текущего работодателя (иначе 404, как для несуществующей)."""
    ep = db.get(EmployerProfile, user.id) if user.role == UserRole.employer else None
    n = db.get(EmployerNeed, need_id)
    if ep is None or n is None or n.company_id != ep.company_id:
        raise api_error(404, "need_not_found", "Потребность не найдена")
    return need_id


@router.post("/attacks/{attack_id}", summary="Запустить атаку «Красной кнопки» (вход обязателен, ничего не записывается)",
             responses={401: err("Не выполнен вход"), 404: err("Нет такой атаки или потребности"),
                        429: err("Слишком частые запуски")})
def run_attack(attack_id: str, data: AttackIn | None = None, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    data = data or AttackIn()
    if attack_id not in {a["id"] for a in attacks.ATTACKS}:
        raise api_error(404, "attack_not_found", "Нет такой атаки")
    hit(_per_user, str(user.id), "attack_rate", "Слишком часто: не больше 12 атак в минуту")
    hit(_global, "all", "attack_rate_global", "Красную кнопку сейчас нажимают слишком часто")
    if attack_id == "leak_bank":
        try:
            return attacks.run(db, attack_id, None, {"leak_share": data.leak_share, "direction": data.direction})
        except attacks.AttackBusy:
            raise api_error(429, "attack_busy", "Симуляция утечки уже идёт, повторите через несколько секунд") from None
    need_id = _own_need(db, user, data.need_id) if data.need_id else None
    return attacks.run(db, attack_id, need_id)
