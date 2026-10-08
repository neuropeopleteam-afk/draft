"""Экспертная проверка развёрнутых ответов (open_answer, шаг 3 open_book_3step) по рубрике.

* Очередь «на проверке»: ответы, которые LLM не оценил (недоступен, сбой, невалидный ответ модели). Пока ответ
  не оценён, он не входит в θ и результат помечен «предварительный». Оценка эксперта по критериям рубрики
  (0 / 0,5 / 1 с весами) входит в θ, результат сессии пересчитывается: грейд может быть подтверждён
  (принудительного понижения по-прежнему нет).
* Выборочная проверка оценок LLM (вслепую: балл LLM показывается после оценки эксперта). Пары «LLM — эксперт»
  копятся для выбора модели оценщика по согласию с экспертами (решение владельца 05.10); сводка — на /validation.

Доступ — роль admin (эксперт). Кандидат свои оценки по критериям не видит, видит итог теста.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.enums import GradeChangeReason, TestSessionStatus
from app.core.errors import api_error
from app.modules.assessment import service
from app.modules.assessment.engine import get_engine
from app.modules.assessment.models import GradeHistory, TestSession
from app.modules.auth.models import User
from app.modules.jury import scope as jury_scope
from app.modules.assessment.rules import apply_result
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateProfile
from app.modules.profiles.specializations import ensure_specialization


def _bank_sessions(db: Session, limit: int = 400, demo_only: bool = False) -> list[TestSession]:
    q = select(TestSession).where(TestSession.status.in_([TestSessionStatus.finished, TestSessionStatus.in_progress]))
    if demo_only:  # демо-эксперт жюри видит только демо-кандидатов, из песочниц жюри — только своей
        q = q.join(User, User.id == TestSession.user_id).where(User.is_demo.is_(True), jury_scope.pool_clause(User.email))
    rows = db.scalars(q.order_by(TestSession.created_at.desc()).limit(limit)).all()
    return [t for t in rows if str((t.result or {}).get("engine", "")).startswith("bank")]


LLM_METHODS = ("llm", "llm2")


def queue(db: Session, mode: str = "pending", demo_only: bool = False) -> dict:
    """mode: pending — ждут оценки; llm — оценены LLM (выборочная проверка вслепую); reviewed — проверены экспертом."""
    eng = get_engine("bank")
    items = []
    counts = {"pending": 0, "llm": 0, "reviewed": 0}
    for ts in _bank_sessions(db, demo_only=demo_only):
        prof = db.get(CandidateProfile, ts.user_id)
        for r in eng.review_items(ts.result.get("state", {})):
            if r["expert"]:
                kind = "reviewed"
            elif r["status"] == "pending":
                kind = "pending"
            elif r["method"] in LLM_METHODS:  # llm2 — среднее двух оценок (grader: вторая оценка при сомнении)
                kind = "llm"
            else:  # оценено правилом (пустой/короткий ответ) или демо-экспертом — не для выборочной проверки LLM
                continue
            counts[kind] += 1
            if kind != mode:
                continue
            g = r.pop("grading") or {}
            if mode == "llm":  # вслепую: балл и комментарий LLM не показываем до оценки эксперта
                r["score"], r["method"] = None, "llm"
            else:
                by_llm = g.get("method") in LLM_METHODS
                r["llm"] = {"score": g.get("score") if by_llm else (g.get("expert") or {}).get("llm_score"),
                            "criteria": g.get("criteria") if by_llm else None,
                            "comment": g.get("comment") if by_llm else None, "error": g.get("error"),
                            "quotes": g.get("quotes") if by_llm else None, "scores": g.get("scores") or None,
                            # промпт-инъекция (grader.injection_signals): ответ в LLM не уходил, причина — эксперту
                            "flags": g.get("flags") or [],
                            "injection_note": g.get("comment") if g.get("error") == "prompt_injection_suspected" else None}
            items.append({**r, "session_id": str(ts.id), "session_status": ts.status.value,
                          "candidate_ref": prof.public_ref if prof else None, "direction": ts.direction_id,
                          "claimed_grade": ts.claimed_grade_id,
                          "at": ts.finished_at.isoformat() if ts.finished_at else None})
    return {"mode": mode, "counts": counts, "items": items[:100]}


def submit(db: Session, session_id: uuid.UUID, token: str, part: int, criteria: dict[str, float],
           comment: str | None, reviewer: str, demo_only: bool = False) -> dict:
    ts = db.get(TestSession, session_id, with_for_update=True)
    if ts is None or not str((ts.result or {}).get("engine", "")).startswith("bank"):
        raise api_error(404, "session_not_found", "Сессия теста не найдена")
    if demo_only:
        owner = db.get(User, ts.user_id)
        # сессии реальных пользователей и чужих песочниц жюри демо-эксперту недоступны
        if owner is None or not owner.is_demo or not jury_scope.visible(owner.email):
            raise api_error(404, "session_not_found", "Сессия теста не найдена")
    state = ts.result["state"]
    eng = get_engine("bank")
    rec = eng.apply_review(state, token, part, criteria, comment, reviewer)
    if rec is None:
        raise api_error(422, "review_rejected", "Оценка не принята: нет такого ответа или не все критерии рубрики оценены")
    service._drain_outbox(db, ts)
    flag_modified(ts, "result")
    out = {"review": rec, "recomputed": False}
    if ts.status == TestSessionStatus.finished and rec.get("applied"):
        out.update(recompute(db, ts))
        out["recomputed"] = True
    db.commit()
    return out


def recompute(db: Session, ts: TestSession) -> dict:
    """Пересчёт завершённой сессии после экспертной оценки: θ, решение по грейду, факты T1, рейтинг."""
    res = get_engine("bank").finish(ts.result["state"])
    profile = db.get(CandidateProfile, ts.user_id)
    now = utcnow()
    before = (ts.result.get("engine_result") or {}).get("confirmed")
    keep_grade = ts.result_grade_id
    # after_review: паспорт грейда «предварительно» → «подтверждён» сразу после оценки эксперта (app/passport)
    outcome = service.apply_engine_result(db, ts, res, profile, now, after_review=True)
    ts.result = {**ts.result, "recomputed_at": now.isoformat()}
    flag_modified(ts, "result")
    if not res.confirmed:
        ts.result_grade_id = keep_grade
    return {"theta": res.theta, "se": res.se, "confirmed": res.confirmed, "confirmed_before": before,
            "pending_left": (res.details or {}).get("pending_review"), "message": outcome.message}


def agreement(db: Session) -> dict:
    """Согласие LLM и эксперта на ответах, которые оценили оба (MAE, доля совпадения уровня ±0,25)."""
    pairs = []
    for ts in _bank_sessions(db, limit=2000):
        for it in ts.result.get("state", {}).get("items", []):
            for part, rec in (it.get("expert_reviews") or {}).items():
                if rec.get("llm_score") is not None:
                    pairs.append((float(rec["llm_score"]), float(rec["score"])))
    if not pairs:
        return {"n": 0}
    d = [abs(a - b) for a, b in pairs]
    return {"n": len(pairs), "mae": round(sum(d) / len(d), 3),
            "within_025": round(sum(1 for x in d if x <= 0.25) / len(d), 3)}
