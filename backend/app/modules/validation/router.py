"""Страница /validation («Как мы проверяем себя») и «Красная кнопка жюри» — публичный API."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import threading
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import TestSessionStatus
from app.core.errors import api_error
from app.modules.assessment.models import TestSession
from app.modules.validation import attacks

router = APIRouter(prefix="/api/validation", tags=["validation"])
REPORT = Path(__file__).resolve().parent / "data" / "report.json"
_leak_lock = threading.Lock()


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


@router.post("/attacks/{attack_id}", summary="Запустить атаку «Красной кнопки» (ничего не записывается)")
def run_attack(attack_id: str, data: AttackIn | None = None, db: Session = Depends(get_db)):
    data = data or AttackIn()
    if attack_id not in {a["id"] for a in attacks.ATTACKS}:
        raise api_error(404, "attack_not_found", "Нет такой атаки")
    if attack_id == "leak_bank":
        if not _leak_lock.acquire(blocking=False):  # симуляция тяжёлая: не больше одной одновременно на воркер
            raise api_error(429, "attack_busy", "Симуляция утечки уже идёт, повторите через несколько секунд")
        try:
            return attacks.run(db, attack_id, None, {"leak_share": data.leak_share, "direction": data.direction})
        finally:
            _leak_lock.release()
    return attacks.run(db, attack_id, data.need_id)


BENCH = Path(__file__).resolve().parent / "data" / "matching_bench.json"


@lru_cache(maxsize=1)
def _bench() -> dict:
    if not BENCH.exists():
        return {"missing": True}
    return json.loads(BENCH.read_text(encoding="utf-8"))


@router.get("/matching-bench", summary="Бенчмарк подбора со скрытой истиной (пересчёт: make bench)")
def matching_bench():
    return _bench()
