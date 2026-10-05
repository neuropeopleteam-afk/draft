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
from app.modules.assessment.rules import apply_result
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateProfile


def _bank_sessions(db: Session, limit: int = 400) -> list[TestSession]:
    rows = db.scalars(select(TestSession).where(TestSession.status.in_(
        [TestSessionStatus.finished, TestSessionStatus.in_progress])).order_by(TestSession.created_at.desc())
        .limit(limit)).all()
    return [t for t in rows if str((t.result or {}).get("engine", "")).startswith("bank")]


def queue(db: Session, mode: str = "pending") -> dict:
    """mode: pending — ждут оценки; llm — оценены LLM (выборочная проверка вслепую); reviewed — проверены экспертом."""
    eng = get_engine("bank")
    items = []
    counts = {"pending": 0, "llm": 0, "reviewed": 0}
    for ts in _bank_sessions(db):
        prof = db.get(CandidateProfile, ts.user_id)
        for r in eng.review_items(ts.result.get("state", {})):
            kind = "reviewed" if r["expert"] else ("pending" if r["status"] == "pending" else "llm")
            counts[kind] += 1
            if kind != mode:
                continue
            g = r.pop("grading") or {}
            if mode == "llm":  # вслепую: балл и комментарий LLM не показываем до оценки эксперта
                r["score"], r["method"] = None, "llm"
            else:
                r["llm"] = {"score": g.get("score") if g.get("method") == "llm" else (g.get("expert") or {}).get("llm_score"),
                            "criteria": g.get("criteria") if g.get("method") == "llm" else None,
                            "comment": g.get("comment") if g.get("method") == "llm" else None, "error": g.get("error")}
            items.append({**r, "session_id": str(ts.id), "session_status": ts.status.value,
                          "candidate_ref": prof.public_ref if prof else None, "direction": ts.direction_id,
                          "claimed_grade": ts.claimed_grade_id,
                          "at": ts.finished_at.isoformat() if ts.finished_at else None})
    return {"mode": mode, "counts": counts, "items": items[:100]}


def submit(db: Session, session_id: uuid.UUID, token: str, part: int, criteria: dict[str, float],
           comment: str | None, reviewer: str) -> dict:
    ts = db.get(TestSession, session_id, with_for_update=True)
    if ts is None or not str((ts.result or {}).get("engine", "")).startswith("bank"):
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
    sandbox = service.is_sandbox(profile)
    current = profile.current_grade_id if profile.current_direction_id == ts.direction_id else None
    before = (ts.result.get("engine_result") or {}).get("confirmed")
    outcome = apply_result(current, ts.claimed_grade_id, res.confirmed, now, sandbox,
                           get_settings().grade_change_interval_days, profile.grade_locked_until)
    ts.theta, ts.theta_se = res.theta, res.se
    ts.score = res.correct / res.answered if res.answered else 0.0
    ts.result_grade_id = ts.claimed_grade_id if res.confirmed else ts.result_grade_id
    ts.result = {**ts.result, "engine_result": res.to_dict(), "recomputed_at": now.isoformat(),
                 "outcome": {"changed": outcome.changed, "grade": outcome.new_grade, "message": outcome.message}}
    flag_modified(ts, "result")
    if res.confirmed:
        if outcome.changed:
            db.add(GradeHistory(user_id=ts.user_id, direction_id=ts.direction_id, from_grade_id=current,
                                to_grade_id=outcome.new_grade, reason=GradeChangeReason(outcome.reason),
                                test_session_id=ts.id, locked_until=outcome.locked_until))
            profile.current_direction_id = ts.direction_id
            profile.current_grade_id = outcome.new_grade
            profile.current_category_id = f"{ts.direction_id}.{outcome.new_grade}"
            profile.grade_locked_until = outcome.locked_until
        service._write_t1_facts(db, ts, res)
        db.flush()
        refresh_rating(db, ts.user_id)
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
