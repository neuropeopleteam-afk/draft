"""Сервис тестирования: хранение сессий, применение правил грейда, запись фактов T1.

С движком (заглушка или банк) общается только через протокол AssessmentEngine (engine.py).
"""
from __future__ import annotations

from datetime import timedelta
import secrets
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource, GradeChangeReason, TestSessionStatus
from app.core.errors import api_error
from app.modules.assessment.engine import get_engine
from app.modules.assessment.models import GradeHistory, SurveyResponse, TestSession
from app.modules.assessment.rules import apply_result, check_can_start
from app.modules.catalog.seed_data import STACK
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateFact, CandidateProfile


def is_sandbox(profile: CandidateProfile) -> bool:
    s = get_settings()
    return s.demo_sandbox or (s.jury_mode_available and profile.jury_mode)


def latest_survey(db: Session, user_id: uuid.UUID) -> SurveyResponse | None:
    return db.scalar(select(SurveyResponse).where(SurveyResponse.user_id == user_id)
                     .order_by(SurveyResponse.created_at.desc()).limit(1))


def active_session(db: Session, user_id: uuid.UUID) -> TestSession | None:
    return db.scalar(select(TestSession).where(
        TestSession.user_id == user_id,
        TestSession.status.in_([TestSessionStatus.created, TestSessionStatus.in_progress]),
    ).order_by(TestSession.created_at.desc()).limit(1))


def start_session(db: Session, user_id: uuid.UUID, claimed_grade: str) -> TestSession:
    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id)
    if profile is None or survey is None or profile.onboarding_completed_at is None:
        raise api_error(409, "onboarding_required", "Сначала пройдите опрос: направление, стек и опыт")
    now = utcnow()
    check = check_can_start(profile.current_grade_id, profile.grade_locked_until, claimed_grade, now,
                            is_sandbox(profile))
    if not check.allowed:
        raise api_error(409 if check.code == "grade_locked" else 422, check.code or "not_allowed", check.message or "")
    old = active_session(db, user_id)
    if old is not None:
        if old.claimed_grade_id == claimed_grade and old.direction_id == survey.direction_id:
            return old
        old.status = TestSessionStatus.aborted
        old.finished_at = now
    engine = get_engine()
    seed = secrets.randbelow(2**31)
    stack = list((survey.answers or {}).get("stack", {}).keys())
    state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed)
    ts = TestSession(
        user_id=user_id, survey_id=survey.id, direction_id=survey.direction_id, claimed_grade_id=claimed_grade,
        status=TestSessionStatus.in_progress, form_seed=seed, is_sandbox=is_sandbox(profile), started_at=now,
        deadline_at=now + timedelta(minutes=30), result={"engine": engine.name, "state": state},
    )
    db.add(ts)
    db.commit()
    return ts


def get_own_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> TestSession:
    ts = db.get(TestSession, session_id)
    if ts is None or ts.user_id != user_id:
        raise api_error(404, "session_not_found", "Сессия теста не найдена")
    return ts


def next_item(ts: TestSession):
    if ts.status != TestSessionStatus.in_progress:
        return None
    return get_engine(_engine_key(ts)).next_item(ts.result["state"])


def _engine_key(ts: TestSession) -> str:
    return "bank" if str(ts.result.get("engine", "")).startswith("bank") else "stub"


def submit_answer(db: Session, ts: TestSession, item_id: str, answer, time_spent_ms: int | None):
    if ts.status != TestSessionStatus.in_progress:
        raise api_error(409, "session_closed", "Сессия теста уже завершена")
    if ts.deadline_at and utcnow() > as_aware(ts.deadline_at):
        ts.status = TestSessionStatus.expired
        db.commit()
        raise api_error(409, "session_expired", "Время на тест истекло — начните заново")
    state = ts.result["state"]
    fb = get_engine(_engine_key(ts)).answer(state, item_id, answer, time_spent_ms)
    if not fb.accepted:
        raise api_error(422, "answer_rejected", "Ответ не принят: задание уже отвечено или вариант не существует")
    flag_modified(ts, "result")
    db.commit()
    return fb


def finish_session(db: Session, ts: TestSession) -> dict:
    if ts.status == TestSessionStatus.finished:
        return ts.result.get("outcome", {})
    if ts.status != TestSessionStatus.in_progress:
        raise api_error(409, "session_closed", "Сессия теста уже закрыта")
    profile = db.get(CandidateProfile, ts.user_id)
    res = get_engine(_engine_key(ts)).finish(ts.result["state"])
    now = utcnow()
    sandbox = is_sandbox(profile)
    # Тест в другом направлении: подтверждённый грейд считается «нет» для правил (категория — пара направление·грейд)
    current = profile.current_grade_id if profile.current_direction_id == ts.direction_id else None
    outcome = apply_result(current, ts.claimed_grade_id, res.confirmed, now, sandbox,
                           get_settings().grade_change_interval_days, profile.grade_locked_until)
    ts.status = TestSessionStatus.finished
    ts.finished_at = now
    ts.theta, ts.theta_se = res.theta, res.se
    ts.score = res.correct / res.answered if res.answered else 0.0
    ts.result_grade_id = ts.claimed_grade_id if res.confirmed else None
    ts.result = {**ts.result, "engine_result": res.to_dict(),
                 "outcome": {"changed": outcome.changed, "grade": outcome.new_grade, "message": outcome.message}}

    if outcome.changed or (res.confirmed and outcome.new_grade == ts.claimed_grade_id):
        if outcome.changed:
            db.add(GradeHistory(user_id=ts.user_id, direction_id=ts.direction_id, from_grade_id=current,
                                to_grade_id=outcome.new_grade, reason=GradeChangeReason(outcome.reason),
                                test_session_id=ts.id, locked_until=outcome.locked_until))
            profile.current_direction_id = ts.direction_id
            profile.current_grade_id = outcome.new_grade
            profile.current_category_id = f"{ts.direction_id}.{outcome.new_grade}"
            profile.grade_locked_until = outcome.locked_until
        _write_t1_facts(db, ts, res)
        db.flush()
        refresh_rating(db, ts.user_id)
    db.commit()
    return {
        "session_id": str(ts.id), "theta": res.theta, "se": res.se, "claimed_grade": ts.claimed_grade_id,
        "point_grade": res.point_grade, "confirmed": res.confirmed, "upgrade_available": res.upgrade_available,
        "retake_lower": res.retake_lower, "probabilities": res.probabilities, "correct": res.correct,
        "answered": res.answered, "explanation": res.explanation, "grade_changed": outcome.changed,
        "current_grade": profile.current_grade_id, "category_id": profile.current_category_id,
        "message": outcome.message, "engine": res.engine,
        "locked_until": as_aware(profile.grade_locked_until).isoformat() if profile.grade_locked_until else None,
    }


def _write_t1_facts(db: Session, ts: TestSession, res) -> None:
    """Результат теста и навыки, проверенные заданиями, — факты T1 (заменяют прежние факты теста)."""
    db.execute(delete(CandidateFact).where(CandidateFact.user_id == ts.user_id, CandidateFact.source == FactSource.test))
    db.add(CandidateFact(
        user_id=ts.user_id, kind="test_result", key=f"{ts.direction_id}.{ts.claimed_grade_id}",
        title=f"Тест {ts.direction_id} · {ts.claimed_grade_id}",
        value={"theta": res.theta, "se": res.se, "grade": ts.claimed_grade_id, "confirmed": res.confirmed,
               "correct": res.correct, "answered": res.answered, "engine": res.engine, "session_id": str(ts.id)},
        evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
    ))
    for tag, s in res.skills.items():
        db.add(CandidateFact(
            user_id=ts.user_id, kind="skill", key=tag, title=STACK.get(tag, (tag,))[0],
            value={"score": s["score"], "correct": s["correct"], "total": s["total"]},
            evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
        ))


def status(db: Session, user_id: uuid.UUID) -> dict:
    from app.modules.catalog.models import Category

    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id)
    now = utcnow()
    sandbox = is_sandbox(profile)
    lock = as_aware(profile.grade_locked_until)
    sessions = db.scalars(select(TestSession).where(TestSession.user_id == user_id)
                          .order_by(TestSession.created_at.desc()).limit(20)).all()
    history = db.scalars(select(GradeHistory).where(GradeHistory.user_id == user_id)
                         .order_by(GradeHistory.created_at.desc())).all()
    surveys = db.scalars(select(SurveyResponse).where(SurveyResponse.user_id == user_id)
                         .order_by(SurveyResponse.created_at.desc()).limit(10)).all()
    cat = db.get(Category, profile.current_category_id) if profile.current_category_id else None
    rank = total = None
    if cat is not None:
        peers = db.scalars(select(CandidateProfile.rating_score).where(
            CandidateProfile.current_category_id == cat.id, CandidateProfile.visible_to_employers.is_(True))).all()
        total = len(peers) + (0 if profile.visible_to_employers else 1)
        mine = profile.rating_score or 0
        rank = 1 + sum(1 for r in peers if (r or 0) > mine)
    active = active_session(db, user_id)
    return {
        "onboarding_completed": profile.onboarding_completed_at is not None,
        "survey_direction": survey.direction_id if survey else None,
        "claimed_grade": survey.claimed_grade_id if survey else None,
        "current": {
            "direction": profile.current_direction_id, "grade": profile.current_grade_id,
            "category_id": profile.current_category_id, "category_title": cat.title if cat else None,
            "rating_score": profile.rating_score, "rank": rank, "category_size": total,
            "market_range": {"from": cat.market_salary_from, "to": cat.market_salary_to,
                             "median": cat.market_salary_median} if cat else None,
        },
        "locked_until": lock.isoformat() if lock else None,
        "lock_active": bool(lock and now < lock),
        "can_retest_now": not (lock and now < lock) or sandbox,
        "jury_mode": profile.jury_mode, "jury_mode_available": get_settings().jury_mode_available,
        "sandbox_active": sandbox,
        "grade_change_interval_days": get_settings().grade_change_interval_days,
        "active_session_id": str(active.id) if active else None,
        "engine": get_engine().name,
        "sessions": [{
            "id": str(s.id), "direction": s.direction_id, "claimed_grade": s.claimed_grade_id, "status": s.status.value,
            "theta": s.theta, "se": s.theta_se, "confirmed": (s.result or {}).get("engine_result", {}).get("confirmed"),
            "message": (s.result or {}).get("outcome", {}).get("message"), "is_sandbox": s.is_sandbox,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        } for s in sessions],
        "grade_history": [{
            "from": h.from_grade_id, "to": h.to_grade_id, "direction": h.direction_id, "reason": h.reason.value,
            "at": h.created_at.isoformat(), "locked_until": h.locked_until.isoformat() if h.locked_until else None,
        } for h in history],
        "surveys": [{"id": str(s.id), "direction": s.direction_id, "claimed_grade": s.claimed_grade_id,
                     "at": s.created_at.isoformat()} for s in surveys],
    }
